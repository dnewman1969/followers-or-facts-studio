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
    # progress("Saving sources 3/12", 25): the text and, when known, a percentage
    progress: Callable[..., None] = lambda text, pct=None: None
    cancelled: Callable[[], bool] = lambda: False

    def writing(self, what: str, start: float = 5, end: float = 95, expect_words: int = 0) -> Callable[[str], None]:
        """A progress callback for the local AI's streamed answer: 'Writing the script: 240 words so far'."""
        def update(text: str) -> None:
            self.check_cancel()
            n = len(text.split())
            pct = None
            if expect_words:
                pct = min(end, start + (end - start) * n / expect_words)
            self.progress(f"{what}: {n:,} words written so far" + (f" (about {expect_words:,} expected)"
                                                                   if expect_words else ""), pct)
        return update

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
    hidden: bool = False   # a helper job (like the quick preview) outside the approval chain

    @property
    def gpu(self) -> bool:
        return self.engine in ("ollama", "comfy")


def blocks(checks: list[Check]) -> list[Check]:
    return [c for c in checks if c.level == BLOCK]
