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
    "acoustic": "acoustic", "synthwave": "synthwave", "ambient": "ambient", "orchestral": "orchestral",
    "disco": "disco",
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
    "808": "808 bass", "organ": "organ", "nylon_guitar": "nylon-string guitar", "ukulele": "ukulele",
    "harp": "harp", "synth_pad": "ambient synth pad", "orchestra": "full orchestra",
}

VOCALS = {"female": "expressive female vocal", "male": "warm male vocal", "duet": "male and female duet"}

SECTION_TAGS = ("Intro", "Verse", "Pre-Chorus", "Chorus", "Bridge", "Outro")

LYRICS_TEMPLATE = "[Verse]\n\n\n[Chorus]\n\n"

# Quick starting points. Values are option ids; a preset without a vocal suits instrumentals.
PRESETS = {
    # Songs
    "piano_pop": dict(language="english", genres=["pop"], moods=["warm"], instruments=["piano", "bass", "drums"],
                      vocal="female", bpm=88),
    "kr_ballad": dict(language="korean", genres=["ballad"], moods=["melancholic"],
                      instruments=["piano", "strings", "bass"], vocal="male", bpm=72),
    "city_pop": dict(language="japanese", genres=["citypop"], moods=["nostalgic"],
                     instruments=["rhodes", "bass", "drums", "brass"], vocal="female", bpm=112),
    "kpop_dance": dict(language="korean", genres=["kpop", "edm"], moods=["energetic"],
                       instruments=["synth", "808", "drums"], vocal="duet", bpm=124),
    "rnb_groove": dict(language="english", genres=["rnb", "soul"], moods=["romantic"],
                       instruments=["rhodes", "bass", "drums"], vocal="female", bpm=90),
    "hiphop_beat": dict(language="english", genres=["hiphop"], moods=["dark"], instruments=["808", "synth", "drums"],
                        vocal="male", bpm=92),
    "rock_anthem": dict(language="english", genres=["rock"], moods=["epic"],
                        instruments=["electric_guitar", "bass", "drums"], vocal="male", bpm=140),
    "acoustic_folk": dict(language="english", genres=["folk", "acoustic"], moods=["warm"],
                          instruments=["acoustic_guitar", "ukulele", "bass"], vocal="female", bpm=100),
    "jazz_vocal": dict(language="english", genres=["jazz"], moods=["romantic"],
                       instruments=["piano", "bass", "drums", "saxophone"], vocal="female", bpm=118),
    "edm_festival": dict(language="english", genres=["edm"], moods=["uplifting"], instruments=["synth", "808", "drums"],
                         vocal="female", bpm=128),
    "jpop_anime": dict(language="japanese", genres=["jpop", "rock"], moods=["energetic"],
                       instruments=["electric_guitar", "synth", "drums"], vocal="female", bpm=150),
    "synthwave_night": dict(language="english", genres=["synthwave"], moods=["nostalgic"],
                            instruments=["synth", "bass", "drums"], vocal="male", bpm=108),
    "disco_funk": dict(language="english", genres=["disco", "funk"], moods=["playful"],
                       instruments=["electric_guitar", "bass", "strings", "drums"], vocal="duet", bpm=118),
    "country_road": dict(language="english", genres=["country"], moods=["warm"],
                         instruments=["acoustic_guitar", "violin", "bass", "drums"], vocal="male", bpm=96),
    # Instrumentals
    "lofi_study": dict(language="english", genres=["lofi"], moods=["chill"], instruments=["rhodes", "bass", "drums"],
                       vocal=None, bpm=78),
    "cafe_jazz": dict(language="english", genres=["jazz", "bossa"], moods=["warm"],
                      instruments=["piano", "bass", "saxophone"], vocal=None, bpm=96),
    "reading_piano": dict(language="english", genres=["classical"], moods=["gentle"], instruments=["piano"],
                          vocal=None, bpm=72),
    "cinematic": dict(language="english", genres=["cinematic"], moods=["epic"], instruments=["strings", "brass", "piano"],
                      vocal=None, bpm=90),
    "ambient_calm": dict(language="english", genres=["ambient"], moods=["dreamy"],
                         instruments=["synth_pad", "piano", "harp"], vocal=None, bpm=60),
    "epic_trailer": dict(language="english", genres=["orchestral", "cinematic"], moods=["epic"],
                         instruments=["orchestra", "brass", "drums"], vocal=None, bpm=120),
    "synthwave_drive": dict(language="english", genres=["synthwave"], moods=["nostalgic"],
                            instruments=["synth", "bass", "drums"], vocal=None, bpm=110),
    "acoustic_morning": dict(language="english", genres=["acoustic", "folk"], moods=["gentle"],
                             instruments=["acoustic_guitar", "ukulele"], vocal=None, bpm=96),
    "bossa_lounge": dict(language="english", genres=["bossa"], moods=["chill"],
                         instruments=["nylon_guitar", "bass", "flute"], vocal=None, bpm=100),
    "string_quartet": dict(language="english", genres=["classical"], moods=["romantic"],
                           instruments=["violin", "cello", "strings"], vocal=None, bpm=80),
}

# Which quick starts each screen offers (first entry is the screen's default).
PRESET_GROUPS = {
    "create": ["piano_pop", "kr_ballad", "city_pop", "kpop_dance", "rnb_groove", "hiphop_beat", "rock_anthem",
               "acoustic_folk", "jazz_vocal", "edm_festival", "jpop_anime", "country_road"],
    "restyle": ["rock_anthem", "jazz_vocal", "city_pop", "rnb_groove", "acoustic_folk", "edm_festival",
                "synthwave_night", "disco_funk", "kr_ballad", "country_road", "hiphop_beat", "piano_pop"],
    "instrumental": ["lofi_study", "cafe_jazz", "reading_piano", "cinematic", "ambient_calm", "epic_trailer",
                     "synthwave_drive", "acoustic_morning", "bossa_lounge", "string_quartet"],
    "cover": ["piano_pop", "acoustic_folk", "jazz_vocal", "rock_anthem", "synthwave_night", "kr_ballad",
              "lofi_study", "string_quartet", "bossa_lounge"],
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
            "vocals": VOCALS, "section_tags": list(SECTION_TAGS), "presets": PRESETS, "preset_groups": PRESET_GROUPS}
