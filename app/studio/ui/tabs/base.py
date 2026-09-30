"""Tab base class. A tab builds its components, then wires cross-tab events."""
from __future__ import annotations

import gradio as gr

from ...i18n import lang_of


class Tab:
    id = ""
    label = ""                 # translation key

    def __init__(self, ctx):
        self.ctx = ctx
        self.studio = ctx.studio
        self.open_outputs: list = []   # components refreshed by open()

    def build(self):
        """Create components. Runs inside this tab's gr.Tab context."""
        raise NotImplementedError

    def wire(self):
        """Register events that reference other tabs (all tabs exist by now)."""

    def open(self, song_id, lang):
        """Updates for open_outputs when another tab sends the user here with `song_id`."""
        return []

    def refresh(self, song_id, lang):
        """Updates for open_outputs when the user clicks the tab header."""
        return self.open(song_id, lang)

    # -- helpers --------------------------------------------------------------
    def audio_of(self, song_id):
        """Playable audio for a song (rendered preview or reference clip), as a path string."""
        store = self.studio.store
        if not song_id or not store.exists(song_id):
            return None
        path = store.playable_audio(song_id)
        return str(path) if path else None

    def on_select(self, tab):
        if not self.open_outputs:
            return

        def refresh(song_id, request: gr.Request):
            updates = self.refresh(song_id, lang_of(request))
            # Gradio treats a single output's return value as-is, so unwrap one-item lists.
            return updates[0] if len(self.open_outputs) == 1 else updates

        tab.select(refresh, [self.ctx.current_song], self.open_outputs, queue=False, api_visibility="private")

    def stop_button(self, button, panel, *events):
        """Stop the running job, then show what was kept (e.g. a score that can still be recorded)."""
        def cancel(request: gr.Request):
            # Gradio drops the cancelled event's remaining updates, so this handler draws the result.
            song_id = self.studio.cancel(request.session_hash, wait=15)
            return panel.stopped(song_id, lang_of(request))

        button.click(cancel, None, panel.outputs, cancels=list(events), queue=False, api_visibility="private")
