"""Render a user-edited score as a new version of a song."""
from __future__ import annotations

from yue2.protocol import SongRequest

from .. import scores
from ..jobs import UserError
from ..models import Operation, ScoreOrigin
from .base import Workflow, auto_title, register, require, resolve_seed


@register
class EditScore(Workflow):
    name = "edit"

    def validate(self, abc, source_id=None, style=None, lyrics=None, seed=None, title=""):
        parent = self.source(source_id) if source_id else None
        abc = require(abc, "error.score_required")
        abc = abc if abc.endswith("\n") else abc + "\n"
        info = scores.inspect(abc)
        if not info["ok"]:
            raise UserError("error.score_invalid", detail=info["error"])
        style = style if style and style.strip() else (parent.style if parent else "")
        lyrics = lyrics if lyrics is not None and lyrics.strip() else (parent.lyrics if parent else "")
        return dict(abc=abc, source_id=source_id, style=require(style, "error.style_required"), lyrics=lyrics or "",
                    seed=resolve_seed(seed), title=(title or "").strip())

    def run(self, ctx, abc, source_id, style, lyrics, seed, title):
        parent = self.store.get(source_id) if source_id else None
        changes = scores.compare(self.store.read_score(source_id), abc) if parent else None
        mode = scores.mode_for(abc)
        meta = self.store.create(
            Operation.EDIT, title or (self.derived_title(parent, "edited", ctx.lang) if parent else auto_title(lyrics, style, ctx.lang)),
            parent_id=source_id, style=style, lyrics=lyrics, mode=mode, seed=seed,
            score_origin=ScoreOrigin.USER.value, extra={"changes": changes})
        ctx.emit("song", song_id=meta.id)
        request = SongRequest(style=style, lyrics=lyrics, cot=mode, seed=seed, abc=abc, id=meta.id)
        with self.guard(meta):
            plan = self.plan_into(meta, request, ctx)
            return self.render_into(meta, plan, ctx)
