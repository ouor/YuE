"""Public API for gradio_client. Every endpoint wraps the same Studio calls the UI uses.

Song endpoints return a song dict: metadata plus `score`, `audio` (server path of
the rendered FLAC), `preview`, `source_audio`, `has_plan` and `lineage`. Use
/song_audio or /export_song to download files.
"""
from __future__ import annotations

import gradio as gr

from . import __version__
from .core import UserError
from .core.messages import user_message
from .core.store import SongNotFound
from .core.workflows import WORKFLOWS
from .i18n import t

GPU = dict(concurrency_id="gpu", concurrency_limit=1)


def register_api(studio):
    """Register endpoints on the current Blocks context."""

    def song(song_id):
        try:
            return studio.song(song_id)
        except SongNotFound:
            raise gr.Error(f"{t('error.song_missing')} (error.song_missing)")

    def run(name, **params):
        try:
            meta = studio.run(name, **params)
        except UserError as exc:
            raise gr.Error(f"{user_message(exc, 'en')} ({exc.key})")
        return studio.song(meta.id)

    @gr.api(api_name="health", queue=False)
    def health() -> dict:
        """Versions, GPU state, and registered workflows."""
        return {"version": __version__, "engine": studio.engine.status(), "workflows": sorted(WORKFLOWS),
                "songs": len(studio.store.list())}

    @gr.api(api_name="style_options", queue=False)
    def style_options() -> dict:
        """Option ids for compose_style (languages, genres, moods, instruments, vocals, presets)."""
        return studio.style_options()

    @gr.api(api_name="compose_style", queue=False)
    def compose_style(language: str = "", genres: list[str] | None = None, moods: list[str] | None = None,
                      instruments: list[str] | None = None, vocal: str = "", bpm: int = 0, extra: str = "",
                      instrumental: bool = False) -> str:
        """Assemble a style prompt from option ids."""
        return studio.compose_style(language=language or None, genres=genres or [], moods=moods or [],
                                    instruments=instruments or [], vocal=vocal or None, bpm=bpm or None,
                                    extra=extra, instrumental=instrumental)

    @gr.api(api_name="create_song", **GPU)
    def create_song(style: str, lyrics: str, title: str = "", mode: str = "full", seed: int = -1,
                    review_first: bool = False) -> dict:
        """Lyrics + style → score → song. mode: full | melody | off. review_first stops after the score."""
        return run("create", style=style, lyrics=lyrics, title=title, mode=mode, seed=seed, review_first=review_first)

    @gr.api(api_name="render_planned", **GPU)
    def render_planned(song_id: str) -> dict:
        """Record a score-only song exactly as planned."""
        return run("render_planned", song_id=song_id)

    @gr.api(api_name="restyle_song", **GPU)
    def restyle_song(source_id: str, style: str, lyrics: str = "", keep_chords: bool = False, seed: int = -1,
                     title: str = "") -> dict:
        """Same melody, new style. Empty lyrics reuse the source's lyrics."""
        return run("restyle", source_id=source_id, style=style, lyrics=lyrics, keep_chords=keep_chords, seed=seed,
                   title=title)

    @gr.api(api_name="check_score", queue=False)
    def check_score(abc: str, source_id: str = "") -> dict:
        """Validate an ABC score; with source_id, also report what changed."""
        return studio.check_score(abc, source_id or None)

    @gr.api(api_name="edit_song", **GPU)
    def edit_song(abc: str, source_id: str = "", style: str = "", lyrics: str = "", seed: int = -1,
                  title: str = "") -> dict:
        """Render an edited score. Empty style/lyrics reuse the source's."""
        return run("edit", abc=abc, source_id=source_id or None, style=style, lyrics=lyrics, seed=seed, title=title)

    @gr.api(api_name="create_instrumental", **GPU)
    def create_instrumental(style: str = "", source_id: str = "", keep_chords: bool = True, plan_mode: str = "full",
                            seed: int = -1, title: str = "") -> dict:
        """Instrumental from a description (YuE2 writes the score) or from a library song's score."""
        return run("instrumental", style=style, source_id=source_id or None, keep_chords=keep_chords,
                   plan_mode=plan_mode, seed=seed, title=title)

    @gr.api(api_name="transcribe_abc", **GPU)
    def transcribe_abc(abc: str, keep_harmony: bool = False, title: str = "") -> dict:
        """Use a native two-voice ABC score as a cover reference."""
        return run("transcribe", abc=abc, keep_harmony=keep_harmony, title=title)

    @gr.api(api_name="create_cover", **GPU)
    def create_cover(source_id: str, style: str, kind: str = "sung", lyrics: str = "",
                     keep_harmony: bool | None = None, seed: int = -1, title: str = "") -> dict:
        """Cover a reference (from /transcribe_reference or /transcribe_abc).

        kind: sung (your lyrics) | original (the reference's transcribed lyrics unless you pass lyrics) | instrumental.
        """
        return run("cover", source_id=source_id, style=style, kind=kind, lyrics=lyrics, keep_harmony=keep_harmony,
                   seed=seed, title=title)

    @gr.api(api_name="transcribe_lyrics", **GPU)
    def transcribe_lyrics(source_id: str, language: str = "auto") -> dict:
        """Transcribe the sung words of an audio reference onto its score lines (Qwen3-ASR); the song's
        "lyrics" field holds the result. language: auto | english | korean | japanese | mandarin | cantonese."""
        return run("transcribe_lyrics", source_id=source_id, language=language)

    @gr.api(api_name="complete_lyrics", concurrency_id="assist", concurrency_limit=4)
    def complete_lyrics(style: str = "", lyrics: str = "", title: str = "", theme: str = "", source_id: str = "",
                        abc: str = "") -> str:
        """Finish lyrics with AI, keeping the lines already written. With source_id or abc, fit that melody."""
        try:
            request = studio.lyrics_request(style=style, lyrics=lyrics, title=title, theme=theme,
                                            melody_abc=abc or None, source_id=source_id or None)
            text = ""
            for text in studio.stream_lyrics(request):
                pass
            return text
        except UserError as exc:
            raise gr.Error(f"{user_message(exc, 'en')} ({exc.key})")

    @gr.api(api_name="list_songs", queue=False)
    def list_songs(operation: str = "", query: str = "") -> list:
        """Library, newest first. operation: create | restyle | edit | instrumental | transcribe | cover."""
        return studio.songs(operation, query)

    @gr.api(api_name="get_song", queue=False)
    def get_song(song_id: str) -> dict:
        return song(song_id)

    @gr.api(api_name="rename_song", queue=False)
    def rename_song(song_id: str, title: str) -> dict:
        try:
            studio.store.rename(song_id, title)
        except SongNotFound:
            raise gr.Error(f"{t('error.song_missing')} (error.song_missing)")
        except ValueError:
            raise gr.Error(f"{t('error.title_required')} (error.title_required)")
        return song(song_id)

    @gr.api(api_name="delete_song", queue=False)
    def delete_song(song_id: str) -> dict:
        """Move a song to the trash folder (recoverable on disk)."""
        try:
            studio.store.delete(song_id)
        except SongNotFound:
            raise gr.Error(f"{t('error.song_missing')} (error.song_missing)")
        return {"deleted": song_id}

    # File transfer needs real components so gradio_client uploads/downloads files.
    with gr.Column(visible=False):
        upload = gr.File(type="filepath")
        start, length = gr.Number(0), gr.Number(60)
        keep_harmony, title = gr.Checkbox(False), gr.Textbox()
        hear_lyrics, lyrics_language = gr.Checkbox(False), gr.Textbox("auto")
        song_id, result, file_out = gr.Textbox(), gr.JSON(), gr.File()
        trigger_transcribe, trigger_audio, trigger_export = gr.Button(), gr.Button(), gr.Button()

    def transcribe_reference(path, start_seconds, length_seconds, keep, name, lyrics, language):
        """Upload a reference recording; returns the transcribed melody score as a song.
        With lyrics=True the sung words are transcribed too (the song's "lyrics" field)."""
        return run("transcribe", audio_path=path, start=start_seconds or 0, length=length_seconds or None,
                   keep_harmony=bool(keep), title=name or "", lyrics=bool(lyrics), language=language or "auto")

    def song_audio(identifier):
        """Download a song's rendered FLAC (or a reference's clip)."""
        data = song(identifier)
        path = data["audio"] or data["source_audio"]
        if not path:
            raise gr.Error(f"{t('error.no_audio')} (error.no_audio)")
        return path

    def export_song(identifier):
        """Download every artifact of a song as a zip."""
        song(identifier)
        return str(studio.store.export_zip(identifier))

    trigger_transcribe.click(transcribe_reference, [upload, start, length, keep_harmony, title, hear_lyrics,
                                                    lyrics_language], result,
                             api_name="transcribe_reference", **GPU)
    trigger_audio.click(song_audio, [song_id], file_out, api_name="song_audio", queue=False)
    trigger_export.click(export_song, [song_id], file_out, api_name="export_song", queue=False)
