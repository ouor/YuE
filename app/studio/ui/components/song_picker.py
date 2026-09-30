"""Library dropdown for choosing the song a workflow starts from."""
from __future__ import annotations

from datetime import datetime

import gradio as gr

from ...i18n import t


def song_label(meta, lang):
    try:
        stamp = datetime.fromisoformat(meta.created_at).astimezone().strftime("%m-%d %H:%M")
    except ValueError:
        stamp = meta.created_at
    return f"{meta.title} · {t('op.' + meta.operation, lang)} · {stamp}"


class SongPicker:
    def __init__(self, ctx, label_key, accept=None):
        self.ctx = ctx
        self.accept = accept or (lambda meta: True)
        self.dropdown = gr.Dropdown(choices=[], value=None, label=ctx.T(label_key), interactive=True,
                                    allow_custom_value=False)

    def choices(self, lang):
        return [(song_label(m, lang), m.id) for m in self.ctx.studio.store.list() if self.accept(m)]

    def update(self, song_id, lang):
        choices = self.choices(lang)
        ids = {value for _, value in choices}
        return gr.update(choices=choices, value=song_id if song_id in ids else (choices[0][1] if choices else None))


def has_score(meta):
    return meta.status in {"complete", "planned"} and meta.score_origin != "none"
