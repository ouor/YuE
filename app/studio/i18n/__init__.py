"""Translation tables shared by static UI text (gr.I18n) and server-side messages.

English is the base language; other locales fall back to it key by key.
Add a language by dropping <code>.json next to en.json.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

BASE = "en"
DIRECTORY = Path(__file__).parent


@lru_cache(maxsize=1)
def translations() -> dict[str, dict[str, str]]:
    tables = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(DIRECTORY.glob("*.json"))}
    base = tables[BASE]
    return {lang: {**base, **table} for lang, table in tables.items()}


def languages():
    return list(translations())


def resolve(locale: str | None) -> str:
    """Map a BCP 47 tag or Accept-Language header ('ko-KR,ko;q=0.9') to a known language."""
    for part in (locale or "").split(","):
        tag = part.split(";")[0].strip().lower()
        for candidate in (tag, tag.split("-")[0]):
            if candidate in translations():
                return candidate
    return BASE


def t(key: str, lang: str = BASE, /, **params) -> str:
    # Positional-only, so templates may use {key} (e.g. a musical key) as a parameter.
    table = translations().get(lang) or translations()[BASE]
    text = table.get(key) or translations()[BASE].get(key) or key
    try:
        return text.format(**params) if params else text
    except (KeyError, IndexError, ValueError):
        return text


def lang_of(request) -> str:
    """Language for a Gradio request, from its Accept-Language header."""
    headers = getattr(request, "headers", None) or {}
    return resolve(headers.get("accept-language"))
