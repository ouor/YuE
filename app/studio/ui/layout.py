"""Assemble the Blocks app: header, registered tabs, localization, and the API."""
from __future__ import annotations

from pathlib import Path

import gradio as gr

from ..api import register_api
from ..i18n import lang_of
from .components.score_view import HEAD as SCORE_HEAD
from .context import SCROLL_TOP, UIContext
from .tabs import TABS

ASSETS = Path(__file__).parent / "assets"


def build(studio):
    with gr.Blocks(title="YuE2 Song Studio") as demo:
        ctx = UIContext(studio)
        with gr.Row(elem_classes="app-header"):
            gr.Markdown(ctx.T("app.header"))
        ctx.current_song = gr.State(None)
        pages = []
        with gr.Tabs(elem_id="main-tabs") as ctx.tabs:
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
        mobile_nav(ctx, pages)

        def localize(request: gr.Request):
            return ctx.localized_updates(lang_of(request))

        demo.load(localize, None, ctx.localized_components, queue=False, api_visibility="private")
        register_api(studio)
    return demo, ctx


def mobile_nav(ctx, pages):
    """Bottom tab bar for phones (CSS hides it on wider screens and hides the top tab strip on phones)."""
    ids = [page.id for page in pages]
    with gr.Row(elem_classes="mobile-nav", elem_id="mobile-nav"):
        buttons = [gr.Button(ctx.T(f"nav.{tab_id}"), size="sm", elem_classes="nav-item",
                             variant="primary" if index == 0 else "secondary")
                   for index, tab_id in enumerate(ids)]

    def highlight(active):
        return [gr.update(variant="primary" if tab_id == active else "secondary") for tab_id in ids]

    private = dict(queue=False, api_visibility="private")
    for tab_id, button in zip(ids, buttons):
        button.click(lambda t=tab_id: gr.Tabs(selected=t), None, ctx.tabs, **private)
        button.click(None, None, None, js=SCROLL_TOP, **private)
    # Selecting a tab any other way (next-step buttons, library links) keeps the bar in sync.
    for page in pages:
        page.tab.select(lambda t=page.id: highlight(t), None, buttons, **private)


def launch_options(settings):
    page_css = (ASSETS / "page.css").read_text(encoding="utf-8")
    return dict(css=(ASSETS / "app.css").read_text(encoding="utf-8"), head=SCORE_HEAD + f"<style>{page_css}</style>",
                js=(ASSETS / "app.js").read_text(encoding="utf-8"),
                allowed_paths=[str(settings.data_dir)], theme=gr.themes.Soft(primary_hue="violet"))
