"""ABC score helpers, reusing the yue2-music skill's verified tools."""
from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
import importlib
import re
import sys

from ..config import Settings

HEADER = re.compile(r"^(?:[A-Z]:|V:|%)")
CHORD_SYMBOL = re.compile(r'"[^"\n]*"')


@lru_cache(maxsize=1)
def tools():
    """Import the skill helpers (standard-library only) from skills/yue2-music."""
    path = str(Settings().skill_scripts)
    if path not in sys.path:
        sys.path.insert(0, path)
    return {name: importlib.import_module(name) for name in ("abc_tools", "instrumentalize", "instrumental")}


def parse(text):
    return tools()["abc_tools"].parse_abc(text)


def _header(text, field):
    match = re.search(rf"^{field}:(.*)$", text, re.M)
    return match.group(1).strip() if match else None


def sections(text):
    return [line[2:].strip() for line in text.splitlines() if line.startswith("% ")]


def has_chords(text):
    return any(CHORD_SYMBOL.search(line) for line in text.splitlines() if not HEADER.match(line))


def inspect(text):
    """Summarize a score for the UI; never raises for malformed input."""
    text = text or ""
    info = {"ok": False, "error": None, "bpm": None, "key": _header(text, "K"), "meter": _header(text, "M"),
            "has_chords": has_chords(text), "sections": sections(text), "vocal_notes": 0, "ins_notes": 0,
            "measures": 0, "seconds": None}
    if not text.strip():
        info["error"] = "empty"
        return info
    try:
        score = parse(text)
    except ValueError as exc:
        info["error"] = str(exc)
        return info
    vocal, ins = score.voices["Vocal"], score.voices["Ins"]
    info.update(ok=True, bpm=score.bpm, vocal_notes=len(vocal.notes), ins_notes=len(ins.notes),
                measures=len(vocal.bars), seconds=round(float(vocal.time * 60 / score.bpm), 1),
                has_chords=bool(vocal.chords))
    return info


def mode_for(text):
    """Chord symbols need the full planner mode; chord-free scores use melody mode."""
    return "full" if has_chords(text) else "melody"


def melody_only(text):
    """Remove chord symbols so the accompaniment can follow a new style."""
    try:
        return tools()["abc_tools"].strip_chords(text)
    except ValueError:
        # Fall back to a textual strip for scores outside the checked dialect.
        return "\n".join(line if HEADER.match(line) else CHORD_SYMBOL.sub("", line)
                         for line in text.splitlines()) + ("\n" if text.endswith("\n") else "")


def native_sections(text):
    """Drop section comments outside the native set (e.g. SheetSage2's '% silence').

    Only comment lines change; notes, bars and voices are untouched. A dropped
    label folds its bars into the previous section, so repeated labels merge.
    """
    known = importlib.import_module("compile_score").SECTIONS if tools() else set()
    lines, previous = [], None
    for line in text.splitlines():
        if line.startswith("% "):
            label = line[2:].strip()
            if label not in known or label == previous:
                continue
            previous = label
        lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


INLINE_KEY = re.compile(r"\[K:[^\]\n]+\]")
ONLY_RESTS = re.compile(r'^(?:z\d*|Z\d?|"[^"\n]*"|\s)*$')


def settle_key_changes(text):
    """Move inline key changes that only precede rests to the next bar start.

    Transcriptions sometimes change key mid-bar inside a rest; the converter
    requires key changes on bar lines. With no notes after the change in its
    bar, moving (or, at the very end, dropping) it cannot alter any pitch —
    and the result is verified note-for-note before it is used.
    """
    lines = text.splitlines()
    pending, voice = {}, None
    meter, unit = _header(text, "M") or "4/4", _header(text, "L") or "1/8"
    try:
        (n, d), (_, u) = map(int, meter.split("/")), map(int, unit.split("/"))
        full_bar = f"z{n * u // d}"
    except ValueError:
        return text

    def prefix(key, bar):
        # 'Z' (whole-bar rests) cannot carry an inline field; spell the first bar out.
        rest = re.fullmatch(r"Z([2-4])?", bar.strip())
        if rest:
            return "|".join([key + full_bar] + ["Z"] * (int(rest.group(1) or 1) - 1))
        return key + bar

    for index, line in enumerate(lines):
        if line.startswith("V:"):
            voice = line[2:].strip().split()[0]
            continue
        if HEADER.match(line) or not line.endswith("|") or voice is None:
            continue
        bars = line[:-1].split("|")
        if voice in pending:
            bars[0] = prefix(pending.pop(voice), bars[0])
        for i, bar in enumerate(bars):
            match = INLINE_KEY.search(bar)
            if not match or match.start() == 0 or not ONLY_RESTS.match(bar[match.end():]):
                continue
            bars[i] = bar[:match.start()] + bar[match.end():]
            if i + 1 < len(bars):
                bars[i + 1] = prefix(match.group(0), bars[i + 1])
            else:
                pending[voice] = match.group(0)
        lines[index] = "|".join(bars) + "|"
    result = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    try:
        before, after = parse(text), parse(result)
    except ValueError:
        return text
    same = all(before.voices[v].notes == after.voices[v].notes for v in ("Vocal", "Ins"))
    return result if same else text


def to_instrumental(text, keep_chords=True):
    """Move every Vocal note to Ins; returns (score, transfer report)."""
    text = settle_key_changes(native_sections(text))
    return tools()["instrumentalize"].convert_score(text, overlap="vocal", keep_chords=keep_chords)


def melody_outline(text, rest_gap=Fraction(1, 2), held=Fraction(1), longest=14, shortest=4):
    """The sung shape of a score: one entry per section, with the note count of each phrase.

    A phrase ends at a rest of at least `rest_gap` quarter notes, or after a note held for
    `held` quarters once the phrase has a few notes; phrases longer than `longest` notes are
    split at bar lines. Each note is roughly one sung syllable, which is what lyric writing
    needs: [{"label": "verse", "phrases": [8, 7]}]. Sections without vocal notes come back
    with no phrases (instrumental passages).
    """
    text = settle_key_changes(native_sections(text))
    score = parse(text)
    vocal = score.voices["Vocal"]
    bar_starts = {start for start, _, _ in vocal.bars}
    starts = sorted(tools()["instrumentalize"].section_starts(text, score).items())
    sections = [{"label": label, "start": start, "phrases": []} for start, label in starts]
    if not sections or sections[0]["start"] > 0:
        sections.insert(0, {"label": "verse", "start": Fraction(0), "phrases": []})
    previous = None                      # (section index, end time, duration) of the last note
    for start, _pitch, duration in vocal.notes:
        index = max(i for i, section in enumerate(sections) if section["start"] <= start)
        phrases = sections[index]["phrases"]
        new_phrase = (previous is None or index != previous[0] or start - previous[1] >= rest_gap
                      or (previous[2] >= held and phrases and phrases[-1] >= 4)
                      or (start in bar_starts and phrases and phrases[-1] >= longest))
        if new_phrase or not phrases:
            phrases.append(0)
        phrases[-1] += 1
        previous = (index, start + duration, duration)
    # A couple of notes before a section (a pickup) belong to the next section's first line.
    for current, following in zip(sections, sections[1:]):
        if 0 < sum(current["phrases"]) < 4:
            if following["phrases"]:
                following["phrases"][0] += sum(current["phrases"])
            current["phrases"] = []
    for section in sections:
        section["phrases"] = _merge_short(section["phrases"], shortest)
    return [{"label": s["label"], "phrases": s["phrases"]} for s in sections]


def _merge_short(phrases, shortest):
    """Fold fragments (a held note splitting a line) into a neighbouring phrase."""
    merged = []
    for count in phrases:
        if merged and (count < shortest or merged[-1] < shortest):
            merged[-1] += count
        else:
            merged.append(count)
    return merged


def lyric_template(text):
    """Section tags in score order, e.g. '[Verse]\\n\\n[Chorus]\\n'."""
    return tools()["instrumental"].lyric_tags(native_sections(text))


def instrumental_style(style):
    """Mirror the skill's instrumental prompt conventions."""
    style = (style or "").strip().rstrip(".,") or "Expressive instrumental music"
    if not re.match(r"^instrumental\b", style, re.I):
        style = "Instrumental, " + style
    for condition in ("no vocals", "no singing", "no choir", "no spoken words"):
        if condition not in style.lower():
            style += ", " + condition
    return style + "."


def compare(before, after):
    """Describe what an edit changed; exact symbolic comparison when both scores parse."""
    result = {"checked": False, "differences": [], "melody_preserved": None,
              "tempo": [_header(before, "Q"), _header(after, "Q")], "key": [_header(before, "K"), _header(after, "K")],
              "chords_changed": None}
    try:
        a, b = parse(before), parse(after)
    except ValueError as exc:
        result["error"] = str(exc)
        return result
    report = tools()["abc_tools"].compare(a, b, allow_tempo_change=True)
    result.update(checked=True, differences=report["differences"],
                  melody_preserved=not any("sounding notes" in d for d in report["differences"]),
                  chords_changed=a.voices["Vocal"].chords != b.voices["Vocal"].chords)
    return result
