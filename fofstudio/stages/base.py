"""What a stage is, and the check results that decide whether you may approve it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..episode import Episode

BLOCK, WARN, OK = "block", "warn", "ok"


@dataclass
class Check:
    level: str          # block | warn | ok
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "message": self.message}


@dataclass
class Context:
    episode: Episode
    options: dict[str, Any] = field(default_factory=dict)
    log: Callable[[str], None] = print
    progress: Callable[[str], None] = lambda text: None
    cancelled: Callable[[], bool] = lambda: False

    def check_cancel(self) -> None:
        from ..util import StageError
        if self.cancelled():
            raise StageError("Cancelled.")


@dataclass
class Stage:
    name: str
    label: str
    engine: str                      # ollama | comfy | cpu | ffmpeg | network
    requires: tuple[str, ...]
    run: Callable[[Context], None]
    check: Callable[[Episode], list[Check]]
    optional: bool = False
    description: str = ""

    @property
    def gpu(self) -> bool:
        return self.engine in ("ollama", "comfy")


def blocks(checks: list[Check]) -> list[Check]:
    return [c for c in checks if c.level == BLOCK]
