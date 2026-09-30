"""Job context shared by workflows, plus a thread → generator bridge for streaming UIs."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import queue
import threading
import time
from typing import Any, Callable, Iterator


class Cancelled(Exception):
    """The user stopped the job."""


class UserError(ValueError):
    """An input problem to show to the user; `key` indexes the translation table."""

    def __init__(self, key, **params):
        super().__init__(key)
        self.key, self.params = key, params


@dataclass
class Event:
    kind: str                      # stage | tokens | score | song | tick | done | error
    data: dict = field(default_factory=dict)


class JobContext:
    def __init__(self, emit: Callable[[Event], None] | None = None, cancel: threading.Event | None = None,
                 lang: str = "en"):
        self._emit = emit
        self.cancel_event = cancel or threading.Event()
        self.lang = lang                # language for text the job writes (e.g. generated titles)

    def emit(self, kind, **data):
        if self._emit is not None:
            self._emit(Event(kind, data))

    def stage(self, name, **data):
        self.emit("stage", stage=name, **data)

    def cancelled(self):
        return self.cancel_event.is_set()

    def check(self):
        if self.cancelled():
            raise Cancelled()


class TokenCounter:
    """on_token callback that reports progress at most every `interval` seconds."""

    def __init__(self, ctx, phase, interval=0.4):
        self.ctx, self.phase, self.interval = ctx, phase, interval
        self.count, self._last, self.started = 0, 0.0, time.monotonic()

    def __call__(self, _phase, _token):
        self.count += 1
        now = time.monotonic()
        if now - self._last >= self.interval:
            self._last = now
            self.ctx.emit("tokens", phase=self.phase, count=self.count, elapsed=now - self.started)


@dataclass
class Job:
    """A running job: its cancel flag, a flag set when the worker has finished, and its song."""
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    song_id: str | None = None


class JobRegistry:
    """Remembers each session's latest job so a Stop button can cancel it.

    Finished jobs are kept (bounded) because a Stop click may race the end of the
    job it targets; the handler still needs that job's song to show what was kept.
    """

    def __init__(self, limit=256):
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()
        self._limit = limit

    def start(self, key):
        job = Job()
        with self._lock:
            self._jobs.pop(key, None)
            self._jobs[key] = job
            while len(self._jobs) > self._limit:
                self._jobs.popitem(last=False)
        return job

    def cancel(self, key):
        """Flag the session's latest job; returns it (or None) so callers can wait on `done`."""
        with self._lock:
            job = self._jobs.get(key)
        if job is not None:
            job.cancel.set()
        return job


def stream(fn: Callable[[JobContext], Any], cancel: threading.Event | None = None, tick: float = 1.0,
           done: threading.Event | None = None, lang: str = "en") -> Iterator[Event]:
    """Run fn(ctx) on a worker thread and yield its events; ends with done or error.

    Closing the generator (e.g. a cancelled Gradio event) sets the cancel flag so
    the model loop stops at its next cancellation check.
    """
    events: queue.Queue = queue.Queue()
    ctx = JobContext(events.put, cancel, lang)

    def worker():
        try:
            events.put(Event("done", {"result": fn(ctx)}))
        except (Cancelled, InterruptedError):
            events.put(Event("error", {"cancelled": True}))
        except BaseException as exc:  # surfaced to the UI instead of killing the thread silently
            events.put(Event("error", {"exception": exc}))
        finally:
            if done is not None:
                done.set()

    thread = threading.Thread(target=worker, name="studio-job", daemon=True)
    thread.start()
    try:
        while True:
            try:
                event = events.get(timeout=tick)
            except queue.Empty:
                if not thread.is_alive() and events.empty():
                    return
                # Long silent phases (acoustic synthesis, decoding) still refresh elapsed time.
                event = Event("tick")
            yield event
            if event.kind in {"done", "error"}:
                return
    finally:
        if thread.is_alive():
            ctx.cancel_event.set()
