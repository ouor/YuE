"""Runtime settings, resolved from environment variables and CLI flags."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parent


def _model(env, local_name, repo):
    """Prefer an explicit value, then a snapshot under <repo>/models, then the Hub id."""
    if os.environ.get(env):
        return os.environ[env]
    local = REPO_ROOT / "models" / local_name
    return str(local) if local.is_dir() else repo


def _flag(env, default=False):
    value = os.environ.get(env)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("YUE2_STUDIO_DATA", APP_DIR / "data")))
    model: str = field(default_factory=lambda: _model("YUE2_STUDIO_MODEL", "YuE2-3B", "m-a-p/YuE2-3B"))
    vae: str = field(default_factory=lambda: _model("YUE2_STUDIO_VAE", "YuE2-Vae", "m-a-p/YuE2-Vae"))
    # SheetSage2 runs remote code; loading it by Hub id keeps its module cache keyed by commit.
    # A local folder is cached by folder name and can mix files from different snapshots.
    transcriber: str = field(default_factory=lambda: os.environ.get("YUE2_STUDIO_TRANSCRIBER", "m-a-p/SheetSage2"))
    transcriber_revision: str | None = field(default_factory=lambda: os.environ.get("YUE2_STUDIO_TRANSCRIBER_REVISION"))
    # Qwen3-ASR hears the words of a reference (the YuE2 model card's recommended lyric step).
    lyrics_asr: str = field(default_factory=lambda: _model("YUE2_STUDIO_LYRICS_ASR", "Qwen3-ASR-1.7B", "Qwen/Qwen3-ASR-1.7B"))
    lyrics_aligner: str = field(default_factory=lambda: _model("YUE2_STUDIO_LYRICS_ALIGNER", "Qwen3-ForcedAligner-0.6B",
                                                               "Qwen/Qwen3-ForcedAligner-0.6B"))
    device: str = field(default_factory=lambda: os.environ.get("YUE2_STUDIO_DEVICE", "auto"))
    offline: bool = field(default_factory=lambda: _flag("YUE2_STUDIO_OFFLINE"))
    skill_scripts: Path = REPO_ROOT / "skills" / "yue2-music" / "instrumental" / "scripts"
    host: str = field(default_factory=lambda: os.environ.get("YUE2_STUDIO_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("YUE2_STUDIO_PORT", "7860")))
    share: bool = field(default_factory=lambda: _flag("YUE2_STUDIO_SHARE"))
    # "user:password" enables a login page (and gradio_client auth) when the app is exposed publicly.
    auth: str | None = field(default_factory=lambda: os.environ.get("YUE2_STUDIO_AUTH"))
    # Serve HTTPS directly, e.g. behind a Cloudflare proxy in Full (strict) mode with an origin certificate.
    ssl_certfile: str | None = field(default_factory=lambda: os.environ.get("YUE2_STUDIO_SSL_CERT"))
    ssl_keyfile: str | None = field(default_factory=lambda: os.environ.get("YUE2_STUDIO_SSL_KEY"))
    # Reference clips longer than this are trimmed before transcription; long
    # sources can exceed YuE2's generation budget when rendered as a cover.
    max_reference_seconds: float = 240.0

    def with_overrides(self, **values):
        return replace(self, **{k: v for k, v in values.items() if v is not None})
