"""Create a song from lyrics and style; optionally stop after the score for review."""
from __future__ import annotations

from yue2 import SymbolicPlan
from yue2.protocol import SongRequest

from ..jobs import UserError
from ..models import Operation, ScoreOrigin, Status
from ..store import SongStore
from .base import Workflow, auto_title, register, require, resolve_seed

MODES = ("full", "melody", "off")


@register
class CreateSong(Workflow):
    name = "create"

    def validate(self, style, lyrics, title="", mode="full", seed=None, review_first=False):
        if mode not in MODES:
            raise UserError("error.bad_mode")
        if review_first and mode == "off":
            raise UserError("error.review_needs_score")
        return dict(style=require(style, "error.style_required"), lyrics=require(lyrics, "error.lyrics_required"),
                    title=(title or "").strip(), mode=mode, seed=resolve_seed(seed), review_first=bool(review_first))

    def run(self, ctx, style, lyrics, title, mode, seed, review_first):
        meta = self.store.create(Operation.CREATE, title or auto_title(lyrics, style), style=style, lyrics=lyrics,
                                 mode=mode, seed=seed,
                                 score_origin=(ScoreOrigin.NONE if mode == "off" else ScoreOrigin.YUE2).value)
        ctx.emit("song", song_id=meta.id)
        request = SongRequest(style=style, lyrics=lyrics, cot=mode, seed=seed, id=meta.id)
        with self.guard(meta):
            plan = self.plan_into(meta, request, ctx)
            if review_first:
                return self.store.update(meta.id, status=Status.PLANNED)
            return self.render_into(meta, plan, ctx)


@register
class RenderPlanned(Workflow):
    """Render a saved plan exactly (no re-planning) — used after reviewing a score."""

    name = "render_planned"

    def validate(self, song_id):
        meta = self.source(song_id, need_score=False)
        if self.store.file(song_id, SongStore.PLAN) is None:
            raise UserError("error.no_plan")
        if meta.status == Status.COMPLETE.value:
            raise UserError("error.already_rendered")
        return dict(song_id=song_id)

    def run(self, ctx, song_id):
        meta = self.store.get(song_id)
        plan = SymbolicPlan.load(self.store.path(song_id) / SongStore.PLAN)
        ctx.emit("song", song_id=song_id)
        ctx.emit("score", song_id=song_id, abc=plan.abc or "")
        with self.guard(meta):
            return self.render_into(meta, plan, ctx)
