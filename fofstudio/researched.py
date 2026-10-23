"""Researched projects: every subject you've researched, the videos made from it, and a way
to start another video from the same research - with different evidence, or with another of
the three stories already written.

Research itself is kept in the database (every source, quote and summary the agents found is
linked to its claims), so a new video on the same subject starts with all of it. Each video
keeps its own ticks (research.json) and its own three stories (stories.json).
"""

from __future__ import annotations

import html
import shutil
from typing import Any

from . import db, subjects
from .episode import Episode, list_episodes, next_id
from .stages import STAGES
from .util import read_json, utc_now, write_json

KIND_NAMES = {"story": "Story", "conspiracy": "Conspiracy", "person": "Person", "org": "Organization"}
STEP_NAMES = {"research": "Research", "stories": "Stories", "script": "Script", "storyboard": "Storyboard",
              "video_plan": "Video", "video": "Video", "narration": "Production", "captions": "Production",
              "music": "Production", "production": "Production", "render": "Production",
              "package": "Publish", "upload": "Publish"}


def subject_of(row: dict[str, Any]) -> tuple[str, str] | None:
    kind = row.get("subject_type") or ("story" if row.get("arc_id") else None)
    sid = row.get("subject_id") or row.get("arc_id")
    return (kind, sid) if kind and sid else None


def where_is(ep: Episode) -> str:
    """Plain words for how far a video has got."""
    last = None
    for s in STAGES:
        if s.hidden or s.optional:
            continue
        st = ep.stage_status(s.name)["status"]
        if st != "approved":
            name = STEP_NAMES.get(s.name, s.label)
            if st == "awaiting_approval":
                return f"{name}: waiting for your OK"
            if st in ("running", "queued"):
                return f"{name}: working"
            if st == "failed":
                return f"{name}: failed"
            return f"next: {name}" if last else "not started"
        last = s.name
    return "uploaded"


def videos_for(kind: str, subject_id: str) -> list[dict[str, Any]]:
    out = []
    for row in reversed(list_episodes()):  # oldest first
        if subject_of(row) != (kind, subject_id):
            continue
        ep = Episode.load(row["project_id"])
        packet = read_json(ep.path("research.json")) or {}
        stories = read_json(ep.path("stories.json")) or {}
        chosen = stories.get("chosen")
        ev = packet.get("evidence", [])
        out.append({
            "project_id": row["project_id"], "title": ep.title, "episode": ep,
            "ticked": sum(1 for e in ev if e.get("include")), "evidence": len(ev),
            "researched_at": packet.get("researched_at"), "has_research": bool(packet),
            "stories": [o.get("title", "") for o in stories.get("options", [])],
            "chosen": chosen, "chosen_title": stories["options"][chosen]["title"] if chosen is not None else None,
            "set_id": stories.get("set_id"), "where": where_is(ep), "based_on": ep.info.get("based_on"),
        })
    return out


def listing(search: str = "") -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in list_episodes():
        key = subject_of(row)
        if not key:
            continue
        ep = Episode.load(row["project_id"])
        packet = read_json(ep.path("research.json"))
        if not packet:
            continue
        g = groups.setdefault(key, {"kind": key[0], "id": key[1], "videos": 0, "evidence": 0,
                                    "last": "", "title": row["title"]})
        g["videos"] += 1
        g["evidence"] = max(g["evidence"], len(packet.get("evidence", [])))
        g["last"] = max(g["last"], packet.get("researched_at") or packet.get("built_at") or "")
    for g in groups.values():
        try:
            g["title"] = subjects.headline(g["kind"], g["id"])["title"]
        except (TypeError, KeyError):
            pass
    q = search.strip().lower()
    rows = [g for g in groups.values() if not q or q in g["title"].lower() or q in g["id"].lower()]
    return sorted(rows, key=lambda g: g["last"], reverse=True)


def detail_html(kind: str, subject_id: str) -> str:
    e = html.escape
    try:
        head = subjects.headline(kind, subject_id)
    except (TypeError, KeyError):
        head = {"title": subject_id, "about": ""}
    vids = videos_for(kind, subject_id)
    parts = [f"<h2 style='margin:0'>{e(head['title'])}</h2>",
             f"<p style='color:#8a8fa3'>{KIND_NAMES.get(kind, kind)} · {len(vids)} video(s) made from this research</p>"]
    if head.get("about"):
        parts.append(f"<p>{e(head['about'][:500])}</p>")
    on_file = max((v["evidence"] for v in vids), default=0)
    parts.append(f"<p><b>{on_file} pieces of evidence on file</b> (all saved in the database, so a new video "
                 "starts with everything found so far).</p><h3>Videos</h3>")
    for v in vids:
        parts.append(f"<p><b>{e(v['project_id'])}</b> {e(v['title'])}<br>"
                     f"<span style='color:#8a8fa3'>{e(v['where'])} · {v['ticked']} of {v['evidence']} pieces of "
                     "evidence ticked" + (f" · started from {e(v['based_on'])}" if v["based_on"] else "") + "</span>")
        if v["stories"]:
            parts.append("<br>Stories written: " + "; ".join(
                (f"<b style='color:#27ae60'>✔ {e(t)}</b>" if i == v["chosen"] else e(t))
                for i, t in enumerate(v["stories"])))
        parts.append("</p>")
    return "".join(parts)


def new_video_from(project_id: str, mode: str) -> Episode:
    """mode 'evidence': same research, nothing ticked, so you can pick different evidence.
    mode 'story': same ticks and the same three stories; you pick another one."""
    src = Episode.load(project_id)
    row = db.one("SELECT * FROM project WHERE project_id=?", (project_id,))
    kind, sid = subject_of(row) or (None, None)
    new = Episode.create(next_id(), src.title, row.get("arc_id"), src.claim_ids)
    db.execute("UPDATE project SET subject_type=?, subject_id=? WHERE project_id=?", (kind, sid, new.project_id))
    info = new.info
    info["based_on"] = project_id
    write_json(new.path("episode.json"), info)
    packet = read_json(src.path("research.json")) or {}
    if mode == "evidence":
        for e in packet.get("evidence", []):
            e["include"] = False
            e["new"] = False
        packet["new_ids"] = []
        packet["project_id"] = new.project_id
        write_json(new.path("research.json"), packet)
    elif mode == "story":
        packet["project_id"] = new.project_id
        write_json(new.path("research.json"), packet)
        for f in ("research.md",):
            if src.path(f).exists():
                shutil.copy2(src.path(f), new.path(f))
        new.record("research", "approved", f"same evidence as {project_id}")
        stories = read_json(src.path("stories.json")) or {}
        if stories:
            if not stories.get("set_id"):  # older story sets: give the original one an ID too
                stories["set_id"] = f"{project_id}-{utc_now()}"
                write_json(src.path("stories.json"), stories)
            stories.pop("chosen", None)
            write_json(new.path("stories.json"), stories)
    else:
        raise ValueError(f"Unknown mode {mode}")
    return new
