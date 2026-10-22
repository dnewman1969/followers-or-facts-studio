"""One episode = one project row + one folder of files.

Folder layout (inside <data>/episodes/<project_id>-<slug>/):
    episode.json        title, arc, claims, settings snapshot
    research.json       research packet (claims, sources, excerpts, rules)
    script.md           the script, in truth-vlog's v2 scene format (you can edit it)
    storyboard.json     every shot: type, prompt, image, clip, timing, provenance
    images/ video/ audio/narration/ audio/music/ captions/ render/ publish/
Stage status is stored in the database as an append-only event history.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import db
from .config import Paths
from .util import read_json, slug, utc_now, write_json


@dataclass
class Episode:
    project_id: str
    folder: Path

    # ------------------------------------------------------------ loading
    @classmethod
    def load(cls, project_id: str) -> "Episode":
        row = db.one("SELECT * FROM project WHERE project_id=?", (project_id,))
        if not row:
            raise KeyError(f"No episode called {project_id}")
        return cls(project_id, Paths().episodes / row["folder"])

    @classmethod
    def create(cls, project_id: str, title: str, arc_id: str | None,
               claim_ids: list[str] | None = None) -> "Episode":
        if not re.fullmatch(r"[A-Za-z0-9_-]{2,24}", project_id):
            raise ValueError("Episode ID must be short letters/numbers, e.g. S01E01")
        if db.one("SELECT 1 FROM project WHERE project_id=?", (project_id,)):
            raise ValueError(f"{project_id} already exists")
        if arc_id and not db.one("SELECT 1 FROM arc WHERE arc_id=?", (arc_id,)):
            raise ValueError(f"Unknown arc {arc_id}")
        if claim_ids is None:
            claim_ids = [r["claim_id"] for r in db.rows(
                "SELECT claim_id FROM claim_readiness WHERE arc_id=? "
                "ORDER BY primary_sources DESC, claim_id", (arc_id,))] if arc_id else []
        folder_name = f"{project_id}-{slug(title, 40)}"
        folder = Paths().ensure().episodes / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        with db.transaction() as con:
            con.execute("INSERT INTO project(project_id,title,arc_id,folder,created_at) "
                        "VALUES (?,?,?,?,?)", (project_id, title, arc_id, folder_name, utc_now()))
            for n, cid in enumerate(claim_ids):
                con.execute("INSERT INTO project_claim VALUES (?,?,?)", (project_id, cid, n))
        ep = cls(project_id, folder)
        write_json(ep.path("episode.json"), {
            "project_id": project_id, "title": title, "arc_id": arc_id,
            "claim_ids": claim_ids, "created_at": utc_now(), "format": "fof-episode/1",
        })
        for sub in ("images", "video", "audio/narration", "audio/music", "captions",
                    "render", "publish", "receipts"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        return ep

    # ------------------------------------------------------------ files
    def path(self, *parts: str) -> Path:
        return self.folder.joinpath(*parts)

    @property
    def info(self) -> dict[str, Any]:
        return read_json(self.path("episode.json"), {})

    @property
    def title(self) -> str:
        return self.info.get("title", self.project_id)

    @property
    def claim_ids(self) -> list[str]:
        return [r["claim_id"] for r in db.rows(
            "SELECT claim_id FROM project_claim WHERE project_id=? ORDER BY order_no",
            (self.project_id,))]

    def set_claims(self, claim_ids: list[str]) -> None:
        with db.transaction() as con:
            con.execute("DELETE FROM project_claim WHERE project_id=?", (self.project_id,))
            for n, cid in enumerate(claim_ids):
                con.execute("INSERT INTO project_claim VALUES (?,?,?)", (self.project_id, cid, n))

    def rel(self, path: Path) -> str:
        """Paths stored in JSON are relative to the episode folder."""
        return Path(path).resolve().relative_to(self.folder.resolve()).as_posix()

    def abs(self, rel: str) -> Path:
        return self.folder / rel

    def storyboard(self) -> dict[str, Any]:
        return read_json(self.path("storyboard.json"), {})

    def save_storyboard(self, data: dict[str, Any]) -> None:
        write_json(self.path("storyboard.json"), data)

    # ------------------------------------------------------------ stage history
    def record(self, stage: str, status: str, note: str = "") -> None:
        db.execute("INSERT INTO stage_event(project_id,stage,status,note,at) VALUES (?,?,?,?,?)",
                   (self.project_id, stage, status, note, utc_now()))

    def stage_status(self, stage: str) -> dict[str, Any]:
        row = db.one("SELECT status, note, at FROM stage_event WHERE project_id=? AND stage=? "
                     "ORDER BY event_id DESC LIMIT 1", (self.project_id, stage))
        return row or {"status": "not_started", "note": "", "at": None}

    def history(self) -> list[dict[str, Any]]:
        return db.rows("SELECT * FROM stage_event WHERE project_id=? ORDER BY event_id",
                       (self.project_id,))


def list_episodes() -> list[dict[str, Any]]:
    return db.rows("SELECT * FROM project ORDER BY created_at DESC")
