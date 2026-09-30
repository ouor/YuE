"""Instrumental music: YuE2 (or a library song) supplies the score, Vocal notes move to Ins."""
from __future__ import annotations

import json

from yue2.protocol import SongRequest

from .. import scores
from ..jobs import UserError
from ..models import Operation, ScoreOrigin
from ..store import SongStore
from .base import Workflow, auto_title, register, resolve_seed

PLANNING_LYRICS = "[Intro]\n\n[Verse]\n\n[Chorus]\n\n[Outro]\n"   # planner-only section tags, never sung


def instrumental_request(song_id, style, abc, seed):
    """Final request: converted score, section tags only, instrumental style."""
    return SongRequest(style=scores.instrumental_style(style), lyrics=scores.lyric_template(abc),
                       cot=scores.mode_for(abc), seed=seed, abc=abc, id=song_id)


def convert(store, meta, score, keep_chords, ctx):
    ctx.stage("convert", song_id=meta.id)
    try:
        abc, transfer = scores.to_instrumental(score, keep_chords=keep_chords)
    except ValueError as exc:
        raise UserError("error.convert_failed", detail=str(exc)) from exc
    store.write_text(meta.id, SongStore.CONVERSION, json.dumps(transfer, indent=2, ensure_ascii=False))
    store.update(meta.id, extra={**meta.extra, "transfer": {k: v for k, v in transfer.items() if k != "affected_ins_notes"}})
    return abc


@register
class Instrumental(Workflow):
    name = "instrumental"

    def validate(self, style="", source_id=None, keep_chords=True, plan_mode="full", seed=None, title=""):
        if source_id:
            self.source(source_id)
        elif not (style or "").strip():
            raise UserError("error.style_required")
        if plan_mode not in ("full", "melody"):
            raise UserError("error.bad_mode")
        return dict(style=(style or "").strip(), source_id=source_id or None, keep_chords=bool(keep_chords),
                    plan_mode=plan_mode, seed=resolve_seed(seed), title=(title or "").strip())

    def run(self, ctx, style, source_id, keep_chords, plan_mode, seed, title):
        parent = self.store.get(source_id) if source_id else None
        style = style or (parent.style if parent else "")
        meta = self.store.create(
            Operation.INSTRUMENTAL, title or (self.derived_title(parent, "instrumental", ctx.lang) if parent else auto_title("", style, ctx.lang)),
            parent_id=source_id, style=scores.instrumental_style(style), mode=plan_mode, seed=seed,
            score_origin=ScoreOrigin.CONVERTED.value, extra={"keep_chords": keep_chords})
        ctx.emit("song", song_id=meta.id)
        with self.guard(meta):
            if parent:
                score = self.store.read_score(source_id)
            else:
                score = self._plan_score(meta, style, plan_mode, seed, ctx)
            abc = convert(self.store, self.store.get(meta.id), score, keep_chords, ctx)
            request = instrumental_request(meta.id, style, abc, seed)
            self.store.update(meta.id, lyrics=request.lyrics, mode=request.cot)
            plan = self.plan_into(meta, request, ctx)
            return self.render_into(meta, plan, ctx)

    def _plan_score(self, meta, style, plan_mode, seed, ctx):
        """Let YuE2 compose the score; keep its untouched plan under planning/."""
        ctx.stage("plan", song_id=meta.id)
        request = SongRequest(style=scores.instrumental_style(style), lyrics=PLANNING_LYRICS, cot=plan_mode,
                              seed=seed, id=meta.id)
        plan = self.engine.plan(request, ctx)
        ctx.check()
        plan.save(self.store.path(meta.id) / "planning")
        if plan.truncated or not plan.abc:
            raise UserError("error.plan_truncated")
        return plan.abc
