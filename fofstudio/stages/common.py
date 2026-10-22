"""Things several stages need: the sources a script cites, and the KF credit line."""

from __future__ import annotations

from typing import Any

from .. import db
from ..config import settings
from ..episode import Episode
from ..scriptfmt import parse
from ..util import read_json


def cited_sources(ep: Episode) -> list[dict[str, Any]]:
    if not ep.path("script.md").exists():
        return []
    order: list[str] = []
    for sc in parse(ep.path("script.md").read_text(encoding="utf-8"))["scenes"]:
        for sid in sc["source_ids"]:
            if sid not in order:
                order.append(sid)
    found = {r["source_id"]: r for r in db.rows(
        "SELECT * FROM source WHERE source_id IN (%s)" % ",".join("?" * len(order)), tuple(order))} \
        if order else {}
    return [found[s] for s in order if s in found]


def kf_episodes(ep: Episode) -> list[str]:
    packet = read_json(ep.path("research.json")) or {"claims": []}
    eps: list[str] = []
    for c in packet["claims"]:
        for k in c.get("kf_episodes", []):
            if k["kf_ep"] not in eps:
                eps.append(k["kf_ep"])
    return eps


def credit_line(ep: Episode) -> str:
    eps = kf_episodes(ep)
    base = settings()["pipeline"]["channel_credit"]
    if eps:
        shown = ", ".join(f"#{e}" for e in eps[:8]) + (" and more" if len(eps) > 8 else "")
        return f"{base} Knowledge Fight episodes used as a research index: {shown}."
    return base


def source_line(s: dict[str, Any]) -> str:
    bits = [s["title"]]
    if s.get("publisher"):
        bits.append(s["publisher"])
    if s.get("date"):
        bits.append(s["date"])
    return " - ".join(bits)
