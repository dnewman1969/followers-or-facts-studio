"""Film genres and directors' styles for the script (Script page).

The genre changes the script's tone, pacing, scene ideas, the look of the pictures (lighting, palette,
framing) and the music; the director's style changes the shot list: framing, camera moves, how long
shots hold, transitions and how music and silence are used. Facts never change: the fact lock goes in
front of every genre.

From the research "Film genres directors and video length" (project docs). Directors are described to
the AI by their traits only, never by name; the app shows "inspired by ..." so you know which is which.
Careful topics (real victims or deaths) only offer the sober genres and no playful styles.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"
CAREFUL_GENRES = {"explainer_documentary", "investigative_news_magazine", "courtroom_drama",
                  "historical_epic_period_piece"}
PLAYFUL_DIRECTORS = {"dollhouse_symmetry", "kinetic_montage", "curious_collage"}
DEFAULT_GENRE = "explainer_documentary"


@dataclass(frozen=True)
class Genre:
    key: str
    name: str
    definition: str
    prompt: str
    music_tags: str
    look: str
    suits: str
    avoid: str

    @property
    def careful_ok(self) -> bool:
        return self.key in CAREFUL_GENRES

    @property
    def bpm(self) -> int:
        m = re.search(r"(\d{2,3})\s*bpm", self.music_tags)
        return int(m.group(1)) if m else 90


@dataclass(frozen=True)
class Director:
    key: str
    name: str
    inspired_by: str
    prompt: str
    topics: str
    shot_seconds: tuple[int, int]

    @property
    def label(self) -> str:
        return f"{self.name} (inspired by {self.inspired_by})"

    @property
    def average_shot(self) -> float:
        return max(2.0, min(8.0, sum(self.shot_seconds) / 2))


@lru_cache(maxsize=1)
def _genre_data() -> dict:
    return json.loads((DATA / "genres.json").read_text(encoding="utf-8"))


def fact_lock() -> str:
    return "FACT LOCK: " + _genre_data()["fact_lock"]


def genres() -> dict[str, Genre]:
    return {g["key"]: Genre(g["key"], g["name"], g["definition"], g["prompt"], g["music_tags"], g["look"],
                            g["suits"], g["avoid"]) for g in _genre_data()["genres"]}


@lru_cache(maxsize=1)
def _director_data() -> list:
    return json.loads((DATA / "directors.json").read_text(encoding="utf-8"))


def directors() -> dict[str, Director]:
    return {d["key"]: Director(d["key"], d["name"], d["inspired_by"], d["prompt"], d.get("topics", ""),
                               tuple(d.get("shot_seconds", [4, 7]))) for d in _director_data()}


def allowed_genres(careful: bool) -> list[Genre]:
    return [g for g in genres().values() if g.careful_ok or not careful]


def allowed_directors(careful: bool) -> list[Director]:
    return [d for d in directors().values() if not (careful and d.key in PLAYFUL_DIRECTORS)]


def chosen(creative: dict) -> tuple[Genre | None, Director | None]:
    """The genre and director for this video (None = not chosen), respecting the careful-topic lock."""
    careful = bool(creative.get("careful"))
    g = genres().get(creative.get("genre") or "")
    d = directors().get(creative.get("director") or "")
    if g and careful and not g.careful_ok:
        g = genres()[DEFAULT_GENRE]
    if d and careful and d.key in PLAYFUL_DIRECTORS:
        d = None
    return g, d


def script_block(g: Genre | None, d: Director | None) -> str:
    """For the script writer: the genre's tone and structure, the director's way of shooting."""
    parts = [fact_lock()]
    if g:
        parts.append(f"GENRE ({g.name}): {g.prompt}")
    if d:
        parts.append(f"DIRECTING STYLE (use it for the VISUAL of every scene, the pacing and the music; it never "
                     f"changes the facts): {d.prompt}")
    return "\n\n".join(parts)


def visual_block(g: Genre | None, d: Director | None) -> str:
    """For the storyboard's art director and the image prompts: lighting, palette, framing, camera."""
    parts = []
    if g and g.look:
        parts.append(f"Genre look ({g.name}): {g.look}")
    if d:
        parts.append(f"Directing style: {d.prompt}")
    return "\n".join(parts)
