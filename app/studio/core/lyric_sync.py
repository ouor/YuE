"""Original lyrics for a cover: time the transcribed score, hear it phrase group by phrase group,
and put the recognized words on the score's lines under its section tags.

SheetSage2 writes the beat grid its ABC was built on (notation/song_beats.txt), so every note
of the score has a time in the clip. Speech recognition runs on stretches of at most
MAX_SEGMENT seconds cut at rests between phrases (whole songs make the aligner drift), and
each word goes to the phrase it is sung in. The result is a draft for people to correct.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from fractions import Fraction
import re
import unicodedata

from . import scores, styles
from .assist import count_syllables, has_words, script_of  # noqa: F401  (workflows use lyric_sync.has_words)
from .jobs import UserError

BEATS = "notation/song_beats.txt"
MAX_SEGMENT = 20.0          # seconds per recognition window
MAX_GAP = 4.0               # a longer instrumental gap starts a new window
PAD = (0.3, 0.4)            # audio kept before/after a window's first and last note
LINE_NOTES = 12             # neighbouring phrases join into one lyric line up to this many notes
LINE_GAP = 1.0              # ... when sung less than this many seconds apart
# Qwen3-ASR names; Mandarin is "Chinese" there.
ASR_LANGUAGES = {"English": "English", "Korean": "Korean", "Japanese": "Japanese", "Mandarin": "Chinese",
                 "Cantonese": "Cantonese"}
UNSPACED = {"Japanese", "Chinese", "Cantonese"}
_NAMES = {**{name.lower(): asr for name, asr in ASR_LANGUAGES.items()},
          **{asr.lower(): asr for asr in ASR_LANGUAGES.values()},
          **{key: ASR_LANGUAGES[phrase] for key, phrase in styles.LANGUAGES.items()}}
EDGE_PUNCTUATION = " \t,.;:!?、。，．；：！？…「」『』\"'“”‘’()（）-—~〜"


def asr_language(value):
    """'auto' or empty → None (detect); a style key ('japanese') or name ('Mandarin') → the Qwen3-ASR name."""
    if not value or str(value).strip().lower() == "auto":
        return None
    name = _NAMES.get(str(value).strip().lower())
    if name is None:
        raise UserError("error.bad_language")
    return name


def read_beats(path):
    """Rows of (seconds, beat in bar, beats per bar, beat unit) from a SheetSage2 beat file."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 4:
            rows.append((float(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])))
    return rows


def score_clock(abc, beats):
    """A function from score time (quarter notes) to seconds in the transcribed clip.

    ABC bars follow SheetSage2's measures: a lead-in before the first downbeat, one bar per
    downbeat span, then a closing partial bar. A lead-in bar is padded with rests at its start.
    Falls back to the score tempo from the first beat when the bars do not line up.
    """
    score = scores.parse(scores.native_sections(abc))
    bars = score.voices["Vocal"].bars
    downbeats = [i for i, row in enumerate(beats) if row[1] == 1]
    spans = []
    if downbeats:
        if downbeats[0] > 0:
            spans.append((0, downbeats[0], True))
        spans += [(a, b, False) for a, b in zip(downbeats, downbeats[1:])]
        if downbeats[-1] < len(beats) - 1:
            spans.append((downbeats[-1], len(beats) - 1, False))
    first = beats[0][0] if beats else 0.0
    seconds_per_quarter = 60.0 / score.bpm

    if len(spans) != len(bars):
        return lambda q: first + float(q) * seconds_per_quarter

    bar_starts = [start for start, _, _ in bars]
    last_period = beats[-1][0] - beats[-2][0] if len(beats) > 1 else seconds_per_quarter

    def clock(q):
        k = max(bisect_right(bar_starts, q) - 1, 0)
        bar_start, length, _ = bars[k]
        a, b, lead_in = spans[k]
        count = b - a
        per_beat = 4.0 / beats[a][3]                 # quarters per beat
        padding = float(length) - count * per_beat
        position = (float(q - bar_start) - (padding if lead_in else 0.0)) / per_beat
        if position >= count and k == len(bars) - 1:
            return beats[b][0] + (position - count) * last_period
        position = min(max(position, 0.0), count)
        index = min(int(position), count - 1)
        t0, t1 = beats[a + index][0], beats[a + index + 1][0]
        return t0 + (position - index) * (t1 - t0)

    return clock


@dataclass
class Line:
    start: float
    end: float
    notes: int
    words: list = field(default_factory=list)
    beats: tuple = (0, 0)        # (start, end) in score quarter notes


@dataclass
class Section:
    label: str
    lines: list


@dataclass
class Window:
    start: float
    end: float
    lines: list                  # Line objects sung inside this window


def sung_lines(abc, beats):
    """Score sections with each phrase timed in seconds; implicit leading vocals join the first section."""
    clock = score_clock(abc, beats)
    phrased = scores.melody_phrases(abc)
    sections = [Section(s["label"], [Line(clock(a), clock(b), n, beats=(a, b)) for a, b, n in s["phrases"]])
                for s in phrased]
    if phrased[0]["implicit"]:
        lead = sections.pop(0)
        if sections:
            sections[0].lines[:0] = lead.lines
        else:
            sections = [lead]
    # A phrase that starts mid-bar just before a section and runs into it without a rest is
    # that section's pickup ("Come home before | the morning train").
    bars = scores.parse(scores.native_sections(abc)).voices["Vocal"].bars
    bar_starts = {start for start, _, _ in bars}
    longest_bar = max((length for _, length, _ in bars), default=Fraction(4))
    for current, following in zip(sections, sections[1:]):
        if len(current.lines) < 2 or not following.lines:
            continue
        last, first = current.lines[-1], following.lines[0]
        if (first.beats[0] - last.beats[1] < Fraction(1, 2) and last.beats[0] not in bar_starts
                and first.beats[0] - last.beats[0] <= longest_bar):
            following.lines.insert(0, current.lines.pop())
    return sections


def windows(sections, duration=None):
    """Group consecutive lines into recognition windows cut at rests."""
    lines = [line for section in sections for line in section.lines]
    groups = []
    for line in lines:
        if groups and line.end - groups[-1][0].start <= MAX_SEGMENT and line.start - groups[-1][-1].end <= MAX_GAP:
            groups[-1].append(line)
        else:
            groups.append([line])
    result = []
    for index, group in enumerate(groups):
        # Padding stops at the neighbouring windows' notes so no word is heard twice.
        before = groups[index - 1][-1].end if index else 0.0
        after = groups[index + 1][0].start if index + 1 < len(groups) else float("inf")
        start = max(group[0].start - PAD[0], before, 0.0)
        end = min(group[-1].end + PAD[1], after, duration if duration is not None else float("inf"))
        if end - start >= 0.5:                       # nothing to hear past the end of the clip
            result.append(Window(start, end, group))
    return result


def _kept(ch):
    return ch == "'" or unicodedata.category(ch)[0] in "LN"


def units(text, tokens, language):
    """Split the recognized text into placeable pieces, one per aligned token (or spaced word).

    Each piece keeps the original spelling, spacing and punctuation that follow it, so joining
    pieces gives back the text. tokens: [(token, start, end)] from the aligner, in order.
    Returns [(piece, start, end)].
    """
    spans, cursor = [], 0
    for token, start, end in tokens:
        pattern = r"[^\w']*".join(re.escape(ch) for ch in token)
        match = re.compile(pattern, re.I).search(text, cursor) if token else None
        if match is None:
            continue
        spans.append([match.start(), match.end(), start, end])
        cursor = match.end()
    if not spans:
        return []
    spans[0][0] = 0
    for current, following in zip(spans, spans[1:]):
        current[1] = following[0]
    spans[-1][1] = len(text)
    # In spaced languages, tokens inside one word (Korean particles) move together.
    if language not in UNSPACED:
        merged = []
        for span in spans:
            if merged and not re.search(r"\s", text[merged[-1][0]:span[0]]):
                merged[-1] = [merged[-1][0], span[1], merged[-1][2], span[3]]
            else:
                merged.append(span)
        spans = merged
    return [(text[a:b], start, end) for a, b, start, end in spans]


def timings_usable(pieces, window):
    """The aligner sometimes returns zeros or piles everything at one instant on music."""
    if not pieces:
        return False
    timed = [p for p in pieces if p[2] > p[1]]
    spread = max(p[2] for p in pieces) - min(p[1] for p in pieces)
    return len(timed) >= 0.3 * len(pieces) and spread >= 0.4 * (window.end - window.start)


BREAK = re.compile(r"[,.;:!?、。，．；：！？…]\s*$")
PARTICLE = re.compile(r"[ぁ-ゖー]{1,2}")


def syllables(piece, language):
    return max(count_syllables(piece, "Mandarin" if language == "Chinese" else language), 1)


def place(pieces, lines, language, timed):
    """Split pieces, in order, into one run per line (dynamic programming over break points).

    A run costs how far its syllables are from the line's note count (scaled by the window's
    syllables-per-note, which absorbs melismas), how far its words are sung outside the line's
    time span when timings are usable, and a break that falls mid-sentence.
    """
    n, m = len(pieces), len(lines)
    counts = [syllables(piece, language) for piece, _, _ in pieces]
    ratio = sum(counts) / (sum(line.notes for line in lines) or 1)
    prefix = [0]
    for count in counts:
        prefix.append(prefix[-1] + count)
    mid_break = 0.8 if language in UNSPACED else 0.3

    def outside(i, line):
        start, end = pieces[i][1], pieces[i][2]
        middle = (start + end) / 2
        return 0.0 if line.start <= middle <= line.end else min(abs(middle - line.start), abs(middle - line.end))

    def cost(j, a, b):                      # pieces a..b-1 on line j
        target = max(lines[j].notes * ratio, 1.0)
        value = abs(prefix[b] - prefix[a] - target) / target
        if timed:
            value += 0.4 * sum(outside(i, lines[j]) for i in range(a, b))
        if 0 < b < n and not BREAK.search(pieces[b - 1][0]):
            value += mid_break
            # A Japanese line never starts with a particle or verb ending (て, に, を, よ ...).
            if language == "Japanese" and PARTICLE.fullmatch(pieces[b][0].strip(EDGE_PUNCTUATION)):
                value += mid_break
        return value

    INF = float("inf")
    best = [[INF] * (n + 1) for _ in range(m + 1)]
    back = [[0] * (n + 1) for _ in range(m + 1)]
    best[0][0] = 0.0
    for j in range(1, m + 1):
        for b in range(n + 1):
            for a in range(b + 1):
                if best[j - 1][a] < INF:
                    value = best[j - 1][a] + cost(j - 1, a, b)
                    if value < best[j][b]:
                        best[j][b], back[j][b] = value, a
    b = n
    for j in range(m, 0, -1):
        a = back[j][b]
        lines[j - 1].words.extend(piece for piece, _, _ in pieces[a:b])
        b = a


def fill_window(window, text, tokens, language):
    """Put one window's recognized text on its lines. tokens are clip-relative to the window."""
    tokens = [(token, start + window.start, end + window.start) for token, start, end in tokens]
    pieces = units(text, tokens, language)
    if not pieces and text.strip():
        pieces = [(word + " ", 0.0, 0.0) for word in text.split()] if language not in UNSPACED             else [(part, 0.0, 0.0) for part in re.findall(r"[^、。，．！？,.!?]+[、。，．！？,.!?]*", text)]
    if pieces:
        place(pieces, window.lines, language, timings_usable(pieces, window))


def line_text(words, language=""):
    text = "".join(words)
    if language in UNSPACED:
        text = re.sub(r"[、。，．！？]+", " ", text)     # sentence marks inside a sung line read as pauses
    return re.sub(r"\s+", " ", text).strip(EDGE_PUNCTUATION)


SENTENCE_END = re.compile(r"[.?!。？！…]\s*$")


def lyric_lines(lines, language=""):
    """Join short phrases sung back to back into one line, unless a sentence ends between them."""
    result, previous = [], None
    for line in lines:
        text = "".join(line.words)
        if not line_text([text], language):
            continue
        joins = (previous is not None and previous["notes"] + line.notes <= LINE_NOTES
                 and line.start - previous["end"] <= LINE_GAP and not SENTENCE_END.search(previous["text"]))
        if joins:
            previous.update(text=previous["text"] + text, notes=previous["notes"] + line.notes, end=line.end)
            continue
        previous = {"text": text, "notes": line.notes, "end": line.end}
        result.append(previous)
    return [line_text([item["text"]], language) for item in result]


def format_lyrics(sections, language=""):
    """[Section] tags in score order, each followed by its sung lines."""
    blocks = ["\n".join(["[" + section.label.title() + "]"] + lyric_lines(section.lines, language))
              for section in sections]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def language_from(text, detected=""):
    """Decide the song language from what the recognizer wrote (its own label is unreliable on songs)."""
    written = script_of(text)
    if written == "Mandarin":
        return "Chinese"
    if written:
        return written
    first = (detected or "").split(",")[0].strip()
    return first if first and first not in UNSPACED | {"Korean"} else "English"


def densest(windows_):
    """The window with the most sung notes: the best sample for telling the language."""
    return max(windows_, key=lambda window: sum(line.notes for line in window.lines))


def extract(recognize, audio, abc, beats, *, language=None, sample_rate=16000, check=lambda: None):
    """Recognize and place the original lyrics.

    recognize(clips, language, timestamps) -> [(detected language, text, [(token, start, end)])]
    audio: mono float waveform at sample_rate. language: a Qwen3-ASR name or None to detect.
    Returns {"lyrics", "language", "windows": [{"start", "end", "text"}]}.
    """
    sections = sung_lines(abc, beats)
    duration = len(audio) / sample_rate
    parts = windows(sections, duration)
    if not parts:
        return {"lyrics": "", "language": language, "windows": []}

    def clip(window):
        return audio[int(window.start * sample_rate):int(window.end * sample_rate)]

    if not language:
        sample = densest(parts)
        detected, text, _ = recognize([clip(sample)], None, False)[0]
        language = language_from(text, detected)
        check()
    results = recognize([clip(window) for window in parts], language, True)
    record = []
    for window, (_, text, tokens) in zip(parts, results):
        fill_window(window, text, tokens, language)
        record.append({"start": round(window.start, 2), "end": round(window.end, 2), "text": text})
    return {"lyrics": format_lyrics(sections, language), "language": language, "windows": record}
