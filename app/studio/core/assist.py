"""AI lyric completion through an OpenAI-compatible chat API (DeepSeek by default).

The assistant keeps every line the user wrote, fills what is missing, and — for a
cover — fits new lines to the melody's phrase lengths. Prompts live here so they
can be tuned with app/tools/lyrics_samples.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import re

from . import styles

BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"            # DeepSeek-V4.1-Flash

SECTION_TAG = re.compile(r"^\s*\[([^\]]+)\]\s*$")

SYSTEM_PROMPT = """You write song lyrics inside a songwriting app. A person is working on a song and asks you to finish the lyrics. A singing-voice model will sing exactly what you write, so every line must be words that can be sung.

OUTPUT FORMAT
- Output only the lyrics: no title, no commentary, no markdown, no quotation marks, no stage directions in parentheses.
- Put each section tag on its own line, in English: [Intro], [Verse], [Pre-Chorus], [Chorus], [Post-Chorus], [Bridge], [Outro]. Leave one blank line between sections.
- One line = one breath. Keep lines short enough to sing.
- Write numbers and times as words, the way they are sung (칠 번, seven thirty, 三時).

RESPECT WHAT THE PERSON WROTE
- Keep every line they already wrote exactly as written and in its place. Fill empty sections, continue where they stopped, and add only what the song still needs.
- Match their voice: vocabulary, tense, point of view, line length and rhyme habits.
- If they gave a title or a theme, the song is about that. Dramatize the theme; never restate its key phrase in a line.

SHAPE
- A full song is 20 to 28 sung lines, counting every repeated chorus. If the person already wrote a lot, add less.
- A usual pop shape is verse, pre-chorus, chorus, verse, pre-chorus, chorus, bridge, chorus, with 4-line verses and choruses; if there is a pre-chorus, it comes before both verse-led choruses (the second may change a line). The genre changes the shape and the energy:
  hip-hop: two 8-line verses in talking cadence with internal and multi-syllable rhymes, no pre-chorus, a 4-line hook;
  K-pop and EDM: a short post-chorus chant after every chorus, built on one repeated word or English phrase, and a bridge that builds tension for the last drop;
  rock and J-rock: forward motion and lift, the chorus as the energy peak;
  country: plain talk, and the title turns into wordplay by the last chorus;
  jazz: conversational wit and one clever turn of phrase;
  ballad: restraint; the hardest feeling stays unsaid until the end.
  An upbeat or energetic style needs a song that moves forward, not only melancholy, and mood words in the style (warm, uplifting, dark) should be felt somewhere in the words.
- Verse 1 lets the listener know early why this moment matters. Verse 2 stays in the same story and setting, takes it one step further, and mirrors verse 1's line lengths and rhyme pattern so it fits the same melody.
- The chorus is built on one hook line (the title, if there is one), sung at least twice. Its other lines add a concrete picture or a consequence, never generic feeling.
- The bridge is the turn: an admission, a decision, or something the song has not shown yet. The last chorus then changes one or two lines to answer the bridge; the earlier choruses repeat word for word.

CRAFT
- Show the feeling through one moment: someone does or says something in a specific place and time. Things people say out loud are often the strongest lines. One concrete detail every couple of lines is plenty, and every detail belongs to the same scene. Skip the first prop that comes to mind for the theme and look for a less obvious one.
- One speaker, one situation. Keep it clear who is speaking and who "you" is. Anything the song refers to (a message that was sent, a promise, who "we" are, a lie the chorus hints at) is set up before or when it is used.
- Rhyme where it lands naturally: at least one clear rhyme pair in each verse and chorus (slant rhyme is fine; Mandarin keeps one rhyme sound per section; in Korean and Japanese, echoing sounds or endings can stand in for end rhyme). Never invert word order to rhyme, and never rhyme a word with itself. A plain line without a rhyme is better than a forced one.
- Use the plain, natural wording a native speaker would actually say, and avoid lines that recall well-known songs. If a line could sit in a thousand other songs, replace it (for example: neon lights, shattered, echoes, rise above, dancing in the rain, let it go; 운명, 영원히, 별빛, 눈부신, 어느새; 運命, 永遠, 輝く未来).
- Outside the chorus, do not lean on the same key word more than two or three times.
- Korean: spoken line endings (-어, -지, -는데, -잖아), never the dictionary form -다, one speech level throughout, and consistent honorifics for anyone else (알아보시네 … 놓으시네). Japanese: natural spoken grammar and common word pairings. Mandarin: about 7 to 10 characters per line in a ballad, paired lines within one character.

BEFORE YOU ANSWER
Read the draft once as a listener who hears it only once, and fix what trips them:
- Every line is a complete, grammatical thought that makes literal sense; hook lines above all must be clear the first time they are heard: who does what, to what (no missing subject or object, no dangling phrase).
- No word can be heard two ways: a word just used in another sense, an idiom or slang meaning that jumps out, or wording that suggests something darker than meant (death, reckless danger).
- The scene and the story hold together: where people are, what they hold, the time, the weather and every fact the song states (whether someone came, a usual hour, who said what) never contradict each other (someone in a car is not running; money is kept in one place; a thing in a pocket makes the pocket warm).
- No word is there only because it rhymes or fills the meter; if you would not say it without the rhyme, rewrite the line."""

FIT_RULES = """MELODY FIT
The music already exists. Write exactly the sections listed in the message, in that order; the counts replace the SHAPE rules. Each number is one sung line and how many syllables it should have (one syllable per note; count Korean by Hangul syllables, Japanese by morae, Mandarin by characters). Stay within one syllable of each number. A section marked "instrumental" gets its tag and no lines.
Hit each count with meaningful words: every line is a clause or a clear phrase, the speaker is doing something, and each section reads as one thought, in one tense and one place. It stays clear who does what; avoid lines that can be heard two ways. Never pad with filler words or names (friend, baby, oh, yeah, tonight, there). Still rhyme where it comes naturally. Give the chorus a short phrase that repeats; the shortest or the last line is a good home for it. In English, do not end a line on a weak word (the, a, of, and). In Korean, keep the particles (은/는/이/가/을/를/에): when a count is tight, choose shorter words instead of dropping particles."""


@dataclass
class LyricsRequest:
    style: str = ""
    title: str = ""
    theme: str = ""
    lyrics: str = ""
    melody: list = field(default_factory=list)   # scores.melody_outline() for a cover
    ui_lang: str = "en"


def script_of(text):
    """Korean, Japanese or Mandarin when the text is written in that script; None for Latin or empty."""
    if re.search(r"[가-힣]", text):
        return "Korean"
    if re.search(r"[぀-ヿ]", text):
        return "Japanese"
    if re.search(r"[一-鿿]", text):
        return "Mandarin"
    return None


def language_of(request):
    """The language to write in: the script of lines already written, else the style's language, else the brief."""
    words = "\n".join(line for line in (request.lyrics or "").splitlines() if not SECTION_TAG.match(line))
    written = script_of(words)
    style = (request.style or "").lower()
    first = style.split(",")[0].strip()
    stated = next((phrase for phrase in styles.LANGUAGES.values()
                   if phrase.lower() == first or re.search(rf"\b{re.escape(phrase.lower())}\b", style)), None)
    # The person's own lines win over a style left on its default (Han script also covers Cantonese).
    if written and not (stated == written or (written == "Mandarin" and stated == "Cantonese")):
        return written
    if stated:
        return stated
    return script_of(request.title + request.theme) or {"ko": "Korean", "ja": "Japanese"}.get(request.ui_lang, "English")


def has_words(lyrics):
    return any(line.strip() and not SECTION_TAG.match(line) for line in (lyrics or "").splitlines())


def build_messages(request):
    language = language_of(request)
    system = SYSTEM_PROMPT + ("\n\n" + FIT_RULES if request.melody else "")
    parts = [f"Language: write the lyrics in {language}.", f"Style: {request.style or 'not specified'}"]
    if request.title.strip():
        parts.append(f"Title: {request.title.strip()}")
    if request.theme.strip():
        parts.append(f"What the song is about: {request.theme.strip()}")
    if request.melody:
        lines = []
        for section in request.melody:
            tag = "[" + section["label"].title() + "]"
            lines.append(f"{tag} " + (", ".join(str(n) for n in section["phrases"]) if section["phrases"] else "instrumental"))
        parts.append("Melody (syllables per line, by section):\n" + "\n".join(lines))
    if has_words(request.lyrics):
        parts.append("Lyrics so far (keep these lines exactly):\n<<<\n" + request.lyrics.strip() + "\n>>>")
        parts.append("Finish the lyrics.")
    elif (request.lyrics or "").strip():
        parts.append("Section plan so far (fill it in):\n<<<\n" + request.lyrics.strip() + "\n>>>")
        parts.append("Write the lyrics.")
    else:
        parts.append("Write the lyrics.")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]


def clean(text):
    """Strip wrappers a model sometimes adds (code fences, a leading title line, <<< >>> markers)."""
    text = re.sub(r"^```\w*\n|```$", "", text.strip()).strip()
    text = text.replace("<<<", "").replace(">>>", "").replace("’", "'").replace("‘", "'").strip()
    lines = text.splitlines()
    if lines and re.match(r"^(title|제목|タイトル)\s*[:：]", lines[0].strip(), re.I):
        lines.pop(0)
    # "[Verse 2]" → "[Verse]": the singing model knows plain section names.
    lines = [re.sub(r"^\s*\[([A-Za-z-]+)\s*\d+\]\s*$", r"[\1]", line) for line in lines]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


class LyricsAssistant:
    def __init__(self, api_key=None, base_url=None, model=None, thinking=True, effort=None):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.environ.get("YUE2_STUDIO_ASSIST_BASE_URL", BASE_URL)
        self.model = model or os.environ.get("YUE2_STUDIO_ASSIST_MODEL", MODEL)
        self.thinking = thinking
        self.effort = effort or os.environ.get("YUE2_STUDIO_ASSIST_EFFORT", "low")
        self._client = None

    @property
    def available(self):
        return bool(self.api_key)

    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=120)
        return self._client

    def _options(self):
        options = {"extra_body": {"thinking": {"type": "enabled" if self.thinking else "disabled"}}}
        if self.thinking:
            options["reasoning_effort"] = self.effort
        else:
            options["temperature"] = 0.9
        return options

    def stream(self, request):
        """Yield the lyrics written so far (the answer only; reasoning is not shown)."""
        response = self.client().chat.completions.create(
            model=self.model, messages=build_messages(request), stream=True, **self._options())
        text = ""
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                text += delta.content
                yield text
        yield clean(text)

    def complete(self, request):
        result = ""
        for result in self.stream(request):
            pass
        return result


def count_syllables(line, language="English"):
    """Rough sung-syllable count for checking melody fit."""
    line = line.strip()
    if language == "Korean":
        return len(re.findall(r"[가-힣]", line))
    if language == "Japanese":
        kana = re.findall(r"[ぁ-ゖァ-ヺー]", line)
        small = re.findall(r"[ゃゅょぁぃぅぇぉャュョァィゥェォ]", line)
        kanji = re.findall(r"[一-鿿]", line)
        return len(kana) - len(small) + 2 * len(kanji)
    if language in ("Mandarin", "Cantonese"):
        return len(re.findall(r"[一-鿿]", line))
    count = 0
    for word in re.findall(r"[A-Za-z']+", line.lower()):
        groups = re.findall(r"[aeiouy]+", word)
        n = len(groups)
        if word.endswith("e") and not word.endswith(("le", "ee", "ye")) and n > 1:
            n -= 1
        count += max(n, 1)
    return count
