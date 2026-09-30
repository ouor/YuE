"""Point-and-click style builder that assembles an editable YuE2 style prompt."""
from __future__ import annotations

import gradio as gr

from ...core import styles


class StyleBuilder:
    def __init__(self, ctx, *, instrumental=False, presets=None, value=None, keep_language=False):
        """keep_language: presets leave the language alone (lyrics already exist in one language)."""
        self.ctx, self.instrumental, self.keep_language = ctx, instrumental, keep_language
        T = ctx.T
        default = styles.PRESETS[(presets or ["piano_pop"])[0]] if value is None else value
        self.preset_names = presets or []
        with gr.Group():
            if self.preset_names:
                with gr.Row(elem_classes="preset-row"):
                    gr.Markdown(T("style.presets"), elem_classes="preset-label")
                    self.preset_buttons = [(name, gr.Button(T(f"preset.{name}"), size="sm", variant="secondary"))
                                           for name in self.preset_names]
            else:
                self.preset_buttons = []
            with gr.Row():
                self.language = ctx.choices(gr.Dropdown(
                    choices=list(styles.LANGUAGES), value=default.get("language"), label=T("style.language"),
                    visible=not instrumental, scale=1), styles.LANGUAGES, "language")
                self.vocal = ctx.choices(gr.Radio(
                    choices=list(styles.VOCALS), value=default.get("vocal"), label=T("style.vocal"),
                    visible=not instrumental, scale=2), styles.VOCALS, "vocal")
            with gr.Row():
                self.genres = ctx.choices(gr.Dropdown(
                    choices=list(styles.GENRES), value=default.get("genres"), multiselect=True, max_choices=3,
                    label=T("style.genre")), styles.GENRES, "genre")
                self.moods = ctx.choices(gr.Dropdown(
                    choices=list(styles.MOODS), value=default.get("moods"), multiselect=True, max_choices=3,
                    label=T("style.mood")), styles.MOODS, "mood")
            self.instruments = ctx.choices(gr.Dropdown(
                choices=list(styles.INSTRUMENTS), value=default.get("instruments"), multiselect=True,
                label=T("style.instruments")), styles.INSTRUMENTS, "instrument")
            with gr.Row():
                self.bpm = gr.Slider(0, 200, value=default.get("bpm") or 0, step=1, label=T("style.tempo"),
                                     info=T("style.tempo_info"), scale=1)
                self.extra = gr.Textbox(label=T("style.extra"), placeholder=T("style.extra_placeholder"), scale=2)
            self.prompt = gr.Textbox(value=self.compose(*self.values(default)), label=T("style.prompt"),
                                     info=T("style.prompt_info"), lines=2, max_lines=4, interactive=True)
        self.fields = [self.language, self.vocal, self.genres, self.moods, self.instruments, self.bpm, self.extra]
        for field in self.fields:
            field.input(self.compose, self.fields, self.prompt, queue=False, api_visibility="private")
        for name, button in self.preset_buttons:
            button.click(lambda language, n=name: self.preset_updates(n, language), [self.language],
                         self.fields + [self.prompt], queue=False, api_visibility="private")

    @staticmethod
    def values(preset):
        return (preset.get("language"), preset.get("vocal"), preset.get("genres"), preset.get("moods"),
                preset.get("instruments"), preset.get("bpm"), preset.get("extra", ""))

    def compose(self, language, vocal, genres, moods, instruments, bpm, extra):
        return styles.compose_style(language, genres, moods, instruments, vocal, bpm, extra,
                                    instrumental=self.instrumental)

    def preset_updates(self, name, language=None):
        values = list(self.values(styles.PRESETS[name]))
        if self.keep_language:
            values[0] = language
        return [*values, self.compose(*values)]
