"""Style builder data: each option id maps to the English phrase sent to YuE2.

UI labels come from the translation table (key: "<group>.<id>"); edit these
dictionaries to add options without touching the UI.
"""
from __future__ import annotations

LANGUAGES = {"english": "English", "korean": "Korean", "japanese": "Japanese", "mandarin": "Mandarin",
             "cantonese": "Cantonese"}

GENRES = {
    "pop": "pop", "ballad": "ballad", "rnb": "R&B", "hiphop": "hip-hop", "rock": "rock", "indie": "indie",
    "jazz": "jazz", "funk": "funk", "soul": "soul", "edm": "EDM", "lofi": "lo-fi", "folk": "folk",
    "country": "country", "citypop": "city pop", "kpop": "K-pop", "jpop": "J-pop", "cinematic": "cinematic",
    "classical": "classical crossover", "bossa": "bossa nova", "reggae": "reggae", "metal": "metal",
    "acoustic": "acoustic",
}

MOODS = {
    "warm": "warm", "uplifting": "uplifting", "melancholic": "melancholic", "energetic": "energetic",
    "dreamy": "dreamy", "romantic": "romantic", "nostalgic": "nostalgic", "dark": "dark", "chill": "chill",
    "epic": "epic", "playful": "playful", "gentle": "gentle",
}

INSTRUMENTS = {
    "piano": "acoustic piano", "acoustic_guitar": "acoustic guitar", "electric_guitar": "electric guitar",
    "bass": "bass", "drums": "drums", "strings": "strings", "synth": "synth", "rhodes": "Rhodes",
    "saxophone": "saxophone", "brass": "brass section", "violin": "violin", "cello": "cello", "flute": "flute",
    "808": "808 bass", "organ": "organ",
}

VOCALS = {"female": "expressive female vocal", "male": "warm male vocal", "duet": "male and female duet"}

SECTION_TAGS = ("Intro", "Verse", "Pre-Chorus", "Chorus", "Bridge", "Outro")

LYRICS_TEMPLATE = "[Verse]\n\n\n[Chorus]\n\n"

# Quick starting points shown as examples. Values are option ids.
PRESETS = {
    "piano_pop": dict(language="english", genres=["pop"], moods=["warm"], instruments=["piano", "bass", "drums"],
                      vocal="female", bpm=88),
    "city_pop": dict(language="japanese", genres=["citypop"], moods=["nostalgic"],
                     instruments=["rhodes", "bass", "drums", "brass"], vocal="female", bpm=112),
    "kpop_dance": dict(language="korean", genres=["kpop", "edm"], moods=["energetic"],
                       instruments=["synth", "808", "drums"], vocal="duet", bpm=124),
    "rock_anthem": dict(language="english", genres=["rock"], moods=["epic"],
                        instruments=["electric_guitar", "bass", "drums"], vocal="male", bpm=140),
    "lofi_study": dict(language="english", genres=["lofi"], moods=["chill"], instruments=["rhodes", "bass", "drums"],
                       vocal=None, bpm=78),
    "cafe_jazz": dict(language="english", genres=["jazz", "bossa"], moods=["warm"],
                      instruments=["piano", "bass", "saxophone"], vocal=None, bpm=96),
    "cinematic": dict(language="english", genres=["cinematic"], moods=["epic"], instruments=["strings", "brass", "piano"],
                      vocal=None, bpm=90),
    "reading_piano": dict(language="english", genres=["classical"], moods=["gentle"], instruments=["piano"],
                          vocal=None, bpm=72),
}


def _pick(table, ids):
    return [table[i] for i in ids or [] if i in table]


def compose_style(language=None, genres=(), moods=(), instruments=(), vocal=None, bpm=None, extra="",
                  instrumental=False):
    """Build a YuE2 style prompt, e.g. 'English, warm pop, expressive female vocal, acoustic piano, 88 BPM'."""
    parts = []
    if language in LANGUAGES and not instrumental:
        parts.append(LANGUAGES[language])
    sound = " ".join(_pick(MOODS, moods) + _pick(GENRES, genres))
    if sound:
        parts.append(sound)
    if vocal in VOCALS and not instrumental:
        parts.append(VOCALS[vocal])
    parts.extend(_pick(INSTRUMENTS, instruments))
    if extra and extra.strip():
        parts.append(extra.strip().rstrip(".,"))
    if bpm:
        parts.append(f"{int(bpm)} BPM")
    return ", ".join(parts)


def options():
    return {"languages": LANGUAGES, "genres": GENRES, "moods": MOODS, "instruments": INSTRUMENTS,
            "vocals": VOCALS, "section_tags": list(SECTION_TAGS), "presets": PRESETS}
