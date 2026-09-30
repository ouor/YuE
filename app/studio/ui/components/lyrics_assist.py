"""'Continue with AI' row under a lyrics box: an optional theme and a button that streams lyrics in."""
from __future__ import annotations

import logging

import gradio as gr

from ...core import UserError
from ...core.messages import user_message
from ...i18n import lang_of

log = logging.getLogger("studio")


class LyricsAssist:
    """Fills `lyrics` from the style (and title/theme); `melody` = (component, value → ABC or song id) fits a score."""

    def __init__(self, ctx, lyrics, style, *, title=None, melody=None, melody_is_song=False):
        self.ctx, self.lyrics, self.style, self.title = ctx, lyrics, style, title
        self.melody, self.melody_is_song = melody, melody_is_song
        visible = ctx.studio.assistant.available
        T = ctx.T
        with gr.Row(equal_height=True, visible=visible, elem_classes="assist-row"):
            self.theme = gr.Textbox(label=T("assist.theme"), placeholder=T("assist.theme_placeholder"), scale=4,
                                    max_lines=2)
            self.button = gr.Button(T("assist.run"), variant="secondary", scale=1, min_width=140,
                                    elem_classes="assist-button")

    def wire(self):
        # Fixed arity (Gradio injects gr.Request only into plain signatures); absent inputs become empty states.
        inputs = [self.style, self.lyrics, self.theme, self.title or gr.State(""), self.melody or gr.State(None)]
        studio = self.ctx.studio

        def fill(style, lyrics, theme, title, melody, request: gr.Request):
            lang = lang_of(request)
            try:
                job = studio.lyrics_request(style=style, lyrics=lyrics, title=title, theme=theme, lang=lang,
                                            source_id=melody if self.melody_is_song else None,
                                            melody_abc=None if self.melody_is_song else melody)
                for text in studio.stream_lyrics(job):
                    yield gr.update(value=text)
            except UserError as exc:
                if exc.key == "error.assist_failed":
                    log.warning("Lyric assistant failed: %s", exc.params.get("detail"))
                raise gr.Error(user_message(exc, lang))

        # Network-bound, not GPU work: several people can write lyrics while a song renders.
        self.button.click(fill, inputs, self.lyrics, concurrency_id="assist", concurrency_limit=4,
                          show_progress="minimal", api_visibility="private")
