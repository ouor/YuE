"""Cover: 1) extract a melody score from a reference, 2) re-imagine it as a sung or instrumental cover."""
from __future__ import annotations

import gradio as gr

from ...core import scores, styles
from ..components.result_panel import RENDER_STEPS, ResultPanel, original_update
from ..components.song_picker import SongPicker
from ..components.style_builder import StyleBuilder
from ..context import GPU
from .base import Tab

REFERENCE = {"audio": "audio", "abc": "abc"}
KINDS = {"sung": "sung", "instrumental": "instrumental"}
TRANSCRIBE_STEPS = [("clip", "step.clip"), ("transcribe", "step.transcribe")]
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
                self.kind = ctx.choices(gr.Radio(list(KINDS), value="sung", label=T("cover.kind")), KINDS, "cover.kind")
                self.lyrics = gr.Textbox(label=T("field.lyrics"), info=T("cover.lyrics_info"), lines=8, max_lines=24)
                self.style = StyleBuilder(ctx, presets=["piano_pop", "cafe_jazz", "rock_anthem", "lofi_study"],
                                          value=styles.PRESETS["piano_pop"], keep_language=True)
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

    def load_reference(self, song_id):
        """Prefill lyrics with the reference's section tags so users write words per section."""
        store = self.studio.store
        if not song_id or not store.exists(song_id):
            return "", original_update(None)
        score = store.read_score(song_id) or ""
        try:
            template = scores.lyric_template(score)
        except ValueError:
            template = ""
        return template, original_update(self.audio_of(song_id))

    def wire(self):
        panel, private = self.panel, dict(queue=False, api_visibility="private")
        self.reference.change(lambda r: (gr.update(visible=r == "audio"), gr.update(visible=r == "abc")),
                              [self.reference], [self.audio_group, self.abc_group], **private)
        self.abc_file.upload(lambda path: open(path, encoding="utf-8").read() if path else "", [self.abc_file],
                             [self.abc], **private)
        self.picker.dropdown.change(self.load_reference, [self.picker.dropdown], [self.lyrics, panel.original], **private)
        self.kind.change(lambda k: gr.update(visible=k == "sung"), [self.kind], [self.lyrics], **private)
        # An instrumental cover has no sung language or voice; clear them so the prompt stays consistent.
        def voice_fields(kind):
            sung = kind == "sung"
            return (gr.update(visible=sung, value="english" if sung else None),
                    gr.update(visible=sung, value="female" if sung else None))

        self.kind.change(voice_fields, [self.kind], [self.style.language, self.style.vocal], **private).then(
            self.style.compose, self.style.fields, self.style.prompt, **private)

        def transcribe(reference, upload, start, length, abc, keep_harmony, title, request: gr.Request):
            params = dict(audio_path=upload if reference == "audio" else None,
                          abc=abc if reference == "abc" else None,
                          start=start, length=length, keep_harmony=keep_harmony, title=title)
            steps = TRANSCRIBE_STEPS if reference == "audio" else []
            picker = self.picker

            def select_new(meta, lang):
                return {picker.dropdown: picker.update(meta.id, lang)}

            yield from panel.run("transcribe", params, request, steps=steps, on_done=select_new)

        transcribe_outputs = panel.outputs + [self.picker.dropdown]
        transcribe_event = self.transcribe.click(
            transcribe, [self.reference, self.upload, self.start, self.length, self.abc, self.keep_harmony,
                         self.ref_title], transcribe_outputs, api_visibility="private", **GPU)
        self.stop_button(self.stop1, panel, transcribe_event)

        def cover(source_id, kind, lyrics, style, keep_harmony, seed, title, request: gr.Request):
            params = dict(source_id=source_id, style=style, kind=kind, lyrics=lyrics, keep_harmony=keep_harmony,
                          seed=seed, title=title)
            yield from panel.run("cover", params, request,
                                 steps=INSTRUMENTAL_STEPS if kind == "instrumental" else RENDER_STEPS,
                                 original=self.audio_of(source_id))

        run_event = self.run_button.click(
            cover, [self.picker.dropdown, self.kind, self.lyrics, self.style.prompt, self.keep_harmony, self.seed,
                    self.title], panel.outputs, api_visibility="private", **GPU)
        self.stop_button(self.stop2, panel, run_event)
        panel.follow(self.transcribe, self.run_button)
        panel.wire()
        self.on_select(self.tab)
