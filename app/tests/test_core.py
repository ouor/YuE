"""Core tests with a fake engine: no GPU, no model downloads."""
from contextlib import contextmanager
import threading
import zipfile

import numpy as np
import pytest
from yue2 import SymbolicPlan

from studio import i18n
from studio.config import Settings
from studio.core import Studio, UserError, scores, styles
from studio.core.engine import Rendered
from studio.core.jobs import Cancelled, stream
from studio.core.store import SongStore


class FakeEngine:
    """Stands in for YuE2/SheetSage2; returns a fixed score and one second of audio."""

    def __init__(self, abc, *, block=None):
        self.abc, self.block, self.calls = abc, block, []

    @contextmanager
    def gpu(self, label):
        yield self

    def status(self):
        return {"busy": None}

    def plan(self, request, ctx):
        self.calls.append(("plan", request))
        abc = request.abc if request.abc is not None else (None if request.cot == "off" else self.abc)
        ids = list(range(1, 11)) if abc else []
        return SymbolicPlan(request, abc, ids, [1, 2, 3], {"seconds": 0.1}, False)

    def render(self, plan, ctx):
        self.calls.append(("render", plan.request))
        ctx.stage("compose")
        if self.block is not None:
            self.block.wait(5)
            ctx.check()
        ctx.stage("render")
        audio = np.zeros((48000, 2), dtype=np.float32)
        return Rendered(audio, np.zeros((10, 64), np.float32), [1, 2, 3], {"abc": False, "semantic": False}, {})

    def transcribe(self, audio_path, output_dir, *, melody_only, ctx):
        self.calls.append(("transcribe", melody_only))
        return {"abc": scores.melody_only(self.abc) if melody_only else self.abc}


@pytest.fixture
def score(examples):
    return (examples / "score.abc").read_text(encoding="utf-8")


@pytest.fixture
def studio(tmp_path, score):
    return Studio(Settings().with_overrides(data_dir=tmp_path), engine=FakeEngine(score))


def test_translations_cover_every_english_key():
    tables = i18n.translations()
    assert set(tables["ko"]) == set(tables["en"])
    assert i18n.resolve("ko-KR,ko;q=0.9,en;q=0.8") == "ko"
    assert i18n.resolve("fr-FR") == "en"
    assert i18n.t("status.tokens", "ko", count="1,024") == "토큰 1,024개"
    assert "C조" in i18n.t("editor.valid", "ko", bpm=90, key="C", meter="4/4", measures=8, seconds=20)


def test_every_style_option_has_a_label():
    tables = i18n.translations()
    for prefix, table in (("language", styles.LANGUAGES), ("genre", styles.GENRES), ("mood", styles.MOODS),
                          ("instrument", styles.INSTRUMENTS), ("vocal", styles.VOCALS), ("preset", styles.PRESETS)):
        for key in table:
            assert f"{prefix}.{key}" in tables["en"], f"{prefix}.{key}"


def test_compose_style():
    assert styles.compose_style("korean", ["kpop"], ["energetic"], ["synth"], "duet", 124, "") == \
        "Korean, energetic K-pop, male and female duet, synth, 124 BPM"
    assert styles.compose_style("english", ["lofi"], [], ["rhodes"], "female", 0, "", instrumental=True) == "lo-fi, Rhodes"


def test_score_helpers(score):
    info = scores.inspect(score)
    assert info["ok"] and info["has_chords"] and info["sections"] == ["verse", "chorus"]
    melody = scores.melody_only(score)
    assert not scores.has_chords(melody) and scores.mode_for(melody) == "melody"
    converted, transfer = scores.to_instrumental(score)
    assert scores.inspect(converted)["vocal_notes"] == 0 and transfer["vocal_notes_before"] == info["vocal_notes"]
    assert scores.lyric_template(converted) == "[Verse]\n\n[Chorus]\n"
    assert scores.compare(score, score.replace("Q:1/4=88", "Q:1/4=100"))["melody_preserved"] is True
    assert scores.inspect("X:1\nnot a score")["ok"] is False


def test_transcription_quirks_are_normalized_for_conversion(examples):
    """SheetSage2 may emit '% silence' and key changes inside a trailing rest."""
    melody = (examples / "melody.abc").read_text(encoding="utf-8")
    quirky = melody.replace("% verse\n", "% silence\nV: Vocal\nZ|\nV: Ins\nZ|\n% verse\n", 1)
    quirky = quirky.replace("F2E2D2E2G2E2C4|\nV: Ins\nZ4|", "F2E2D2E2G2E2C2[K:G]z2|\nV: Ins\nZ3|z12z2[K:G]z2|")
    assert scores.inspect(quirky)["ok"]
    with pytest.raises(ValueError):
        scores.tools()["instrumentalize"].convert_score(quirky)       # the raw converter refuses both quirks
    settled = scores.settle_key_changes(scores.native_sections(quirky))
    assert "% silence" not in settled
    assert "z2[K:G]" not in settled and "\n[K:G]G2" in settled     # moved to the next bar line, not dropped
    assert scores.parse(settled).voices["Vocal"].notes == scores.parse(quirky).voices["Vocal"].notes
    converted, transfer = scores.to_instrumental(quirky)
    assert scores.inspect(converted)["vocal_notes"] == 0 and transfer["vocal_notes_before"] == 56
    assert scores.lyric_template(quirky) == "[Verse]\n\n[Chorus]\n"


def test_create_render_and_lineage(studio):
    song = studio.run("create", style="English, pop", lyrics="[Verse]\nHello", seed=7)
    assert song.status == "complete" and song.duration == 1.0 and song.seed == 7
    folder = studio.store.path(song.id)
    for name in (SongStore.SCORE, SongStore.AUDIO, SongStore.LATENT, SongStore.SEMANTIC):
        assert (folder / name).is_file(), name
    assert SymbolicPlan.load(folder / SongStore.PLAN).abc == studio.store.read_score(song.id)

    restyled = studio.run("restyle", source_id=song.id, style="English, jazz")
    assert restyled.parent_id == song.id and restyled.mode == "melody" and restyled.lyrics == song.lyrics
    assert (folder / SongStore.MELODY_SCORE).is_file()     # cached derived score on the parent
    assert [m.id for m in studio.store.lineage(restyled.id)] == [song.id, restyled.id]
    again = studio.run("instrumental", source_id=restyled.id)
    assert again.title == f"{song.title} · instrumental"     # labels do not pile up across versions


def test_review_first_then_record(studio):
    planned = studio.run("create", style="English, pop", lyrics="[Verse]\nHello", review_first=True)
    assert planned.status == "planned" and studio.store.file(planned.id, SongStore.AUDIO) is None
    recorded = studio.run("render_planned", song_id=planned.id)
    assert recorded.id == planned.id and recorded.status == "complete"
    with pytest.raises(UserError, match="already_rendered"):
        studio.run("render_planned", song_id=planned.id)


def test_off_mode_has_no_score_and_cannot_be_restyled(studio):
    song = studio.run("create", style="English, pop", lyrics="[Verse]\nHello", mode="off")
    assert song.score_origin == "none" and studio.store.read_score(song.id) is None
    with pytest.raises(UserError, match="song_no_score"):
        studio.run("restyle", source_id=song.id, style="jazz")


def test_edit_records_changes(studio, score):
    song = studio.run("create", style="English, pop", lyrics="[Verse]\nHello")
    edited_score = studio.store.read_score(song.id).replace("Q:1/4=88", "Q:1/4=100")
    edited = studio.run("edit", abc=edited_score, source_id=song.id)
    assert edited.extra["changes"]["tempo"] == ["1/4=88", "1/4=100"]
    assert edited.style == song.style and edited.score_origin == "user"
    with pytest.raises(UserError, match="score_invalid"):
        studio.run("edit", abc="X:1\nbroken", source_id=song.id)


def test_instrumental_from_text_and_song(studio):
    from_text = studio.run("instrumental", style="lo-fi, Rhodes")
    assert from_text.style.startswith("Instrumental, lo-fi") and "no vocals" in from_text.style
    assert scores.inspect(studio.store.read_score(from_text.id))["vocal_notes"] == 0
    assert (studio.store.path(from_text.id) / "planning" / "score.abc").is_file()
    song = studio.run("create", style="English, pop", lyrics="[Verse]\nHello")
    from_song = studio.run("instrumental", source_id=song.id, keep_chords=False)
    assert from_song.parent_id == song.id and from_song.mode == "melody"
    assert from_song.extra["transfer"]["vocal_notes_after"] == 0


def test_transcribe_and_covers(studio, tmp_path, score, examples):
    clip = tmp_path / "ref.wav"
    import soundfile as sf
    sf.write(clip, np.zeros((48000 * 8, 2), np.float32), 48000)
    reference = studio.run("transcribe", audio_path=str(clip), start=1, length=6)
    assert reference.status == "complete" and studio.store.source_audio(reference.id).name == "source.wav"
    assert studio.engine.calls[-1] == ("transcribe", True)
    with pytest.raises(UserError, match="cover_lyrics_required"):
        studio.run("cover", source_id=reference.id, style="English, pop", kind="sung", lyrics="[Verse]\n")
    sung = studio.run("cover", source_id=reference.id, style="English, pop", kind="sung", lyrics="[Verse]\nla la")
    assert sung.parent_id == reference.id and sung.mode == "melody"
    played = studio.run("cover", source_id=reference.id, style="piano", kind="instrumental")
    assert played.style.startswith("Instrumental") and played.lyrics == "[Verse]\n\n[Chorus]\n"
    from_abc = studio.run("transcribe", abc=(examples / "melody.abc").read_text(encoding="utf-8"))
    assert from_abc.score_origin == "user" and from_abc.mode == "melody"


def test_validation_errors(studio):
    with pytest.raises(UserError, match="lyrics_required"):
        studio.run("create", style="pop", lyrics="  ")
    with pytest.raises(UserError, match="review_needs_score"):
        studio.run("create", style="pop", lyrics="x", mode="off", review_first=True)
    with pytest.raises(UserError, match="song_missing"):
        studio.run("restyle", source_id="nope", style="jazz")
    with pytest.raises(UserError, match="reference_required"):
        studio.run("transcribe")


def test_failure_is_recorded(studio):
    def explode(request, ctx):
        raise RuntimeError("boom")
    studio.engine.plan = explode
    with pytest.raises(RuntimeError):
        studio.run("create", style="pop", lyrics="[Verse]\nx")
    meta = studio.store.list()[0]
    assert meta.status == "failed" and "boom" in meta.error


def test_stream_cancel_keeps_the_saved_plan(tmp_path, score):
    gate = threading.Event()
    studio = Studio(Settings().with_overrides(data_dir=tmp_path), engine=FakeEngine(score, block=gate))
    events = studio.stream("create", session="s1", style="pop", lyrics="[Verse]\nx")
    kinds = []
    for event in events:
        kinds.append(event.kind)
        if event.kind == "stage" and event.data["stage"] == "compose":
            assert studio.cancel("s1")
            gate.set()
    assert kinds[-1] == "error" and "score" in kinds
    meta = studio.store.list()[0]
    assert meta.status == "planned"        # the score survives and can still be recorded
    # A Stop that races the end of the job still finds the job's song.
    assert studio.cancel("s1", wait=1) == meta.id
    assert studio.cancel("unknown-session") is None


def test_stream_reports_worker_errors():
    def work(ctx):
        raise Cancelled()
    assert [e.kind for e in stream(work)] == ["error"]


def test_stream_ticks_during_silent_work():
    gate = threading.Event()

    def work(ctx):
        gate.wait(5)
        return "ok"
    kinds = []
    for event in stream(work, tick=0.05):
        kinds.append(event.kind)
        if kinds.count("tick") == 3:
            gate.set()
    assert kinds[-1] == "done" and kinds.count("tick") >= 3


def test_store_rename_delete_export(studio):
    song = studio.run("create", style="pop", lyrics="[Verse]\nHello")
    studio.store.rename(song.id, "New name")
    assert studio.song(song.id)["title"] == "New name"
    with zipfile.ZipFile(studio.store.export_zip(song.id)) as archive:
        assert {"meta.json", "audio.flac", "score.abc"} <= set(archive.namelist())
    studio.store.delete(song.id)
    assert not studio.store.exists(song.id) and any(studio.store.trash.iterdir())
    with pytest.raises(KeyError):
        studio.store.path("../escape")
