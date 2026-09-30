"""Cover: 1) extract a melody score (and the sung words) from a reference, 2) re-imagine it with new
lyrics, its original lyrics, or as an instrumental."""
from __future__ import annotations

import gradio as gr

from ...core import scores, styles
from ...core.assist import has_words
from ...i18n import lang_of, t
from ..components.lyrics_assist import LyricsAssist
from ..components.result_panel import RENDER_STEPS, ResultPanel, original_update
from ..components.song_picker import SongPicker
from ..components.style_builder import StyleBuilder
from ..context import GPU
from .base import Tab

REFERENCE = {"audio": "audio", "abc": "abc"}
KINDS = {"original": "original", "sung": "sung", "instrumental": "instrumental"}
LYRICS_LANGUAGES = {"auto": "auto", **{key: key for key in styles.LANGUAGES}}
STYLE_LANGUAGE = {"English": "english", "Korean": "korean", "Japanese": "japanese", "Chinese": "mandarin",
                  "Cantonese": "cantonese"}        # Qwen3-ASR name → style builder language
TRANSCRIBE_STEPS = [("clip", "step.clip"), ("transcribe", "step.transcribe")]
LYRICS_STEPS = [("lyrics", "step.lyrics")]
INSTRUMENTAL_STEPS = [("convert", "step.convert"), ("compose", "step.compose"), ("render", "step.render")]


def is_reference(meta):
    return meta.operation == "transcribe" and meta.status == "complete"


class CoverTab(Tab):
    id = "cover"
    label = "tab.cover"

    def build(self):
        T, ctx = self.ctx.T, self.ctx
        gr.Markdown(T("cover.intro"), elem_classes="tab-intro")
        with gr.Row(equal_height=False):
            with gr.Column(scale=5):
                gr.Markdown(T("cover.step1"), elem_classes="step-title")
                self.reference = ctx.choices(gr.Radio(list(REFERENCE), value="audio", label=T("cover.reference")),
                                             REFERENCE, "cover.reference")
                with gr.Group() as self.audio_group:
                    self.upload = gr.Audio(sources=["upload"], type="filepath", label=T("cover.upload"))
                    with gr.Row():
                        self.start = gr.Number(0, minimum=0, label=T("cover.start"), info=T("cover.start_info"))
                        self.length = gr.Number(60, minimum=5, maximum=240, label=T("cover.length"),
                                                info=T("cover.length_info"))
                    with gr.Row(visible=self.hearing):
                        self.hear_lyrics = gr.Checkbox(self.hearing, label=T("cover.hear_lyrics"),
                                                       info=T("cover.hear_lyrics_info"), scale=3)
                        self.lyrics_language = ctx.choices(
                            gr.Dropdown(list(LYRICS_LANGUAGES), value="auto", label=T("cover.lyrics_language"),
                                        scale=2, min_width=120), LYRICS_LANGUAGES, "language")
                with gr.Group(visible=False) as self.abc_group:
                    self.abc_file = gr.File(file_types=[".abc", ".txt"], type="filepath", label=T("cover.abc_file"))
                    self.abc = gr.Code(value="", language=None, interactive=True, lines=10, label=T("cover.abc"),
                                        wrap_lines=True)
                self.keep_harmony = gr.Checkbox(False, label=T("cover.keep_harmony"), info=T("cover.keep_harmony_info"))
                self.ref_title = gr.Textbox(label=T("field.title"), placeholder=T("cover.title_placeholder"))
                with gr.Row():
                    self.transcribe = gr.Button(T("cover.transcribe"), variant="primary", scale=3)
                    self.stop1 = gr.Button(T("action.stop"), variant="stop", scale=1)

                gr.Markdown(T("cover.step2"), elem_classes="step-title")
                self.picker = SongPicker(ctx, "cover.source", accept=is_reference)
                kinds = KINDS if self.hearing else {k: v for k, v in KINDS.items() if k != "original"}
                self.kind = ctx.choices(gr.Radio(list(kinds), value="original" if self.hearing else "sung",
                                                 label=T("cover.kind")), kinds, "cover.kind")
                self.lyrics = gr.Textbox(label=T("field.lyrics"), info=T("cover.lyrics_info"), lines=8, max_lines=24)
                self.hear = gr.Button(T("cover.hear"), variant="secondary", size="sm", visible=self.hearing)
                self.style = StyleBuilder(ctx, presets=styles.PRESET_GROUPS["cover"], keep_language=True)
                self.assist = LyricsAssist(ctx, self.lyrics, self.style.prompt, melody=self.picker.dropdown,
                                           melody_is_song=True)
                with gr.Accordion(T("field.advanced"), open=False):
                    self.title = gr.Textbox(label=T("field.title"), placeholder=T("field.title_auto"))
                    self.seed = gr.Number(-1, precision=0, label=T("field.seed"), info=T("field.seed_info"))
                with gr.Row():
                    self.run_button = gr.Button(T("cover.run"), variant="primary", size="lg", scale=3)
                    self.stop2 = gr.Button(T("action.stop"), variant="stop", size="lg", scale=1)
                gr.Markdown(T("cover.rights"), elem_classes="fine-print")
            with gr.Column(scale=6):
                self.panel = ResultPanel(ctx, self.id, compare=True, actions=("editor", "restyle"))
        self.open_outputs = [self.picker.dropdown]

    def open(self, song_id, lang):
        return [self.picker.update(song_id, lang)]

    @property
    def hearing(self):
        return self.studio.engine.lyrics_available

    def reference_meta(self, song_id):
        store = self.studio.store
        return store.get(song_id) if song_id and store.exists(song_id) else None

    def lyrics_view(self, song_id, kind, current, lang, reset):
        """The lyrics box for a cover kind: the recognized words, or section tags to write under.

        Typed lyrics survive a switch to "new lyrics"; picking another reference (`reset`) starts over.
        """
        meta = self.reference_meta(song_id)
        try:
            template = scores.lyric_template(self.studio.store.read_score(song_id) or "") if meta else ""
        except ValueError:
            template = ""
        original = meta.lyrics if meta and has_words(meta.lyrics) else ""
        if kind == "instrumental":
            return gr.update(visible=False)
        if kind == "original":
            key = "cover.lyrics_info_original" if original else "cover.lyrics_info_missing"
            return gr.update(visible=True, value=original or template, info=t(key, lang))
        keep = not reset and has_words(current) and current != original
        return gr.update(visible=True, value=current if keep else template, info=t("cover.lyrics_info", lang))

    def voice_fields(self, song_id, kind):
        """Sung covers default to the words' language; an instrumental has no language or voice."""
        if kind == "instrumental":
            return gr.update(visible=False, value=None), gr.update(visible=False, value=None)
        meta = self.reference_meta(song_id)
        heard = STYLE_LANGUAGE.get(meta.extra.get("lyrics_language")) if meta and kind == "original" else None
        return gr.update(visible=True, value=heard or "english"), gr.update(visible=True, value="female")

    def load_reference(self, song_id, kind, request: gr.Request):
        lyrics = self.lyrics_view(song_id, kind, "", lang_of(request), reset=True)
        language, _ = self.voice_fields(song_id, kind)
        return lyrics, original_update(self.audio_of(song_id) if self.reference_meta(song_id) else None), language

    def wire(self):
        panel, private = self.panel, dict(queue=False, api_visibility="private")
        self.reference.change(lambda r: (gr.update(visible=r == "audio"), gr.update(visible=r == "abc")),
                              [self.reference], [self.audio_group, self.abc_group], **private)
        self.abc_file.upload(lambda path: open(path, encoding="utf-8").read() if path else "", [self.abc_file],
                             [self.abc], **private)
        self.picker.dropdown.change(self.load_reference, [self.picker.dropdown, self.kind],
                                    [self.lyrics, panel.original, self.style.language], **private).then(
            self.style.compose, self.style.fields, self.style.prompt, **private)

        def kind_changed(song_id, kind, current, request: gr.Request):
            lyrics = self.lyrics_view(song_id, kind, current, lang_of(request), reset=False)
            return (lyrics, gr.update(visible=kind == "original" and self.hearing),
                    *self.voice_fields(song_id, kind))

        self.kind.change(kind_changed, [self.picker.dropdown, self.kind, self.lyrics],
                         [self.lyrics, self.hear, self.style.language, self.style.vocal], **private).then(
            self.style.compose, self.style.fields, self.style.prompt, **private)

        def transcribe(reference, upload, start, length, abc, keep_harmony, title, hear, language,
                       request: gr.Request):
            hear = bool(hear) and reference == "audio" and self.hearing
            params = dict(audio_path=upload if reference == "audio" else None,
                          abc=abc if reference == "abc" else None,
                          start=start, length=length, keep_harmony=keep_harmony, title=title,
                          lyrics=hear, language=language)
            steps = (TRANSCRIBE_STEPS + (LYRICS_STEPS if hear else [])) if reference == "audio" else []
            picker = self.picker

            def select_new(meta, lang):
                return {picker.dropdown: picker.update(meta.id, lang)}

            yield from panel.run("transcribe", params, request, steps=steps, on_done=select_new)

        transcribe_outputs = panel.outputs + [self.picker.dropdown]
        transcribe_event = self.transcribe.click(
            transcribe, [self.reference, self.upload, self.start, self.length, self.abc, self.keep_harmony,
                         self.ref_title, self.hear_lyrics, self.lyrics_language], transcribe_outputs,
            api_visibility="private", **GPU)
        self.stop_button(self.stop1, panel, transcribe_event)

        def hear(source_id, language, kind, request: gr.Request):
            def fill(meta, lang):
                return {self.lyrics: self.lyrics_view(meta.id, kind, "", lang, reset=True)}

            yield from panel.run("transcribe_lyrics", dict(source_id=source_id, language=language), request,
                                 steps=LYRICS_STEPS, original=self.audio_of(source_id) if source_id else None,
                                 on_done=fill)

        hear_event = self.hear.click(hear, [self.picker.dropdown, self.lyrics_language, self.kind],
                                     panel.outputs + [self.lyrics], api_visibility="private", **GPU)

        def cover(source_id, kind, lyrics, style, keep_harmony, seed, title, request: gr.Request):
            params = dict(source_id=source_id, style=style, kind=kind, lyrics=lyrics, keep_harmony=keep_harmony,
                          seed=seed, title=title)
            yield from panel.run("cover", params, request,
                                 steps=INSTRUMENTAL_STEPS if kind == "instrumental" else RENDER_STEPS,
                                 original=self.audio_of(source_id))

        run_event = self.run_button.click(
            cover, [self.picker.dropdown, self.kind, self.lyrics, self.style.prompt, self.keep_harmony, self.seed,
                    self.title], panel.outputs, api_visibility="private", **GPU)
        self.stop_button(self.stop2, panel, run_event, hear_event)
        self.assist.wire()
        panel.follow(self.transcribe, self.run_button, self.hear)
        panel.wire()
        self.on_select(self.tab)
