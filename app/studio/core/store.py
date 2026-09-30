"""File-backed song library: one directory per song version."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
from datetime import datetime
import zipfile

from .models import SongMeta, Status, now

SONG_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,120}$")


class SongNotFound(KeyError):
    pass


class SongStore:
    META = "meta.json"
    SCORE = "score.abc"
    MELODY_SCORE = "score.melody.abc"
    PLAN = "plan"
    AUDIO = "audio.flac"
    PREVIEW = "preview.mp3"
    LATENT = "latent.npy"
    SEMANTIC = "semantic.npy"
    SOURCE = "source"                 # source.<ext>: a cover reference clip
    TRANSCRIPTION = "transcription"
    CONVERSION = "conversion.json"

    def __init__(self, root):
        self.root = Path(root)
        self.songs = self.root / "songs"
        self.trash = self.root / "trash"
        self.exports = self.root / "exports"
        for directory in (self.songs, self.trash, self.exports):
            directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # -- identity -----------------------------------------------------------
    def new_id(self, title=""):
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:32] or "song"
        return f"{datetime.now():%Y%m%d-%H%M%S}-{slug}-{secrets.token_hex(2)}"

    def path(self, song_id):
        if not isinstance(song_id, str) or not SONG_ID.fullmatch(song_id):
            raise SongNotFound(song_id)
        return self.songs / song_id

    def exists(self, song_id):
        try:
            return (self.path(song_id) / self.META).is_file()
        except SongNotFound:
            return False

    # -- metadata -----------------------------------------------------------
    def create(self, operation, title, *, parent_id=None, status=Status.RENDERING, **values):
        title = (title or "").strip() or "Untitled"
        meta = SongMeta(id=self.new_id(title), title=title, operation=str(getattr(operation, "value", operation)),
                        status=str(getattr(status, "value", status)), parent_id=parent_id, **values)
        self.path(meta.id).mkdir(parents=True)
        self.save(meta)
        return meta

    def get(self, song_id):
        path = self.path(song_id) / self.META
        if not path.is_file():
            raise SongNotFound(song_id)
        return SongMeta.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, meta):
        meta.updated_at = now()
        target = self.path(meta.id) / self.META
        temporary = target.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(json.dumps(meta.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, target)
        return meta

    def update(self, song_id, **values):
        meta = self.get(song_id)
        for key, value in values.items():
            if key == "status":
                value = str(getattr(value, "value", value))
            setattr(meta, key, value)
        return self.save(meta)

    def list(self, operation=None, query=None):
        result = []
        for path in self.songs.glob(f"*/{self.META}"):
            try:
                meta = SongMeta.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                continue
            if operation and meta.operation != operation:
                continue
            if query and query.lower() not in f"{meta.title} {meta.style} {meta.lyrics}".lower():
                continue
            result.append(meta)
        return sorted(result, key=lambda m: m.created_at, reverse=True)

    def lineage(self, song_id):
        chain, seen = [], set()
        current = song_id
        while current and current not in seen and self.exists(current):
            seen.add(current)
            meta = self.get(current)
            chain.append(meta)
            current = meta.parent_id
        return list(reversed(chain))

    def rename(self, song_id, title):
        title = (title or "").strip()
        if not title:
            raise ValueError("Title must not be empty")
        return self.update(song_id, title=title)

    def delete(self, song_id):
        """Move a song to the trash folder; nothing is permanently removed."""
        source = self.path(song_id)
        if not source.is_dir():
            raise SongNotFound(song_id)
        shutil.move(str(source), str(self.trash / f"{song_id}-{secrets.token_hex(2)}"))

    # -- files --------------------------------------------------------------
    def file(self, song_id, name):
        path = self.path(song_id) / name
        return path if path.exists() else None

    def read_score(self, song_id):
        path = self.file(song_id, self.SCORE)
        return path.read_text(encoding="utf-8") if path else None

    def read_score_variant(self, song_id, name, derive):
        """Return a derived score (e.g. chord-free), computing and caching it on first use."""
        if path := self.file(song_id, name):
            return path.read_text(encoding="utf-8")
        text = derive(self.read_score(song_id))
        self.write_text(song_id, name, text)
        return text

    def write_text(self, song_id, name, text):
        path = self.path(song_id) / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def playable_audio(self, song_id):
        """Browser-friendly audio: preview mp3, rendered flac, or the cover reference clip."""
        for name in (self.PREVIEW, self.AUDIO):
            if path := self.file(song_id, name):
                return path
        return self.source_audio(song_id)

    def source_audio(self, song_id):
        return next(iter(sorted(self.path(song_id).glob(f"{self.SOURCE}.*"))), None)

    def export_zip(self, song_id):
        source = self.path(song_id)
        if not source.is_dir():
            raise SongNotFound(song_id)
        target = self.exports / f"{song_id}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(source).as_posix())
        return target
