"""SQLite access. One file, WAL mode so the app window and the worker can both use it."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import Paths

SCHEMA = Path(__file__).with_name("schema.sql")


def db_path() -> Path:
    return Paths().db


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 30000")
    return con


# Columns added after v0.1. Old databases get them on start-up.
MIGRATIONS = [
    ("job", "progress_pct", "INTEGER"),
    ("project", "subject_type", "TEXT"),
    ("project", "subject_id", "TEXT"),
    ("source", "archive_url", "TEXT"),
    ("source", "found_by", "TEXT"),
    ("source_excerpt", "supports", "TEXT"),
    ("source", "summary", "TEXT"),
    ("caricature", "design_json", "TEXT"),       # the structured design (research "Art styles caricatures ...")
    ("caricature", "references_json", "TEXT"),   # the free photos looked at (audit only; never sent to ComfyUI)
    ("caricature", "search_hint", "TEXT"),       # who this is, so the photo search finds the right person
    ("caricature", "tradition", "TEXT"),         # the caricature style it was approved in
    ("caricature", "picture", "TEXT"),           # the approved picture, relative to the data folder
    ("caricature", "approved_in", "TEXT"),       # the video (project id) it was approved in
    ("caricature", "used_in", "TEXT"),           # JSON list of the videos that drew this person
]


def init(path: Path | None = None) -> None:
    con = connect(path)
    try:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        for table, column, kind in MIGRATIONS:
            have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    finally:
        con.close()


@contextmanager
def transaction(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    con = connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def rows(sql: str, params: tuple | dict = (), path: Path | None = None) -> list[dict[str, Any]]:
    con = connect(path)
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()


def one(sql: str, params: tuple | dict = (), path: Path | None = None) -> dict[str, Any] | None:
    found = rows(sql, params, path)
    return found[0] if found else None


def execute(sql: str, params: tuple | dict = (), path: Path | None = None) -> int:
    with transaction(path) as con:
        return con.execute(sql, params).rowcount


def is_empty(path: Path | None = None) -> bool:
    try:
        found = one("SELECT COUNT(*) AS n FROM claim", path=path)
    except sqlite3.OperationalError:
        return True
    return not found or found["n"] == 0
