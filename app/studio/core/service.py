"""Studio: the single entry point shared by the Gradio UI, the API, and tests."""
from __future__ import annotations

from . import scores, styles
from .engine import Engine
from .jobs import JobContext, JobRegistry, UserError, stream
from .store import SongNotFound, SongStore
from .workflows import WORKFLOWS


class Studio:
    def __init__(self, settings, engine=None):
        self.settings = settings
        self.store = SongStore(settings.data_dir)
        self.engine = engine or Engine(settings)
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

    def run(self, name, ctx=None, **params):
        """Blocking call; returns the resulting SongMeta."""
        return self._runner(name, params)(ctx or JobContext())

    def stream(self, name, *, session=None, **params):
        """Yield job events; a Stop request for `session` cancels the running job."""
        run = self._runner(name, params)
        job = self.jobs.start(session) if session else None
        for event in stream(run, job.cancel if job else None, done=job.done if job else None):
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
