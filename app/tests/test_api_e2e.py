"""End-to-end API tests against a running studio (real GPU generation).

    python app/app.py --port 6000 &
    YUE2_STUDIO_URL=http://127.0.0.1:6000 YUE2_STUDIO_REFERENCE=song.mp3 pytest app/tests/test_api_e2e.py -v

Tests run in order and share songs through STATE; each render takes about a minute.
"""
from pathlib import Path
import os
import re
import zipfile

import pytest
import soundfile as sf

gradio_client = pytest.importorskip("gradio_client")
from gradio_client import Client, handle_file  # noqa: E402
from gradio_client.exceptions import AppError  # noqa: E402

STATE = {}
STYLE = "English, warm piano pop, expressive female vocal, acoustic piano, bass, light drums, 92 BPM"
LYRICS = ("[Verse]\nLanterns glow along the pier\nEvery wave a song I hear\n\n"
          "[Chorus]\nSing it slow, sing it clear\nHold the moment while it's here")
KOREAN_LYRICS = "[Verse]\n바람이 불어오는 길 위에\n작은 노래를 띄워 보내\n\n[Chorus]\n함께 걸어가자\n이 밤이 끝날 때까지"


@pytest.fixture(scope="module")
def client(server_url):
    try:
        return Client(server_url, verbose=False)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Studio not reachable at {server_url}: {exc}")


def rendered(song, *, operation, score=True):
    assert song["status"] == "complete", song
    assert song["operation"] == operation
    assert song["audio"] and Path(song["audio"]).is_file()
    info = sf.info(song["audio"])
    assert info.samplerate == 48000 and info.channels == 2 and info.duration > 5
    assert not any(song["truncated"].values()), song["truncated"]
    if score:
        assert song["score"] and "V: Vocal" in song["score"]
    return song


def fails_with(key, fn, **kwargs):
    with pytest.raises(AppError, match=re.escape(key)):
        fn(**kwargs)


def test_health(client):
    health = client.predict(api_name="/health")
    assert {"create", "restyle", "edit", "instrumental", "transcribe", "cover", "render_planned"} <= set(health["workflows"])
    assert health["engine"]["cuda"] is not None


def test_style_builder_api(client):
    options = client.predict(api_name="/style_options")
    assert "kpop" in options["genres"] and "lofi_study" in options["presets"]
    style = client.predict(language="korean", genres=["kpop"], moods=["energetic"], instruments=["synth"], vocal="duet",
                           bpm=124, api_name="/compose_style")
    assert style == "Korean, energetic K-pop, male and female duet, synth, 124 BPM"


def test_create_full_score(client):
    song = client.predict(style=STYLE, lyrics=LYRICS, title="Lanterns", seed=1234, api_name="/create_song")
    rendered(song, operation="create")
    assert song["title"] == "Lanterns" and song["mode"] == "full" and song["seed"] == 1234
    assert '"' in song["score"]                      # full mode plans chord symbols
    assert song["preview"].endswith("preview.mp3")
    STATE["full"] = song


def test_create_review_then_record(client):
    planned = client.predict(style="Korean, gentle ballad, warm male vocal, piano, strings", lyrics=KOREAN_LYRICS,
                             review_first=True, api_name="/create_song")
    assert planned["status"] == "planned" and planned["has_plan"] and planned["audio"] is None
    assert planned["score"]
    recorded = client.predict(song_id=planned["id"], api_name="/render_planned")
    rendered(recorded, operation="create")
    assert recorded["id"] == planned["id"] and recorded["score"] == planned["score"]   # the exact reviewed score
    fails_with("error.already_rendered", client.predict, song_id=planned["id"], api_name="/render_planned")


def test_create_melody_mode(client):
    song = client.predict(style=STYLE, lyrics=LYRICS, mode="melody", api_name="/create_song")
    rendered(song, operation="create")
    assert song["mode"] == "melody" and '"' not in "".join(
        line for line in song["score"].splitlines() if not line.startswith(("V:", "T:")))


def test_create_without_score(client):
    song = client.predict(style=STYLE, lyrics=LYRICS, mode="off", api_name="/create_song")
    rendered(song, operation="create", score=False)
    assert song["score"] is None and song["score_origin"] == "none"
    STATE["off"] = song
    fails_with("error.song_no_score", client.predict, source_id=song["id"], style="jazz", api_name="/restyle_song")


def test_restyle_melody_only(client):
    source = STATE["full"]
    song = client.predict(source_id=source["id"],
                          style="English, jazz-funk, warm lead vocal, Rhodes, slap bass, tight drums, 104 BPM",
                          api_name="/restyle_song")
    rendered(song, operation="restyle")
    assert song["parent_id"] == source["id"] and song["mode"] == "melody"
    assert song["lyrics"] == source["lyrics"] and song["lineage"] == [source["id"], song["id"]]
    assert client.predict(abc=song["score"], source_id=source["id"], api_name="/check_score")["changes"][
        "melody_preserved"] is True


def test_restyle_keep_chords(client):
    source = STATE["full"]
    song = client.predict(source_id=source["id"], style="English, rock, male vocal, electric guitar, bass, drums",
                          keep_chords=True, api_name="/restyle_song")
    rendered(song, operation="restyle")
    assert song["mode"] == "full" and song["score"] == source["score"]


def test_check_score(client, examples):
    good = client.predict(abc=(examples / "score.abc").read_text(encoding="utf-8"), api_name="/check_score")
    assert good["ok"] and good["bpm"] == 88 and good["has_chords"]
    bad = client.predict(abc="X:1\nT:\nnot a score", api_name="/check_score")
    assert not bad["ok"] and bad["error"]


def test_edit_score(client):
    source = STATE["full"]
    tempo = int(re.search(r"^Q:1/4=(\d+)", source["score"], re.M).group(1))
    edited = re.sub(r"^Q:1/4=\d+", f"Q:1/4={tempo + 16}", source["score"], count=1, flags=re.M)
    report = client.predict(abc=edited, source_id=source["id"], api_name="/check_score")
    assert report["ok"] and report["changes"]["melody_preserved"]
    song = client.predict(abc=edited, source_id=source["id"], api_name="/edit_song")
    rendered(song, operation="edit")
    assert song["parent_id"] == source["id"] and song["style"] == source["style"]
    assert song["extra"]["changes"]["tempo"][1] == f"1/4={tempo + 16}"
    assert f"Q:1/4={tempo + 16}" in song["score"]
    fails_with("error.score_invalid", client.predict, abc="X:1\nbroken", source_id=source["id"], api_name="/edit_song")


def test_instrumental_from_description(client):
    song = client.predict(style="lo-fi hip hop, Rhodes, dusty drums, mellow bass, 80 BPM", api_name="/create_instrumental")
    rendered(song, operation="instrumental")
    assert song["style"].startswith("Instrumental, lo-fi") and "no vocals" in song["style"]
    assert song["extra"]["transfer"]["vocal_notes_after"] == 0
    assert not re.search(r"^\[[^\]]+\]\n(?!\n|\[|$)", song["lyrics"], re.M)   # section tags only, no words


def test_instrumental_from_song(client):
    source = STATE["full"]
    song = client.predict(style="solo acoustic guitar, fingerstyle, intimate", source_id=source["id"],
                          api_name="/create_instrumental")
    rendered(song, operation="instrumental")
    assert song["parent_id"] == source["id"] and song["mode"] == "full"
    transfer = song["extra"]["transfer"]
    assert transfer["vocal_notes_before"] > 0 and transfer["vocal_notes_after"] == 0


def test_transcribe_reference_audio(client):
    reference = os.environ.get("YUE2_STUDIO_REFERENCE")
    if not reference or not Path(reference).is_file():
        pytest.skip("Set YUE2_STUDIO_REFERENCE to an audio file")
    song = client.predict(handle_file(reference), 0, 45, False, "", api_name="/transcribe_reference")
    assert song["status"] == "complete" and song["operation"] == "transcribe" and song["score_origin"] == "sheetsage2"
    assert song["source_audio"] and sf.info(song["source_audio"]).duration == pytest.approx(45, abs=0.5)
    assert song["score"] and song["mode"] == "melody" and song["extra"]["score"]["ok"]
    STATE["reference"] = song


def test_sung_cover(client):
    reference = STATE.get("reference") or pytest.skip("needs the transcribed reference")
    lyrics = "\n\n".join(f"{tag}\nCity lights are calling out my name\nEvery heartbeat running through the rain"
                         for tag in dict.fromkeys(re.findall(r"^\[[^\]]+\]$", reference_template(reference), re.M)))
    fails_with("error.cover_lyrics_required", client.predict, source_id=reference["id"], style=STYLE, kind="sung",
               lyrics="[Verse]\n", api_name="/create_cover")
    song = client.predict(source_id=reference["id"], style="English, synth-pop, bright female vocal, synth, drums",
                          kind="sung", lyrics=lyrics, api_name="/create_cover")
    rendered(song, operation="cover")
    assert song["parent_id"] == reference["id"] and song["extra"]["kind"] == "sung"


def test_instrumental_cover(client):
    reference = STATE.get("reference") or pytest.skip("needs the transcribed reference")
    song = client.predict(source_id=reference["id"], style="string quartet, cinematic", kind="instrumental",
                          api_name="/create_cover")
    rendered(song, operation="cover")
    assert song["style"].startswith("Instrumental") and song["extra"]["kind"] == "instrumental"


def test_cover_from_abc_reference(client, examples):
    reference = client.predict(abc=(examples / "melody.abc").read_text(encoding="utf-8"), title="Melody example",
                               api_name="/transcribe_abc")
    assert reference["status"] == "complete" and reference["score_origin"] == "user"
    song = client.predict(source_id=reference["id"], style="English, bossa nova, soft female vocal, nylon guitar",
                          kind="sung", lyrics="[Verse]\nMorning light upon the sea\nQuiet waves come back to me\n"
                          "Every tide a melody\nSinging softly, wild and free\n\n[Chorus]\nStay a while and hear it play\n"
                          "Let the music find its way\nIn the warm and golden day\nWe will sing it all away",
                          api_name="/create_cover")
    rendered(song, operation="cover")


def test_downloads(client, tmp_path):
    song = STATE["full"]
    audio = Path(client.predict(song["id"], api_name="/song_audio"))
    assert audio.suffix == ".flac" and sf.info(audio).samplerate == 48000
    archive = Path(client.predict(song["id"], api_name="/export_song"))
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
    assert {"meta.json", "score.abc", "audio.flac", "preview.mp3", "latent.npy", "semantic.npy",
            "plan/plan.json"} <= names


def test_library(client):
    songs = client.predict(api_name="/list_songs")
    ids = {s["id"] for s in songs}
    assert STATE["full"]["id"] in ids
    restyles = client.predict(operation="restyle", api_name="/list_songs")
    assert restyles and all(s["operation"] == "restyle" for s in restyles)
    assert any(s["id"] == STATE["full"]["id"] for s in client.predict(query="Lanterns", api_name="/list_songs"))
    renamed = client.predict(song_id=STATE["full"]["id"], title="Lanterns (renamed)", api_name="/rename_song")
    assert renamed["title"] == "Lanterns (renamed)"
    target = STATE["off"]["id"]
    assert client.predict(song_id=target, api_name="/delete_song") == {"deleted": target}
    fails_with("error.song_missing", client.predict, song_id=target, api_name="/get_song")


def test_input_errors(client):
    fails_with("error.lyrics_required", client.predict, style=STYLE, lyrics=" ", api_name="/create_song")
    fails_with("error.style_required", client.predict, style="", lyrics=LYRICS, api_name="/create_song")
    fails_with("error.review_needs_score", client.predict, style=STYLE, lyrics=LYRICS, mode="off", review_first=True,
               api_name="/create_song")
    fails_with("error.song_missing", client.predict, source_id="missing-song", style="jazz", api_name="/restyle_song")
    fails_with("error.reference_required", client.predict, abc="", api_name="/transcribe_abc")


def reference_template(song):
    return "\n".join(f"[{s.title()}]" for s in song["extra"]["score"]["sections"]) or "[Verse]"
