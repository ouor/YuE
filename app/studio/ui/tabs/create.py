"""Create: lyrics + style → score → song, with an optional score review step."""
from __future__ import annotations

import gradio as gr

from ...core import styles
from ..components.result_panel import CREATE_STEPS, ResultPanel
from ..components.style_builder import StyleBuilder
from ..context import GPU
from .base import Tab

EXAMPLES = [
    ["Paper Boats", "[Verse]\nFold the morning into paper boats\nLet them drift where the river goes\n"
                    "Every wish a little sail of white\nCarried off into the light\n\n[Chorus]\n"
                    "Float away, float away\nTake my worries down the bay\nIf the sky should turn to grey\n"
                    "I will fold another day"],
    ["첫눈", "[Verse]\n창밖에 하얀 눈이 내려와\n조용히 너의 이름을 불러\n차가운 바람 속에 스며든\n"
            "따뜻한 기억 하나\n\n[Chorus]\n첫눈처럼 네게 갈게\n하얗게 물든 이 거리 위로\n"
            "멈춰 있던 시간 속에서\n다시 너를 만날게"],
]
MODES = {"full": "full", "melody": "melody", "off": "off"}


class CreateTab(Tab):
    id = "create"
    label = "tab.create"

    def build(self):
        T, ctx = self.ctx.T, self.ctx
        gr.Markdown(T("create.intro"), elem_classes="tab-intro")
        with gr.Row(equal_height=False):
            with gr.Column(scale=5):
                gr.Markdown(T("create.step1"), elem_classes="step-title")
                self.style = StyleBuilder(ctx, presets=["piano_pop", "city_pop", "kpop_dance", "rock_anthem"])
                gr.Markdown(T("create.step2"), elem_classes="step-title")
                self.title = gr.Textbox(label=T("field.title"), placeholder=T("field.title_placeholder"))
                self.lyrics = gr.Textbox(value=EXAMPLES[0][1], label=T("field.lyrics"), info=T("field.lyrics_info"),
                                         lines=12, max_lines=30)
                with gr.Row(elem_classes="tag-row"):
                    self.tags = [gr.Button(f"+ {tag}", size="sm", variant="secondary") for tag in styles.SECTION_TAGS]
                # Buttons instead of gr.Examples: its table headers cannot show translated labels.
                with gr.Row(elem_classes="preset-row"):
                    gr.Markdown(T("create.examples"), elem_classes="preset-label")
                    self.examples = [gr.Button(title, size="sm", variant="secondary") for title, _ in EXAMPLES]
                with gr.Accordion(T("field.advanced"), open=False):
                    self.mode = ctx.choices(gr.Radio(list(MODES), value="full", label=T("field.mode"),
                                                     info=T("field.mode_info")), MODES, "mode")
                    self.seed = gr.Number(-1, precision=0, label=T("field.seed"), info=T("field.seed_info"))
                self.review = gr.Checkbox(False, label=T("create.review_first"), info=T("create.review_first_info"))
                with gr.Row():
                    self.run_button = gr.Button(T("create.run"), variant="primary", size="lg", scale=3)
                    self.stop = gr.Button(T("action.stop"), variant="stop", size="lg", scale=1)
            with gr.Column(scale=6):
                self.panel = ResultPanel(ctx)

        for (title, lyrics), button in zip(EXAMPLES, self.examples):
            button.click(lambda t=title, l=lyrics: (t, l), None, [self.title, self.lyrics], queue=False,
                         api_visibility="private")
        for tag, button in zip(styles.SECTION_TAGS, self.tags):
            button.click(lambda text, tag=tag: (text.rstrip() + f"\n\n[{tag}]\n").lstrip(), self.lyrics, self.lyrics,
                         queue=False, api_visibility="private")

    def wire(self):
        panel = self.panel

        def create(style, lyrics, title, mode, seed, review, request: gr.Request):
            yield from panel.run("create", dict(style=style, lyrics=lyrics, title=title, mode=mode, seed=seed,
                                                review_first=review), request, steps=CREATE_STEPS)

        def record(song_id, request: gr.Request):
            yield from panel.run("render_planned", dict(song_id=song_id), request, steps=CREATE_STEPS[1:])

        run_event = self.run_button.click(
            create, [self.style.prompt, self.lyrics, self.title, self.mode, self.seed, self.review], panel.outputs,
            api_visibility="private", **GPU)
        record_event = panel.record.click(record, [self.ctx.current_song], panel.outputs, api_visibility="private", **GPU)
        self.stop_button(self.stop, panel, run_event, record_event)
        panel.wire()
