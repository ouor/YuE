"""Covers: transcribe a reference (audio or ABC) into a melody score, then re-imagine it."""
from __future__ import annotations

from pathlib import Path

from yue2.protocol import SongRequest

from .. import audio, scores
from ..jobs import UserError
from ..models import Operation, ScoreOrigin, Status
from ..store import SongStore
from .base import Workflow, derived_title, register, require, resolve_seed
from .instrumental import convert, instrumental_request

KINDS = ("sung", "instrumental")


@register
class Transcribe(Workflow):
    name = "transcribe"

    def validate(self, audio_path=None, abc=None, start=0.0, length=None, keep_harmony=False, title=""):
        has_audio, has_abc = bool(audio_path), bool(abc and abc.strip())
        if has_audio == has_abc:
            raise UserError("error.reference_required")
        if has_abc:
            info = scores.inspect(abc)
            if not info["ok"]:
                raise UserError("error.score_invalid", detail=info["error"])
            return dict(audio_path=None, abc=abc if abc.endswith("\n") else abc + "\n", start=0.0, length=None,
                        keep_harmony=bool(keep_harmony), title=(title or "").strip() or "ABC reference")
        path = Path(audio_path)
        if not path.is_file():
            raise UserError("error.reference_required")
        total = audio.duration(path)
        start = max(float(start or 0), 0.0)
        if total is not None and start >= total:
            raise UserError("error.clip_out_of_range")
        limit = self.studio.settings.max_reference_seconds
        available = (total - start) if total is not None else limit
        length = min(float(length), available) if length else available
        length = min(length, limit)
        if length < 5:
            raise UserError("error.clip_too_short")
        return dict(audio_path=str(path), abc=None, start=start, length=round(length, 2),
                    keep_harmony=bool(keep_harmony), title=(title or "").strip() or path.stem[:40])

    def run(self, ctx, audio_path, abc, start, length, keep_harmony, title):
        origin = ScoreOrigin.TRANSCRIBED if audio_path else ScoreOrigin.USER
        meta = self.store.create(Operation.TRANSCRIBE, title, score_origin=origin.value, mode=scores.mode_for(abc) if abc else
                                 ("full" if keep_harmony else "melody"),
                                 extra={"source_name": Path(audio_path).name if audio_path else None,
                                        "start": start, "length": length, "keep_harmony": keep_harmony})
        ctx.emit("song", song_id=meta.id)
        with self.guard(meta):
            if audio_path:
                ctx.stage("clip", song_id=meta.id)
                clip = audio.clip(audio_path, self.store.path(meta.id) / f"{SongStore.SOURCE}.wav", start, length)
                ctx.stage("transcribe", song_id=meta.id)
                try:
                    result = self.engine.transcribe(clip, self.store.path(meta.id) / SongStore.TRANSCRIPTION,
                                                    melody_only=not keep_harmony, ctx=ctx)
                except RuntimeError as exc:
                    raise UserError("error.transcription_failed", detail=str(exc)) from exc
                abc = result.get("abc")
                if result.get("abc_error") or not abc:
                    raise UserError("error.transcription_failed", detail=result.get("abc_error") or "empty score")
            self.store.write_text(meta.id, SongStore.SCORE, abc)
            info = scores.inspect(abc)
            ctx.emit("score", song_id=meta.id, abc=abc)
            return self.store.update(meta.id, status=Status.COMPLETE, duration=length or info["seconds"],
                                     mode=scores.mode_for(abc), extra={**meta.extra, "score": info})


@register
class Cover(Workflow):
    name = "cover"

    def validate(self, source_id, style, kind="sung", lyrics="", keep_harmony=None, seed=None, title=""):
        parent = self.source(source_id)
        if kind not in KINDS:
            raise UserError("error.bad_kind")
        if kind == "sung":
            words = [line for line in (lyrics or "").splitlines() if line.strip() and not line.strip().startswith("[")]
            if not words:
                raise UserError("error.cover_lyrics_required")
        if keep_harmony is None:
            keep_harmony = bool(parent.extra.get("keep_harmony"))
        return dict(source_id=source_id, style=require(style, "error.style_required"), kind=kind,
                    lyrics=lyrics or "", keep_harmony=bool(keep_harmony), seed=resolve_seed(seed),
                    title=(title or "").strip())

    def run(self, ctx, source_id, style, kind, lyrics, keep_harmony, seed, title):
        parent = self.store.get(source_id)
        score = self.store.read_score(source_id)
        meta = self.store.create(
            Operation.COVER, title or derived_title(parent, "cover"), parent_id=source_id, style=style, lyrics=lyrics,
            seed=seed, score_origin=ScoreOrigin.CONVERTED.value if kind == "instrumental" else parent.score_origin,
            extra={"kind": kind, "keep_harmony": keep_harmony})
        ctx.emit("song", song_id=meta.id)
        with self.guard(meta):
            if kind == "instrumental":
                abc = convert(self.store, meta, score, keep_harmony, ctx)
                request = instrumental_request(meta.id, style, abc, seed)
            else:
                abc = score if keep_harmony else scores.melody_only(score)
                request = SongRequest(style=style, lyrics=lyrics, cot=scores.mode_for(abc), seed=seed, abc=abc,
                                      id=meta.id)
            self.store.update(meta.id, style=request.style, lyrics=request.lyrics, mode=request.cot)
            plan = self.plan_into(meta, request, ctx)
            return self.render_into(meta, plan, ctx)
