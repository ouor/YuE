# YuE2 Song Studio

A Gradio demo for people who just want to make songs: write lyrics, pick a sound, and get a
song **plus a score you can read, play, and change**. Design notes: [DESIGN.md](DESIGN.md).

| Tab | What it does |
|---|---|
| 🎤 Create | Lyrics + style builder → score → song. Optionally stop after the score to review it. |
| 🎨 New Genre | Keep a song's melody, re-render it in another style (A/B with the original). |
| ✏️ Score Editor | Edit the ABC score with a live sheet preview; set tempo, remove chords, check, record. |
| 🎹 Instrumental | Background music from a description, or turn a library song into an instrumental. |
| 🔁 Cover | Extract a melody from a recording (SheetSage2) or ABC, then make a sung or instrumental cover. |
| 📚 Library | Every result is a version with its history; rename, download, delete, continue from any song. |

The UI is English with a Korean translation, chosen from the browser language.

## Setup (Windows or Linux, NVIDIA GPU with 24 GB)

```bash
conda create -y -n yue2-app python=3.12
conda activate yue2-app
pip install torch==2.12.0 --index-url https://download.pytorch.org/whl/cu130
pip install --no-deps torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
pip install --no-deps -e .
pip install -r app/requirements.txt
```

`torchaudio` 2.12 is not published for cu130; SheetSage2 only needs its pure-Python
transforms, which work with the 2.11 wheel. FFmpeg must be on `PATH`.

YuE2 models are read from `models/YuE2-3B` and `models/YuE2-Vae` when those
folders exist, otherwise from the Hugging Face Hub; SheetSage2 always loads by Hub id (cached after the
first run). To download the YuE2 models without symlinks (needed on
Windows without Developer Mode):

```bash
python -c "from huggingface_hub import snapshot_download as d; [d(r, local_dir='models/'+r.split('/')[1]) for r in ('m-a-p/YuE2-3B','m-a-p/YuE2-Vae')]"
```

## Run

```bash
python app/app.py --port 7860 --offline
```

| Option / variable | Meaning |
|---|---|
| `--host`, `YUE2_STUDIO_HOST` | Bind address (default `127.0.0.1`; use `0.0.0.0` behind a reverse proxy) |
| `--port`, `YUE2_STUDIO_PORT` | Port (default 7860) |
| `--data-dir`, `YUE2_STUDIO_DATA` | Song library (default `app/data`) |
| `--offline`, `YUE2_STUDIO_OFFLINE` | Never contact the Hub |
| `YUE2_STUDIO_AUTH=user:password` | Require a login — recommended when the app is reachable from the internet |
| `--ssl-cert`, `--ssl-key` (`YUE2_STUDIO_SSL_CERT/KEY`) | Serve HTTPS directly; leave unset behind a proxy that talks HTTP to the app |
| `YUE2_STUDIO_MODEL`, `_VAE`, `_TRANSCRIBER` | Model paths or Hub ids |
| `DEEPSEEK_API_KEY` | Turns on the "Continue with AI" lyric button (hidden when unset) |
| `YUE2_STUDIO_ASSIST_EFFORT` | Lyric model thinking effort: `low` (default, faster) or `high` (slower, a little better in Korean and Japanese) |
| `YUE2_STUDIO_ASSIST_BASE_URL`, `_MODEL` | Another OpenAI-compatible endpoint/model (default DeepSeek `deepseek-flash`) |

## API

Every feature is callable with `gradio_client`; the in-app "Use via API" page lists signatures.

```python
from gradio_client import Client, handle_file

client = Client("http://127.0.0.1:7860")
song = client.predict(style="English, warm piano pop, female vocal", lyrics="[Verse]\n...",
                      api_name="/create_song")
jazz = client.predict(source_id=song["id"], style="English, jazz, Rhodes", api_name="/restyle_song")
ref = client.predict(handle_file("song.mp3"), 0, 45, False, "", api_name="/transcribe_reference")
cover = client.predict(source_id=ref["id"], style="string quartet", kind="instrumental", api_name="/create_cover")
flac = client.predict(cover["id"], api_name="/song_audio")
```

Endpoints: `/health`, `/style_options`, `/compose_style`, `/create_song`, `/render_planned`,
`/restyle_song`, `/check_score`, `/edit_song`, `/create_instrumental`, `/transcribe_reference`,
`/transcribe_abc`, `/create_cover`, `/list_songs`, `/get_song`, `/rename_song`, `/delete_song`,
`/song_audio`, `/export_song`. Input problems raise an error whose message ends with a key such as
`(error.lyrics_required)`.

## Tests

```bash
pytest app/tests/test_core.py                     # no GPU: fake engine
YUE2_STUDIO_URL=http://127.0.0.1:7860 YUE2_STUDIO_REFERENCE=song.mp3 pytest app/tests/test_api_e2e.py -v
```

## Extending

- **New feature:** add a `Workflow` subclass with `@register` in `studio/core/workflows/`.
- **New screen:** add a `Tab` subclass in `studio/ui/tabs/` and list it in `TABS`.
- **New API:** add a function in `studio/api.py` that calls `studio.run("<workflow>", ...)`.
- **New language:** add `studio/i18n/<code>.json` (missing keys fall back to English).
- **Style options:** edit the dictionaries in `studio/core/styles.py` and add labels to the JSON files.
