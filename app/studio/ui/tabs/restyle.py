"""New Genre: keep a song's melody and re-render it in another style."""
from __future__ import annotations

import gradio as gr

from ...core import styles
from ..components.lyrics_assist import LyricsAssist
from ..components.result_panel import RENDER_STEPS, ResultPanel, original_update
from ..components.score_view import ScoreView
from ..components.song_picker import SongPicker, has_score
from ..components.style_builder import StyleBuilder
from ..context import GPU
from .base import Tab


def language_of(style):
    """Guess the style builder's language option from a prompt like 'English, pop, ...'."""
    first = (style or "").split(",")[0].strip().lower()
    return next((key for key, phrase in styles.LANGUAGES.items() if phrase.lower() == first), None)


class RestyleTab(Tab):
    id = "restyle"
    label = "tab.restyle"

    def build(self):
        T, ctx = self.ctx.T, self.ctx
        gr.Markdown(T("restyle.intro"), elem_classes="tab-intro")
        with gr.Row(equal_height=False):
            with gr.Column(scale=5):
                gr.Markdown(T("restyle.step1"), elem_classes="step-title")
                self.picker = SongPicker(ctx, "restyle.source", accept=lambda m: has_score(m) and m.lyrics.strip())
                with gr.Accordion(T("restyle.source_score"), open=False):
                    self.source_score = ScoreView()
                gr.Markdown(T("restyle.step2"), elem_classes="step-title")
                self.style = StyleBuilder(ctx, presets=styles.PRESET_GROUPS["restyle"], keep_language=True)
                self.lyrics = gr.Textbox(label=T("field.lyrics"), info=T("restyle.lyrics_info"), lines=8, max_lines=24)
                # New words must still fit the kept melody.
                self.assist = LyricsAssist(ctx, self.lyrics, self.style.prompt, melody=self.picker.dropdown,
                                           melody_is_song=True)
                self.keep_chords = gr.Checkbox(False, label=T("restyle.keep_chords"), info=T("restyle.keep_chords_info"))
                with gr.Accordion(T("field.advanced"), open=False):
                    self.title = gr.Textbox(label=T("field.title"), placeholder=T("field.title_auto"))
                    self.seed = gr.Number(-1, precision=0, label=T("field.seed"), info=T("field.seed_info"))
                with gr.Row():
                    self.run_button = gr.Button(T("restyle.run"), variant="primary", size="lg", scale=3)
                    self.stop = gr.Button(T("action.stop"), variant="stop", size="lg", scale=1)
            with gr.Column(scale=6):
                self.panel = ResultPanel(ctx, self.id, compare=True, actions=("restyle", "editor", "instrumental"))
        self.open_outputs = [self.picker.dropdown]

    def open(self, song_id, lang):
        return [self.picker.update(song_id, lang)]

    def load_source(self, song_id):
        store = self.studio.store
        if not song_id or not store.exists(song_id):
            return original_update(None), "", "", gr.skip()
        meta = store.get(song_id)
        language = language_of(meta.style)
        return (original_update(self.audio_of(song_id)), store.read_score(song_id) or "", meta.lyrics,
                gr.update(value=language) if language else gr.skip())

    def wire(self):
        panel = self.panel
        self.picker.dropdown.change(self.load_source, [self.picker.dropdown],
                                    [panel.original, self.source_score, self.lyrics, self.style.language],
                                    queue=False, api_visibility="private").then(
            self.style.compose, self.style.fields, self.style.prompt, queue=False, api_visibility="private")

        def restyle(source_id, style, lyrics, keep_chords, seed, title, request: gr.Request):
            yield from panel.run("restyle", dict(source_id=source_id, style=style, lyrics=lyrics,
                                                 keep_chords=keep_chords, seed=seed, title=title),
                                 request, steps=RENDER_STEPS, original=self.audio_of(source_id))

        run_event = self.run_button.click(
            restyle, [self.picker.dropdown, self.style.prompt, self.lyrics, self.keep_chords, self.seed, self.title],
            panel.outputs, api_visibility="private", **GPU)
        self.stop_button(self.stop, panel, run_event)
        self.assist.wire()
        panel.follow(self.run_button)
        panel.wire()
        self.on_select(self.tab)
