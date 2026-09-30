"""Score Editor: change the ABC score with a live sheet preview, then render it."""
from __future__ import annotations

import re

import gradio as gr

from ...core import scores
from ...i18n import lang_of, t
from ..components.result_panel import RENDER_STEPS, ResultPanel, original_update
from ..components.score_view import ScoreView
from ..components.song_picker import SongPicker, has_score
from ..context import GPU
from .base import Tab


def set_tempo(abc, bpm):
    if not abc or not bpm:
        return abc
    return re.sub(r"^Q:1/4=\d+", f"Q:1/4={int(bpm)}", abc, count=1, flags=re.M)


def tempo_of(abc):
    match = re.search(r"^Q:1/4=(\d+)", abc or "", re.M)
    return int(match.group(1)) if match else None


def check_markdown(info, lang):
    if not info["ok"]:
        return "❌ " + t("editor.invalid", lang, detail=info["error"] or "")
    lines = ["✅ " + t("editor.valid", lang, bpm=info["bpm"], key=info["key"], meter=info["meter"],
                         measures=info["measures"], seconds=info["seconds"])]
    changes = info.get("changes")
    if changes and changes.get("checked"):
        lines.append(t("note.melody_same" if changes["melody_preserved"] else "note.melody_changed", lang))
        if changes.get("chords_changed"):
            lines.append(t("note.chords_changed", lang))
    return "\n\n".join(lines)


class EditorTab(Tab):
    id = "editor"
    label = "tab.editor"

    def build(self):
        T, ctx = self.ctx.T, self.ctx
        gr.Markdown(T("editor.intro"), elem_classes="tab-intro")
        self.picker = SongPicker(ctx, "editor.source", accept=has_score)
        with gr.Row(equal_height=False):
            with gr.Column(scale=5):
                self.code = gr.Code(value="", language=None, interactive=True, lines=22, max_lines=40,
                                    label=T("editor.abc"))
                with gr.Row():
                    self.bpm = gr.Number(None, precision=0, minimum=40, maximum=240, label=T("editor.tempo"), scale=2)
                    self.apply_tempo = gr.Button(T("editor.apply_tempo"), size="sm", scale=1)
                    self.strip = gr.Button(T("editor.remove_chords"), size="sm", scale=1)
                    self.reset = gr.Button(T("editor.reset"), size="sm", scale=1)
                self.check = gr.Button(T("editor.check"), variant="secondary")
                self.check_result = gr.Markdown()
                with gr.Accordion(T("editor.help_title"), open=False):
                    gr.Markdown(T("editor.help"))
            with gr.Column(scale=6):
                gr.Markdown(T("editor.preview"), elem_classes="step-title")
                self.preview = ScoreView()
        gr.Markdown(T("editor.step_render"), elem_classes="step-title")
        with gr.Row(equal_height=False):
            with gr.Column(scale=5):
                self.style = gr.Textbox(label=T("style.prompt"), info=T("editor.style_info"), lines=2)
                self.lyrics = gr.Textbox(label=T("field.lyrics"), info=T("editor.lyrics_info"), lines=8, max_lines=24)
                with gr.Accordion(T("field.advanced"), open=False):
                    self.title = gr.Textbox(label=T("field.title"), placeholder=T("field.title_auto"))
                    self.seed = gr.Number(-1, precision=0, label=T("field.seed"), info=T("field.seed_info"))
                with gr.Row():
                    self.run_button = gr.Button(T("editor.run"), variant="primary", size="lg", scale=3)
                    self.stop = gr.Button(T("action.stop"), variant="stop", size="lg", scale=1)
            with gr.Column(scale=6):
                self.panel = ResultPanel(ctx, compare=True, actions=("editor", "restyle", "instrumental"))
        self.open_outputs = [self.picker.dropdown]

    def open(self, song_id, lang):
        return [self.picker.update(song_id, lang)]

    def load_source(self, song_id):
        store = self.studio.store
        if not song_id or not store.exists(song_id):
            return "", None, "", "", "", original_update(None)
        meta, score = store.get(song_id), store.read_score(song_id) or ""
        return score, tempo_of(score), meta.style, meta.lyrics, "", original_update(self.audio_of(song_id))

    def wire(self):
        panel, private = self.panel, dict(queue=False, api_visibility="private")
        self.picker.dropdown.change(self.load_source, [self.picker.dropdown],
                                    [self.code, self.bpm, self.style, self.lyrics, self.check_result, panel.original],
                                    **private)
        # Live preview runs entirely in the browser.
        self.code.change(None, [self.code], [self.preview], js="(abc) => abc", **private)
        self.apply_tempo.click(set_tempo, [self.code, self.bpm], [self.code], **private)
        self.strip.click(lambda abc: scores.melody_only(abc) if abc else abc, [self.code], [self.code], **private)
        self.reset.click(lambda song_id: self.load_source(song_id)[0], [self.picker.dropdown], [self.code], **private)

        def check(abc, song_id, request: gr.Request):
            return check_markdown(self.studio.check_score(abc, song_id), lang_of(request))

        self.check.click(check, [self.code, self.picker.dropdown], [self.check_result], **private)

        def render(abc, song_id, style, lyrics, seed, title, request: gr.Request):
            yield from panel.run("edit", dict(abc=abc, source_id=song_id, style=style, lyrics=lyrics, seed=seed,
                                              title=title), request, steps=RENDER_STEPS,
                                 original=self.audio_of(song_id))

        run_event = self.run_button.click(
            render, [self.code, self.picker.dropdown, self.style, self.lyrics, self.seed, self.title], panel.outputs,
            api_visibility="private", **GPU)
        self.stop_button(self.stop, panel, run_event)
        panel.wire()
        self.on_select(self.tab)
