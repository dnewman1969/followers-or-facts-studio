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


def init(path: Path | None = None) -> None:
    con = connect(path)
    try:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
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
