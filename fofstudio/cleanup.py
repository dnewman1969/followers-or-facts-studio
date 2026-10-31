"""Starting over (Dave, 2026-10-30): "in the research window we need a clear all button so I can start a new research
project, it's mixing up too much research data. Also allow the user to delete any projects in the database under
the Researched tab in case they want to start over with that research project."

Two things pile up:
  * a video's own research files: its ticks, the agents' runs, look-ups, the claim checks, story ideas and
    everything made after research (stories, script, pictures...);
  * what the research agents FOUND: every research run saves the sources and quotes it finds to the database,
    linked to the claims, so the next research on the same claims starts with all of it.

Clear all (Research page) wipes the first for this video and, if you tick the box, the second for this video's
claims. Delete (Database → Researched) removes videos, their folders and their history, and (if you tick the
box) the agents' finds for their claims. Your original research database (the stories, claims, people and
sources you imported) is never deleted: you can always pick the same subject again and press OK. A video that's
working right now has to be stopped first.
"""

from __future__ import annotations

import shutil
from typing import Any

from . import db
from .config import Paths
from .episode import Episode
from .util import StageError, utc_now

EXTRA_FILES = ("lookup-results.json", "claim-check.json", "ideas.json", "worker-test.json")


def _running(project_id: str) -> None:
    job = db.one("SELECT stage FROM job WHERE project_id=? AND status='running'", (project_id,))
    if job:
        raise StageError(f"{project_id} is busy ({job['stage']}). Cancel it in the top bar or wait for it to finish, "
                         "then try again.")


def agent_finds(claim_ids: list[str]) -> list[str]:
    """Sources the research agents found (not from your original database) that are linked to these claims."""
    if not claim_ids:
        return []
    marks = ",".join("?" * len(claim_ids))
    return [r["source_id"] for r in db.rows(
        f"""SELECT DISTINCT s.source_id FROM source s JOIN claim_source cs ON cs.source_id = s.source_id
            WHERE cs.claim_id IN ({marks}) AND s.found_by = 'agent' ORDER BY s.source_id""", tuple(claim_ids))]


def remove_agent_finds(claim_ids: list[str]) -> dict[str, int]:
    """Unlink the agents' finds from these claims (and their quotes); a find no other claim uses is deleted."""
    ids = agent_finds(claim_ids)
    if not ids:
        return {"sources": 0, "quotes": 0, "deleted": 0}
    cmarks = ",".join("?" * len(claim_ids))
    quotes = deleted = 0
    with db.transaction() as con:
        for sid in ids:
            quotes += con.execute(f"DELETE FROM source_excerpt WHERE source_id=? AND (claim_id IN ({cmarks}) "
                                  "OR claim_id IS NULL)", (sid, *claim_ids)).rowcount
            con.execute(f"DELETE FROM claim_source WHERE source_id=? AND claim_id IN ({cmarks})", (sid, *claim_ids))
            still = con.execute("SELECT 1 FROM claim_source WHERE source_id=? LIMIT 1", (sid,)).fetchone() or \
                con.execute("SELECT 1 FROM source_excerpt WHERE source_id=? LIMIT 1", (sid,)).fetchone()
            if not still:
                con.execute("DELETE FROM source WHERE source_id=?", (sid,))
                deleted += 1
    return {"sources": len(ids), "quotes": quotes, "deleted": deleted}


def clear_research(ep: Episode, agent_finds_too: bool = False) -> dict[str, Any]:
    """Clear all on the Research page: this video starts its research again from nothing ticked, with the
    research step and everything after it cleared."""
    from . import pipeline
    _running(ep.project_id)
    cleared = pipeline.clear(ep, "research")
    for name in EXTRA_FILES:
        ep.path(name).unlink(missing_ok=True)
    out: dict[str, Any] = {"steps": cleared, "sources": 0, "quotes": 0, "deleted": 0}
    if agent_finds_too:
        out.update(remove_agent_finds(ep.claim_ids))
    ep.record("research", "reset", "Clear all: research started over"
              + (f"; {out['sources']} agent find(s) removed" if agent_finds_too else ""))
    return out


def delete_video(project_id: str) -> None:
    """Remove one video: its folder, its jobs and its history. What's already on YouTube stays there."""
    _running(project_id)
    ep = Episode.load(project_id)
    folder = ep.folder.resolve()
    root = Paths().episodes.resolve()
    with db.transaction() as con:
        for table in ("job", "stage_event", "project_claim"):
            con.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
        con.execute("DELETE FROM project WHERE project_id=?", (project_id,))
    if root in folder.parents and folder.exists():      # never anything outside the episodes folder
        shutil.rmtree(folder, ignore_errors=True)


def delete_research_project(kind: str, subject_id: str, agent_finds_too: bool = True) -> dict[str, Any]:
    """Delete every video made from this subject (Database → Researched), and the agents' finds for its
    claims if asked. The subject itself stays in the database, so you can research it again from scratch."""
    from . import researched
    vids = researched.videos_for(kind, subject_id)
    for v in vids:
        _running(v["project_id"])
    claims = sorted({c for v in vids for c in v["episode"].claim_ids})
    for v in vids:
        delete_video(v["project_id"])
    out: dict[str, Any] = {"videos": [v["project_id"] for v in vids], "sources": 0, "quotes": 0, "deleted": 0,
                           "at": utc_now()}
    if agent_finds_too:
        out.update(remove_agent_finds(claims))
    return out
