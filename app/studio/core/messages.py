"""User-facing wording for errors, including plain-language score parser messages."""
from __future__ import annotations

import re

from ..i18n import t

LOCATION = re.compile(r"^group (?P<line>\d+)(?:, (?P<part>Vocal|Ins)(?:, bar (?P<bar>\d+))?)?: (?P<rest>.*)$", re.S)
PART_ONLY = re.compile(r"^(?P<part>Vocal|Ins): (?P<rest>.*)$", re.S)

# (pattern on the parser's English message, translation key, captured params)
PROBLEMS = [
    (r"unsupported duration (?P<units>\d+)", "abc.duration"),
    (r"note/rest exceeds meter duration|event after the measure end", "abc.overflow"),
    (r"duration .* != meter duration", "abc.bar_length"),
    (r"must end with a plain barline", "abc.barline"),
    (r"empty measure|double/repeat barline", "abc.empty_bar"),
    (r"expected 1.4 measures", "abc.bars_per_line"),
    (r"expected V: |missing music line|Dangling section comment", "abc.voice_order"),
    (r"voices have different measure counts|meter/time grids differ|bar meter/time grid differs", "abc.bar_count"),
    (r"unresolved tie", "abc.tie_end"),
    (r"tie (?:enters|changes pitch)", "abc.tie"),
    (r"unsupported chord '(?P<chord>[^']*)'", "abc.chord"),
    (r"unsupported token at '(?P<token>[^']{0,12})", "abc.token"),
    (r"outside MIDI range", "abc.pitch"),
    (r"mixed octave marks", "abc.octave"),
    (r"a rest cannot have", "abc.rest_marks"),
    (r"Unsupported key '(?P<key>[^']*)'", "abc.key"),
    (r"Unsupported meter", "abc.meter"),
    (r"quarter-note tempo", "abc.tempo"),
    (r"Incomplete native|Expected native X:1|Missing header|Preserve native|Expected L:|Unsupported L:|duplicate .*field",
     "abc.header"),
]


def explain_abc(detail, lang):
    """Turn a score parser message into 'where: what to do', in the user's language."""
    detail = (detail or "").strip()
    if not detail or detail == "empty":
        return capitalize(t("abc.empty", lang))
    location, rest = "", detail
    if match := LOCATION.match(detail):
        part = t(f"abc.part.{match['part']}", lang) if match["part"] else None
        if match["bar"]:
            location = t("abc.at_bar", lang, line=match["line"], part=part, bar=match["bar"])
        elif part:
            location = t("abc.at_part", lang, line=match["line"], part=part)
        else:
            location = t("abc.at_line", lang, line=match["line"])
        rest = match["rest"]
    elif match := PART_ONLY.match(detail):
        location = t("abc.in_part", lang, part=t(f"abc.part.{match['part']}", lang))
        rest = match["rest"]
    problem = t("abc.unknown", lang)
    for pattern, key in PROBLEMS:
        if found := re.search(pattern, rest):
            problem = t(key, lang, **found.groupdict())
            break
    return capitalize(f"{location}: {problem}" if location else problem)


def capitalize(text):
    return text[:1].upper() + text[1:]


# Errors whose {detail} comes from the score tools and should be explained, not echoed.
SCORE_DETAIL = {"error.score_invalid", "error.convert_failed", "error.transcription_failed"}


def user_message(error, lang):
    """Localized text for a UserError."""
    params = dict(error.params)
    if error.key in SCORE_DETAIL and "detail" in params:
        params["detail"] = explain_abc(params["detail"], lang)
    return t(error.key, lang, **params)
