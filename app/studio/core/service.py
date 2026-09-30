"""Studio: the single entry point shared by the Gradio UI, the API, and tests."""
from __future__ import annotations

from . import scores, styles
from .assist import LyricsAssistant, LyricsRequest
from .engine import Engine
from .jobs import JobContext, JobRegistry, UserError, stream
from .store import SongNotFound, SongStore
from .workflows import WORKFLOWS


class Studio:
    def __init__(self, settings, engine=None, assistant=None):
        self.settings = settings
        self.store = SongStore(settings.data_dir)
        self.engine = engine or Engine(settings)
        self.assistant = assistant or LyricsAssistant()
        self.jobs = JobRegistry()

    # -- workflows ------------------------------------------------------------
    def workflow(self, name):
        if name not in WORKFLOWS:
            raise KeyError(f"Unknown workflow {name!r}")
        return WORKFLOWS[name](self)

    def _runner(self, name, params):
        workflow = self.workflow(name)
        params = workflow.validate(**params)       # fail fast, before waiting for the GPU

        def run(ctx):
            if not workflow.uses_gpu:
                return workflow.run(ctx, **params)
            with self.engine.gpu(name):
                ctx.check()
                return workflow.run(ctx, **params)
        return run

    def run(self, name, ctx=None, *, lang="en", **params):
        """Blocking call; returns the resulting SongMeta."""
        return self._runner(name, params)(ctx or JobContext(lang=lang))

    def stream(self, name, *, session=None, lang="en", **params):
        """Yield job events; a Stop request for `session` cancels the running job."""
        run = self._runner(name, params)
        job = self.jobs.start(session) if session else None
        for event in stream(run, job.cancel if job else None, done=job.done if job else None, lang=lang):
            if job is not None and event.kind == "song":
                job.song_id = event.data["song_id"]
            yield event

    def cancel(self, session, wait=0.0):
        """Stop the session's job. With `wait`, block until its worker has recorded the outcome.

        Returns the job's song id ("" when the job had not created a song yet), or None
        when nothing was running.
        """
        job = self.jobs.cancel(session)
        if job is None:
            return None
        if wait:
            job.done.wait(wait)
        return job.song_id or ""

    # -- lyric assistant ------------------------------------------------------
    def lyrics_request(self, style="", lyrics="", title="", theme="", melody_abc=None, source_id=None, lang="en"):
        """Build an assistant request; a score (given or from a library song) makes it fit that melody."""
        if not self.assistant.available:
            raise UserError("error.assist_unavailable")
        if not melody_abc and source_id and self.store.exists(source_id):
            melody_abc = self.store.read_score(source_id)
        melody = []
        if melody_abc:
            try:
                melody = [s for s in scores.melody_outline(melody_abc) if s["phrases"] or s["label"] != "verse"]
            except ValueError:
                melody = []
        if not (style or "").strip() and not (lyrics or "").strip() and not (theme or "").strip() and not melody:
            raise UserError("error.assist_needs_input")
        return LyricsRequest(style=style or "", title=title or "", theme=theme or "", lyrics=lyrics or "",
                             melody=melody, ui_lang=lang)

    def stream_lyrics(self, request):
        """Yield the lyrics written so far; errors become UserError for the UI."""
        try:
            yield from self.assistant.stream(request)
        except UserError:
            raise
        except Exception as exc:
            raise UserError("error.assist_failed", detail=f"{type(exc).__name__}: {exc}") from exc

    # -- library --------------------------------------------------------------
    def song(self, song_id):
        """Everything a client needs to show one song."""
        meta = self.store.get(song_id)
        path = lambda p: str(p) if p else None  # noqa: E731
        return {**meta.to_dict(),
                "score": self.store.read_score(song_id),
                "audio": path(self.store.file(song_id, SongStore.AUDIO)),
                "preview": path(self.store.playable_audio(song_id)),
                "source_audio": path(self.store.source_audio(song_id)),
                "has_plan": self.store.file(song_id, SongStore.PLAN) is not None,
                "lineage": [m.id for m in self.store.lineage(song_id)]}

    def songs(self, operation=None, query=None):
        return [m.to_dict() for m in self.store.list(operation or None, query or None)]

    def check_score(self, abc, source_id=None):
        info = scores.inspect(abc)
        if source_id and info["ok"] and self.store.exists(source_id) and self.store.read_score(source_id):
            info["changes"] = scores.compare(self.store.read_score(source_id), abc)
        return info

    @staticmethod
    def style_options():
        return styles.options()

    @staticmethod
    def compose_style(**values):
        return styles.compose_style(**values)


__all__ = ["Studio", "UserError", "SongNotFound"]
