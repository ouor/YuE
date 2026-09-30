"""Library: browse every version, inspect lineage, and continue from any song."""
from __future__ import annotations

from datetime import datetime

import gradio as gr

from ...core.models import Operation
from ...i18n import lang_of, t
from ..components.result_panel import ResultPanel
from .base import Tab

OPERATIONS = {"all": "all", **{op.value: op.value for op in Operation}}


def when(stamp):
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stamp


class LibraryTab(Tab):
    id = "library"
    label = "tab.library"

    def build(self):
        T, ctx = self.ctx.T, self.ctx
        gr.Markdown(T("library.intro"), elem_classes="tab-intro")
        with gr.Row():
            self.query = gr.Textbox(label=T("library.search"), placeholder=T("library.search_placeholder"), scale=3)
            self.operation = ctx.choices(gr.Dropdown(list(OPERATIONS), value="all", label=T("library.type"), scale=1),
                                         OPERATIONS, "op")
            self.refresh_button = gr.Button(T("library.refresh"), scale=0, min_width=120)
        self.ids = gr.State([])
        self.table = gr.Dataframe(headers=["Title", "Type", "Status", "Length", "Created"], interactive=False,
                                  wrap=True, max_height=320, elem_classes="library-table")
        with gr.Row(equal_height=False):
            with gr.Column(scale=4):
                self.selected = gr.Markdown(T("library.empty"), elem_classes="library-detail")
                with gr.Row():
                    self.new_title = gr.Textbox(label=T("library.rename"), scale=3)
                    self.rename = gr.Button(T("library.rename_button"), scale=1, size="sm")
                with gr.Row():
                    self.to_cover = gr.Button(T("action.cover"), size="sm", visible=False)
                    self.export = gr.DownloadButton(T("library.export"), size="sm")
                with gr.Row():
                    self.delete = gr.Button(T("library.delete"), variant="stop", size="sm")
                    self.confirm = gr.Button(T("library.confirm_delete"), variant="stop", size="sm", visible=False)
                self.lineage = gr.Markdown(elem_classes="lineage")
            with gr.Column(scale=6):
                self.panel = ResultPanel(ctx, compare=True, actions=("restyle", "editor", "instrumental"))
        self.open_outputs = [self.table, self.ids]

    # -- data -----------------------------------------------------------------
    def rows(self, query, operation, lang):
        songs = self.studio.store.list(None if operation in (None, "all") else operation, query or None)
        table = [[m.title, t("op." + m.operation, lang), t("state." + m.status, lang),
                  f"{m.duration:.0f}s" if m.duration else "", when(m.created_at)] for m in songs]
        headers = [t(f"library.col.{c}", lang) for c in ("title", "type", "status", "length", "created")]
        return gr.update(value=table, headers=headers), [m.id for m in songs]

    def open(self, song_id, lang):
        return list(self.rows("", "all", lang))

    def details(self, song_id, lang):
        store = self.studio.store
        meta = store.get(song_id)
        facts = [f"### {meta.title}",
                 f"**{t('library.type', lang)}** {t('op.' + meta.operation, lang)} · "
                 f"**{t('library.col.status', lang)}** {t('state.' + meta.status, lang)}"]
        if meta.style:
            facts.append(f"**{t('style.prompt', lang)}** {meta.style}")
        if meta.error:
            facts.append(f"**{t('library.error', lang)}** `{meta.error}`")
        chain = store.lineage(song_id)
        lineage = ""
        if len(chain) > 1:
            lineage = f"**{t('library.lineage', lang)}** " + " → ".join(
                f"{m.title} ({t('op.' + m.operation, lang)})" for m in chain)
        # Derived versions play next to their parent; references show their clip (set by the panel).
        panel = self.panel.show(song_id, lang, original=self.audio_of(meta.parent_id) or "")
        return {self.selected: "\n\n".join(facts), self.lineage: lineage, self.new_title: meta.title,
                self.export: gr.update(value=str(store.export_zip(song_id))),
                self.to_cover: gr.update(visible=meta.operation == "transcribe"),
                self.confirm: gr.update(visible=False), **panel}

    # -- events ---------------------------------------------------------------
    def wire(self):
        private = dict(queue=False, api_visibility="private")
        detail_outputs = [self.selected, self.lineage, self.new_title, self.export, self.to_cover, self.confirm,
                          *self.panel.outputs]

        def filter_rows(query, operation, request: gr.Request):
            return self.rows(query, operation, lang_of(request))

        for trigger in (self.query.submit, self.operation.change, self.refresh_button.click):
            trigger(filter_rows, [self.query, self.operation], [self.table, self.ids], **private)

        def select(ids, event: gr.SelectData, request: gr.Request):
            row = event.index[0] if isinstance(event.index, (list, tuple)) else event.index
            if row is None or row >= len(ids):
                return {}
            return self.details(ids[row], lang_of(request))

        self.table.select(select, [self.ids], detail_outputs, **private)

        def rename(song_id, title, query, operation, request: gr.Request):
            lang = lang_of(request)
            if song_id and title.strip():
                self.studio.store.rename(song_id, title)
            return (*self.rows(query, operation, lang), self.details(song_id, lang)[self.selected] if song_id else "")

        self.rename.click(rename, [self.ctx.current_song, self.new_title, self.query, self.operation],
                          [self.table, self.ids, self.selected], **private)
        self.delete.click(lambda: gr.update(visible=True), None, [self.confirm], **private)

        def delete(song_id, query, operation, request: gr.Request):
            lang = lang_of(request)
            if song_id and self.studio.store.exists(song_id):
                self.studio.store.delete(song_id)
            return (*self.rows(query, operation, lang), t("library.deleted", lang), gr.update(visible=False), None)

        self.confirm.click(delete, [self.ctx.current_song, self.query, self.operation],
                           [self.table, self.ids, self.selected, self.confirm, self.ctx.current_song], **private)
        self.ctx.navigate(self.to_cover, "cover")
        self.panel.wire()
        self.on_select(self.tab)
