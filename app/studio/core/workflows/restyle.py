"""Same melody, new genre: re-render a song's score with a different style."""
from __future__ import annotations

from yue2.protocol import SongRequest

from .. import scores, styles
from ..models import Operation, ScoreOrigin
from ..store import SongStore
from .base import Workflow, derived_title, register, require, resolve_seed


def style_label(style):
    """Short name for a version: the first style phrase that is not a language."""
    languages = {phrase.lower() for phrase in styles.LANGUAGES.values()}
    parts = [p.strip() for p in style.split(",") if p.strip()]
    return next((p for p in parts if p.lower() not in languages), parts[0] if parts else "")[:24]


@register
class Restyle(Workflow):
    name = "restyle"

    def validate(self, source_id, style, lyrics=None, keep_chords=False, seed=None, title=""):
        parent = self.source(source_id)
        lyrics = parent.lyrics if lyrics is None or not str(lyrics).strip() else lyrics
        return dict(source_id=source_id, style=require(style, "error.style_required"), lyrics=lyrics or "",
                    keep_chords=bool(keep_chords), seed=resolve_seed(seed), title=(title or "").strip())

    def run(self, ctx, source_id, style, lyrics, keep_chords, seed, title):
        parent = self.store.get(source_id)
        score = self.store.read_score(source_id)
        if keep_chords:
            abc = score
        else:
            # Without chord symbols the accompaniment is free to follow the new style.
            abc = self.store.read_score_variant(source_id, SongStore.MELODY_SCORE, scores.melody_only)
        mode = scores.mode_for(abc)
        meta = self.store.create(
            Operation.RESTYLE, title or derived_title(parent, style_label(style)), parent_id=source_id,
            style=style, lyrics=lyrics, mode=mode, seed=seed,
            score_origin=parent.score_origin if keep_chords else ScoreOrigin.CONVERTED.value,
            extra={"keep_chords": keep_chords})
        ctx.emit("song", song_id=meta.id)
        request = SongRequest(style=style, lyrics=lyrics, cot=mode, seed=seed, abc=abc, id=meta.id)
        with self.guard(meta):
            plan = self.plan_into(meta, request, ctx)
            return self.render_into(meta, plan, ctx)
