"""Song nodes: every result is a version that may point at its parent."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum


class Operation(str, Enum):
    CREATE = "create"
    RESTYLE = "restyle"
    EDIT = "edit"
    INSTRUMENTAL = "instrumental"
    TRANSCRIBE = "transcribe"
    COVER = "cover"


class Status(str, Enum):
    PLANNED = "planned"        # score ready, audio not rendered yet
    RENDERING = "rendering"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScoreOrigin(str, Enum):
    NONE = "none"              # generated without a symbolic plan
    YUE2 = "yue2"
    USER = "user"
    TRANSCRIBED = "sheetsage2"
    CONVERTED = "converted"    # derived from another score (e.g. vocal → instrumental)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SongMeta:
    id: str
    title: str
    operation: str
    status: str
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    parent_id: str | None = None
    style: str = ""
    lyrics: str = ""
    mode: str = "full"
    seed: int = 0
    score_origin: str = ScoreOrigin.NONE.value
    duration: float | None = None
    truncated: dict = field(default_factory=dict)
    timing: dict = field(default_factory=dict)
    error: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        # Ignore unknown keys so newer metadata stays readable by older code.
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def is_truncated(self):
        return any(self.truncated.values())
