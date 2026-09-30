"""Instrumental: background music from a description, or a library song without vocals."""
from __future__ import annotations

import gradio as gr

from ...core import styles
from ..components.result_panel import ResultPanel, original_update
from ..components.song_picker import SongPicker, has_score
from ..components.style_builder import StyleBuilder
from ..context import GPU
from .base import Tab

SOURCES = {"text": "text", "song": "song"}
PLAN_MODES = {"full": "full", "melody": "melody"}
TEXT_STEPS = [("plan", "step.plan"), ("convert", "step.convert"), ("compose", "step.compose"), ("render", "step.render")]
SONG_STEPS = TEXT_STEPS[1:]


class InstrumentalTab(Tab):
    id = "instrumental"
    label = "tab.instrumental"

    def build(self):
        T, ctx = self.ctx.T, self.ctx
        gr.Markdown(T("instrumental.intro"), elem_classes="tab-intro")
        with gr.Row(equal_height=False):
            with gr.Column(scale=5):
                self.source = ctx.choices(gr.Radio(list(SOURCES), value="text", label=T("instrumental.source")),
                                          SOURCES, "instrumental.source")
                with gr.Group(visible=False) as self.song_group:
                    self.picker = SongPicker(ctx, "instrumental.song", accept=has_score)
                    self.keep_chords = gr.Checkbox(True, label=T("instrumental.keep_chords"),
                                                   info=T("instrumental.keep_chords_info"))
                gr.Markdown(T("instrumental.sound"), elem_classes="step-title")
                self.style = StyleBuilder(ctx, instrumental=True, value=styles.PRESETS["lofi_study"],
                                          presets=["lofi_study", "cafe_jazz", "cinematic", "reading_piano"])
                with gr.Accordion(T("field.advanced"), open=False):
                    self.plan_mode = ctx.choices(gr.Radio(list(PLAN_MODES), value="full", label=T("field.mode"),
                                                          info=T("instrumental.plan_mode_info")), PLAN_MODES, "mode")
                    self.title = gr.Textbox(label=T("field.title"), placeholder=T("field.title_auto"))
                    self.seed = gr.Number(-1, precision=0, label=T("field.seed"), info=T("field.seed_info"))
                with gr.Row():
                    self.run_button = gr.Button(T("instrumental.run"), variant="primary", size="lg", scale=3)
                    self.stop = gr.Button(T("action.stop"), variant="stop", size="lg", scale=1)
            with gr.Column(scale=6):
                self.panel = ResultPanel(ctx, self.id, compare=True, actions=("editor", "restyle"))
        self.open_outputs = [self.source, self.song_group, self.picker.dropdown]

    def open(self, song_id, lang):
        # Arriving with a song (e.g. "Make instrumental") selects the song source.
        if song_id and self.studio.store.exists(song_id):
            return ["song", gr.update(visible=True), self.picker.update(song_id, lang)]
        return [gr.skip(), gr.skip(), self.picker.update(None, lang)]

    def refresh(self, song_id, lang):
        return [gr.skip(), gr.skip(), self.picker.update(song_id, lang)]

    def wire(self):
        panel, private = self.panel, dict(queue=False, api_visibility="private")
        self.source.change(lambda s: gr.update(visible=s == "song"), [self.source], [self.song_group], **private)
        self.picker.dropdown.change(lambda song_id: original_update(self.audio_of(song_id)), [self.picker.dropdown],
                                    [panel.original], **private)

        def run(source, song_id, keep_chords, style, plan_mode, seed, title, request: gr.Request):
            from_song = source == "song"
            params = dict(style=style, source_id=song_id if from_song else None, keep_chords=keep_chords,
                          plan_mode=plan_mode, seed=seed, title=title)
            yield from panel.run("instrumental", params, request, steps=SONG_STEPS if from_song else TEXT_STEPS,
                                 original=self.audio_of(song_id) if from_song else None)

        run_event = self.run_button.click(
            run, [self.source, self.picker.dropdown, self.keep_chords, self.style.prompt, self.plan_mode, self.seed,
                  self.title], panel.outputs, api_visibility="private", **GPU)
        self.stop_button(self.stop, panel, run_event)
        panel.follow(self.run_button)
        panel.wire()
        self.on_select(self.tab)
