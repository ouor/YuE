"""State shared by all tabs while the Blocks tree is being built."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import gradio as gr

from ..core import Studio
from ..i18n import lang_of, t, translations

GPU = dict(concurrency_id="gpu", concurrency_limit=1)   # every model call shares one queue slot


@dataclass
class UIContext:
    studio: Studio
    i18n: gr.I18n = field(default_factory=lambda: gr.I18n(**translations()))
    tabs: gr.Tabs | None = None
    current_song: gr.State | None = None
    pages: dict = field(default_factory=dict)            # tab id → Tab instance
    _localizers: list = field(default_factory=list)      # (component, lang → update)

    def T(self, key):
        """Static, browser-translated text for labels and Markdown."""
        return self.i18n(key)

    def localize(self, component, build: Callable[[str], dict]):
        """Refresh a component (e.g. choice labels) in the visitor's language on page load."""
        self._localizers.append((component, build))
        return component

    def choices(self, component, options: dict, prefix: str):
        """Translate choice labels: options maps id → prompt phrase; labels use '<prefix>.<id>'."""
        return self.localize(component, lambda lang: gr.update(
            choices=[(t(f"{prefix}.{key}", lang), key) for key in options]))

    def navigate(self, trigger, target_id, song=None):
        """Wire `trigger` to open tab `target_id` on a song (default: the current song)."""
        page = self.pages[target_id]

        def go(song_id, request: gr.Request):
            return [gr.Tabs(selected=target_id), song_id, *page.open(song_id, lang_of(request))]

        trigger.click(go, [song or self.current_song], [self.tabs, self.current_song, *page.open_outputs],
                      queue=False, api_visibility="private")

    @property
    def localized_components(self):
        return [component for component, _ in self._localizers]

    def localized_updates(self, lang):
        return [build(lang) for _, build in self._localizers]
