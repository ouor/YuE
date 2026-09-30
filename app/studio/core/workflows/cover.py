"""Covers: transcribe a reference (audio or ABC) into a melody score and, optionally, its sung
words; then re-imagine it with new lyrics, its original lyrics, or as an instrumental."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re

from yue2.protocol import SongRequest

from .. import audio, lyric_sync, scores
from ..jobs import Cancelled, UserError
from ..models import Operation, ScoreOrigin, Status
from ..store import SongStore
from ...i18n import t
from .base import Workflow, register, require, resolve_seed
from .instrumental import convert, instrumental_request

KINDS = ("sung", "original", "instrumental")
LYRICS_FILE = f"{SongStore.TRANSCRIPTION}/lyrics.json"
log = logging.getLogger("studio")


def hear_lyrics(workflow, ctx, song_id, abc, language):
    """Recognize a reference's sung words onto its score lines; saves and returns the result."""
    store = workflow.store
    beats = store.path(song_id) / SongStore.TRANSCRIPTION / lyric_sync.BEATS
    source = store.source_audio(song_id)
    if not beats.is_file() or source is None:
        raise UserError("error.lyrics_need_audio")
    ctx.stage("lyrics", song_id=song_id)
    wave = audio.load_mono(source)
    with workflow.engine.listener() as recognize:
        def listen(clips, lang, timestamps):
            results = []
            for clip in clips:
                ctx.check()
                results += recognize([clip], lang, timestamps)
            return results

        result = lyric_sync.extract(listen, wave, abc, lyric_sync.read_beats(beats), language=language,
                                    check=ctx.check)
    store.write_text(song_id, LYRICS_FILE, json.dumps(result, ensure_ascii=False, indent=2))
    return result


@register
class Transcribe(Workflow):
    name = "transcribe"

    def validate(self, audio_path=None, abc=None, start=0.0, length=None, keep_harmony=False, title="",
                 lyrics=False, language="auto"):
        has_audio, has_abc = bool(audio_path), bool(abc and abc.strip())
        if has_audio == has_abc:
            raise UserError("error.reference_required")
        if has_abc:
            info = scores.inspect(abc)
            if not info["ok"]:
                raise UserError("error.score_invalid", detail=info["error"])
            return dict(audio_path=None, abc=abc if abc.endswith("\n") else abc + "\n", start=0.0, length=None,
                        keep_harmony=bool(keep_harmony), title=(title or "").strip(), lyrics=False, language=None)
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
        lyrics = bool(lyrics) and self.engine.lyrics_available
        return dict(audio_path=str(path), abc=None, start=start, length=round(length, 2),
                    keep_harmony=bool(keep_harmony), title=(title or "").strip() or path.stem[:40],
                    lyrics=lyrics, language=lyric_sync.asr_language(language) if lyrics else None)

    def run(self, ctx, audio_path, abc, start, length, keep_harmony, title, lyrics, language):
        if not title:
            # A pasted score: use its T: line when it has one.
            named = re.search(r"^T:(.+)$", abc or "", re.M)
            title = named.group(1).strip()[:40] if named and named.group(1).strip() else t("title.pasted_score", ctx.lang)
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
            words, extra = "", {**meta.extra, "score": info}
            if lyrics:
                # The score is the main result; a failed lyric pass leaves the reference usable.
                try:
                    heard = hear_lyrics(self, ctx, meta.id, abc, language)
                    words, extra["lyrics_language"] = heard["lyrics"], heard["language"]
                except (Cancelled, UserError):
                    raise
                except Exception as exc:
                    log.warning("Lyric recognition failed for %s: %s", meta.id, exc)
                    extra["lyrics_error"] = str(exc)
            return self.store.update(meta.id, status=Status.COMPLETE, duration=length or info["seconds"],
                                     mode=scores.mode_for(abc), lyrics=words, extra=extra)


@register
class TranscribeLyrics(Workflow):
    """Recognize the original lyrics of an existing audio reference."""
    name = "transcribe_lyrics"

    def validate(self, source_id, language="auto"):
        parent = self.source(source_id)
        if parent.operation != Operation.TRANSCRIBE or self.store.source_audio(source_id) is None:
            raise UserError("error.lyrics_need_audio")
        if not self.engine.lyrics_available:
            raise UserError("error.lyrics_unavailable")
        return dict(source_id=source_id, language=lyric_sync.asr_language(language))

    def run(self, ctx, source_id, language):
        meta = self.store.get(source_id)
        ctx.emit("song", song_id=source_id)
        try:
            heard = hear_lyrics(self, ctx, source_id, self.store.read_score(source_id), language)
        except (Cancelled, UserError):
            raise
        except Exception as exc:
            raise UserError("error.lyrics_failed", detail=str(exc)) from exc
        extra = {k: v for k, v in meta.extra.items() if k != "lyrics_error"}
        return self.store.update(source_id, lyrics=heard["lyrics"], extra={**extra, "lyrics_language": heard["language"]})


@register
class Cover(Workflow):
    name = "cover"

    def validate(self, source_id, style, kind="sung", lyrics="", keep_harmony=None, seed=None, title=""):
        parent = self.source(source_id, render=True)
        if kind not in KINDS:
            raise UserError("error.bad_kind")
        if kind == "original" and not lyric_sync.has_words(lyrics):
            lyrics = parent.lyrics                   # the words recognized from the reference
            if not lyric_sync.has_words(lyrics):
                raise UserError("error.cover_no_original_lyrics")
        if kind == "sung" and not lyric_sync.has_words(lyrics):
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
            Operation.COVER, title or self.derived_title(parent, "cover", ctx.lang), parent_id=source_id, style=style, lyrics=lyrics,
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
