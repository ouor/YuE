"""Workflow base class, registry, and the shared plan → render steps."""
from __future__ import annotations

from contextlib import contextmanager
import random
import re

import numpy as np

from .. import audio
from ..jobs import Cancelled, UserError
from ..models import Status
from ..store import SongStore

WORKFLOWS: dict[str, type["Workflow"]] = {}


def register(cls):
    """Class decorator: make a workflow available to the UI and API by name."""
    WORKFLOWS[cls.name] = cls
    return cls


def resolve_seed(seed):
    """None or a negative value means "surprise me"."""
    if seed is None or seed == "" or int(seed) < 0:
        return random.randrange(2**31)
    return int(seed)


def require(value, key):
    if not isinstance(value, str) or not value.strip():
        raise UserError(key)
    return value.strip()


def auto_title(lyrics="", style="", fallback="Untitled"):
    for line in (lyrics or "").splitlines():
        line = line.strip()
        if line and not re.fullmatch(r"\[[^\]]*\]", line):
            return line[:40]
    return (style or "").split(",")[0].strip()[:40] or fallback


def derived_title(parent, label):
    """'<original title> · <label>' — without piling up labels from earlier versions."""
    return f"{parent.title.split(' · ')[0]} · {label}"


class Workflow:
    """One user-facing feature. Subclasses set `name`, and implement validate() and run()."""

    name = ""
    uses_gpu = True

    def __init__(self, studio):
        self.studio = studio
        self.store: SongStore = studio.store
        self.engine = studio.engine

    def validate(self, **params) -> dict:
        """Normalize inputs before queuing for the GPU; raise UserError for bad input."""
        return params

    def run(self, ctx, **params):
        raise NotImplementedError

    # -- shared steps -------------------------------------------------------
    def source(self, song_id, *, need_score=True):
        if not song_id or not self.store.exists(song_id):
            raise UserError("error.song_missing")
        if need_score and not self.store.read_score(song_id):
            raise UserError("error.song_no_score")
        return self.store.get(song_id)

    @contextmanager
    def guard(self, meta):
        """Record failures and cancellations on the song so the library stays truthful."""
        try:
            yield
        except (Cancelled, InterruptedError):
            has_plan = self.store.file(meta.id, SongStore.PLAN) is not None
            # A saved plan can still be rendered later, so a cancelled render stays usable.
            self.store.update(meta.id, status=Status.PLANNED if has_plan else Status.CANCELLED)
            raise
        except UserError as exc:
            self.store.update(meta.id, status=Status.FAILED, error=exc.key)
            raise
        except Exception as exc:
            self.store.update(meta.id, status=Status.FAILED, error=f"{type(exc).__name__}: {exc}")
            raise

    def plan_into(self, meta, request, ctx):
        """Plan (or accept the provided score), then persist it before any audio work."""
        ctx.stage("plan", song_id=meta.id)
        plan = self.engine.plan(request, ctx)
        ctx.check()
        plan.save(self.store.path(meta.id) / SongStore.PLAN)
        if plan.abc:
            self.store.write_text(meta.id, SongStore.SCORE, plan.abc)
        self.store.update(meta.id, truncated={"abc": plan.truncated}, timing={"plan": plan.timing})
        ctx.emit("score", song_id=meta.id, abc=plan.abc or "")
        return plan

    def render_into(self, meta, plan, ctx):
        """Render audio for a plan and store every artifact on the song."""
        self.store.update(meta.id, status=Status.RENDERING, error=None)
        result = self.engine.render(plan, ctx)
        directory = self.store.path(meta.id)
        audio.write_flac(directory / SongStore.AUDIO, result.audio)
        np.save(directory / SongStore.LATENT, np.asarray(result.latents, dtype=np.float32))
        np.save(directory / SongStore.SEMANTIC, np.asarray(result.semantic_tokens, dtype=np.int32))
        audio.make_preview(directory / SongStore.AUDIO, directory / SongStore.PREVIEW)
        current = self.store.get(meta.id)
        updated = self.store.update(meta.id, status=Status.COMPLETE, duration=round(len(result.audio) / audio.SAMPLE_RATE, 2),
                                    truncated=result.truncated, timing={**current.timing, "render": result.timing})
        ctx.emit("song", song_id=meta.id)
        return updated
