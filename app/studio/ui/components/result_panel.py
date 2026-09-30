"""Result card: live progress, audio, score, notes, and next-step actions."""
from __future__ import annotations

import html
import logging
import time

import gradio as gr

from ...core import UserError
from ...core.store import SongStore
from ...i18n import lang_of, t
from ..context import MOBILE
from .score_view import ScoreView

log = logging.getLogger("studio")

# (stage id, label key). A tab passes the steps its workflow reports.
CREATE_STEPS = [("plan", "step.plan"), ("compose", "step.compose"), ("render", "step.render")]
# Instant, not smooth: live status updates cancel an in-flight smooth scroll.
SCROLL_TO = ("() => { if (" + MOBILE + ") setTimeout(() => document.getElementById('%s')"
             "?.scrollIntoView({block: 'start'}), 150); }")
KEEP = object()   # present(): leave the "original" player untouched
RENDER_STEPS = [("plan", "step.prepare"), ("compose", "step.compose"), ("render", "step.render")]


class ResultPanel:
    def __init__(self, ctx, key, *, compare=False, actions=("restyle", "editor", "instrumental")):
        self.ctx, self.elem_id = ctx, f"result-{key}"
        T = ctx.T
        with gr.Group(elem_classes="result-card", elem_id=self.elem_id):
            self.status = ctx.localize(gr.HTML(status_html("idle", t("status.idle")), elem_classes="job-status-wrap"),
                                       lambda lang: status_html("idle", t("status.idle", lang)))
            with gr.Row():
                self.original = gr.Audio(label=T("result.original"), interactive=False, type="filepath",
                                         visible=False, buttons=["download"])
                self.audio = gr.Audio(label=T("result.audio"), interactive=False, type="filepath",
                                      buttons=["download"])
            with gr.Tabs():
                with gr.Tab(T("result.sheet")):
                    self.score = ScoreView()
                with gr.Tab(T("result.abc")):
                    self.code = gr.Code(value="", language=None, interactive=False, lines=10, max_lines=18,
                                        wrap_lines=True)
            self.notice = gr.Markdown(visible=False, elem_classes="result-notice")
            self.record = gr.Button(T("action.record"), variant="primary", visible=False)
            with gr.Row(visible=False, elem_classes="next-steps") as self.actions:
                gr.Markdown(T("result.next"), elem_classes="next-label")
                self.nav = {name: gr.Button(T(f"action.{name}"), size="sm") for name in actions}
                self.download = gr.DownloadButton(T("action.download"), size="sm", visible=False)
        self.outputs = [self.status, self.original, self.audio, self.score, self.code, self.notice, self.record,
                        self.actions, self.download, ctx.current_song]

    def wire(self):
        for name, button in self.nav.items():
            self.ctx.navigate(button, name)

    def follow(self, *triggers):
        """On phones the card sits below the form: bring it into view when a job starts."""
        for trigger in triggers:
            trigger.click(None, None, None, js=SCROLL_TO % self.elem_id, queue=False, api_visibility="private")

    # -- streaming -----------------------------------------------------------
    def run(self, workflow, params, request, *, steps=CREATE_STEPS, original=None, on_done=None):
        """Generator for Gradio: stream a workflow's events into this panel."""
        view = JobView(self, lang_of(request), steps)
        yield view.start(original)
        try:
            for event in self.ctx.studio.stream(workflow, session=request.session_hash, **params):
                updates = view.apply(event)
                if view.meta is not None and on_done is not None:
                    updates.update(on_done(view.meta, view.lang))
                if updates:
                    yield updates
        except UserError as exc:
            yield view.fail(t(exc.key, view.lang, **exc.params))

    def stopped(self, song_id, lang):
        """View after a Stop: the saved score (and Record button) if the job got that far."""
        view = JobView(self, lang, [])
        store = self.ctx.studio.store
        if not song_id or not store.exists(song_id):
            return {self.status: status_html("cancelled", t("status.cancelled", lang))}
        meta = store.get(song_id)
        if meta.status == "complete":
            return view.present(meta)
        score = store.read_score(song_id) or ""
        return {self.status: status_html("cancelled", t("status.cancelled", lang)), self.score: score,
                self.code: score, self.record: gr.update(visible=meta.status == "planned"),
                self.ctx.current_song: song_id}

    def show(self, song_id, lang, original=None):
        """Static view of an existing song (e.g. picked in the library)."""
        view = JobView(self, lang, [])
        return view.present(self.ctx.studio.store.get(song_id), KEEP if original is None else original)


class JobView:
    def __init__(self, panel, lang, steps):
        self.panel, self.lang, self.steps = panel, lang, steps
        self.store = panel.ctx.studio.store
        self.started = time.monotonic()
        self.active, self.done, self.detail = None, [], ""
        self.song_id, self.meta = None, None

    def _status(self):
        items = []
        for stage, key in self.steps:
            state = "done" if stage in self.done else "active" if stage == self.active else "pending"
            extra = f"<small>{html.escape(self.detail)}</small>" if state == "active" and self.detail else ""
            items.append(f'<li class="{state}"><span class="dot"></span>{html.escape(t(key, self.lang))}{extra}</li>')
        elapsed = t("status.elapsed", self.lang, time=clock(time.monotonic() - self.started))
        return (f'<div class="job-status running"><ol class="steps">{"".join(items)}</ol>'
                f'<div class="elapsed">{elapsed}</div></div>')

    def start(self, original):
        p = self.panel
        return {p.status: self._status(), p.audio: None, p.original: original_update(original), p.score: "", p.code: "",
                p.notice: gr.update(visible=False), p.record: gr.update(visible=False),
                p.actions: gr.update(visible=False), p.download: gr.update(visible=False)}

    def apply(self, event):
        p, data = self.panel, event.data
        if event.kind == "song":
            self.song_id = data["song_id"]
            return {p.ctx.current_song: self.song_id}
        if event.kind == "stage":
            stage = data["stage"]
            known = [s for s, _ in self.steps]
            if stage not in known or stage in self.done or stage == self.active:
                return {}
            if self.active:
                self.done.append(self.active)
            # Stages skipped by this run (e.g. no planning for a provided score) count as done.
            self.done.extend(s for s in known[:known.index(stage)] if s not in self.done)
            self.active, self.detail = stage, ""
            return {p.status: self._status()}
        if event.kind == "tick":
            return {p.status: self._status()} if self.active else {}
        if event.kind == "tokens":
            self.detail = t("status.tokens", self.lang, count=f"{data['count']:,}")
            return {p.status: self._status()}
        if event.kind == "transcribe":
            self.detail = str(data.get("stage", "")).replace("_", " ")
            return {p.status: self._status()}
        if event.kind == "score":
            return {p.score: data["abc"], p.code: data["abc"]}
        if event.kind == "done":
            self.meta = data["result"]
            return self.present(self.meta, elapsed=time.monotonic() - self.started)
        if event.kind == "error":
            if data.get("cancelled"):
                return self.fail(t("status.cancelled", self.lang), kind="cancelled")
            exc = data["exception"]
            if isinstance(exc, UserError):
                return self.fail(t(exc.key, self.lang, **exc.params))
            log.error("Job failed", exc_info=exc)
            return self.fail(t("error.unexpected", self.lang, detail=f"{type(exc).__name__}: {exc}"))
        return {}

    def fail(self, message, kind="error"):
        p = self.panel
        updates = {p.status: status_html(kind, message)}
        if self.song_id and self.store.exists(self.song_id):
            meta = self.store.get(self.song_id)
            planned = meta.status == "planned"
            updates[p.record] = gr.update(visible=planned)
        return updates

    def present(self, meta, original=KEEP, elapsed=None):
        p, lang = self.panel, self.lang
        score = self.store.read_score(meta.id) or ""
        audio = self.store.file(meta.id, SongStore.PREVIEW) or self.store.file(meta.id, SongStore.AUDIO)
        flac = self.store.file(meta.id, SongStore.AUDIO)
        planned = meta.status == "planned"
        if meta.operation == "transcribe":
            message, kind = t("status.transcribed", lang), "done"
            original = self.store.source_audio(meta.id)
        elif planned:
            message, kind = t("status.planned", lang), "planned"
        elif meta.status == "complete":
            message, kind = t("status.done", lang, seconds=f"{meta.duration or 0:.0f}",
                              time=clock(elapsed if elapsed is not None else meta_seconds(meta))), "done"
        else:
            message, kind = t("status.failed_song", lang, detail=meta.error or meta.status), "error"
        notes = describe(meta, lang)
        return {p.status: status_html(kind, message), p.audio: str(audio) if audio else None,
                p.original: gr.skip() if original is KEEP else original_update(original),
                p.score: score, p.code: score, p.notice: gr.update(value=notes, visible=bool(notes)),
                p.record: gr.update(visible=planned),
                p.actions: gr.update(visible=bool(score) or meta.status == "complete"),
                p.download: gr.update(value=str(flac) if flac else None, visible=flac is not None),
                p.ctx.current_song: meta.id}


def original_update(path):
    """Show the "original" player only when there is something to compare against."""
    return gr.update(value=str(path) if path else None, visible=bool(path))


def clock(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def meta_seconds(meta):
    render = (meta.timing or {}).get("render", {})
    plan = (meta.timing or {}).get("plan", {})
    return (render.get("render_seconds") or 0) + (plan.get("seconds") or 0)


def status_html(kind, message):
    icon = {"idle": "&#9835;", "done": "&#10003;", "planned": "&#9998;", "cancelled": "&#9632;", "error": "!"}.get(kind, "")
    return f'<div class="job-status {kind}"><span class="icon">{icon}</span><span>{html.escape(message)}</span></div>'


def describe(meta, lang):
    """Plain-language notes about a result: warnings first, then what changed."""
    lines = []
    if meta.is_truncated:
        lines.append("⚠️ " + t("note.truncated", lang))
    extra = meta.extra or {}
    if meta.operation in {"restyle", "cover"} and ("keep_chords" in extra or "keep_harmony" in extra):
        kept = extra.get("keep_chords", extra.get("keep_harmony"))
        lines.append(t("note.chords_kept" if kept else "note.chords_free", lang))
    changes = extra.get("changes")
    if changes and changes.get("checked"):
        lines.append(t("note.melody_same" if changes["melody_preserved"] else "note.melody_changed", lang))
        if changes.get("chords_changed"):
            lines.append(t("note.chords_changed", lang))
        before, after = changes.get("tempo") or [None, None]
        if before != after:
            lines.append(t("note.tempo_changed", lang, before=(before or "?").split("=")[-1],
                           after=(after or "?").split("=")[-1]))
    transfer = extra.get("transfer")
    if transfer:
        lines.append(t("note.transfer", lang, moved=transfer.get("vocal_notes_before", 0),
                       kept=transfer.get("unaltered_ins_notes", 0)))
    score_info = extra.get("score")
    if meta.operation == "transcribe" and score_info:
        lines.append(t("note.transcribed", lang, notes=score_info.get("vocal_notes", 0) + score_info.get("ins_notes", 0),
                       bpm=score_info.get("bpm") or "?", key=score_info.get("key") or "?",
                       sections=", ".join(score_info.get("sections") or []) or "-"))
    facts = [t("mode." + meta.mode, lang)] if meta.mode and meta.operation != "transcribe" else []
    if meta.operation != "transcribe":
        facts.append(t("note.seed", lang, seed=meta.seed))
    if facts:
        lines.append(" · ".join(facts))
    return "\n\n".join(lines)
