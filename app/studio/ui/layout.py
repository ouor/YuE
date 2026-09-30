"""Assemble the Blocks app: header, registered tabs, localization, and the API."""
from __future__ import annotations

from pathlib import Path

import gradio as gr

from ..api import register_api
from ..i18n import lang_of
from .components.score_view import HEAD as SCORE_HEAD
from .context import UIContext
from .tabs import TABS

ASSETS = Path(__file__).parent / "assets"


def build(studio):
    with gr.Blocks(title="YuE2 Song Studio") as demo:
        ctx = UIContext(studio)
        with gr.Row(elem_classes="app-header"):
            gr.Markdown(ctx.T("app.header"))
        ctx.current_song = gr.State(None)
        pages = []
        with gr.Tabs() as ctx.tabs:
            for cls in TABS:
                with gr.Tab(ctx.T(cls.label), id=cls.id) as tab:
                    page = cls(ctx)
                    page.tab = tab
                    page.build()
                    pages.append(page)
                    ctx.pages[cls.id] = page
        for page in pages:
            page.wire()
        gr.Markdown(ctx.T("app.footer"), elem_classes="app-footer")

        def localize(request: gr.Request):
            return ctx.localized_updates(lang_of(request))

        demo.load(localize, None, ctx.localized_components, queue=False, api_visibility="private")
        register_api(studio)
    return demo, ctx


def launch_options(settings):
    return dict(css=(ASSETS / "app.css").read_text(encoding="utf-8"), head=SCORE_HEAD,
                allowed_paths=[str(settings.data_dir)], theme=gr.themes.Soft(primary_hue="violet"))
