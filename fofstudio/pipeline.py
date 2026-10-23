"""Stage rules: what can run, approving, skipping, rejecting, and what a change invalidates."""

from __future__ import annotations

from typing import Any

from .episode import Episode
from .stages import BY_NAME, STAGES
from .stages.base import BLOCK, Check, Context, Stage
from .util import StageError

DONE = ("approved",)


def stage(name: str) -> Stage:
    if name not in BY_NAME:
        raise KeyError(f"Unknown stage '{name}'. Stages: {', '.join(BY_NAME)}")
    return BY_NAME[name]


def is_satisfied(ep: Episode, name: str) -> bool:
    return ep.stage_status(name)["status"] in DONE


def missing_requirements(ep: Episode, name: str) -> list[str]:
    return [r for r in stage(name).requires if not is_satisfied(ep, r)]


def dependents(name: str) -> list[str]:
    """Every stage that depends on `name`, directly or not, in pipeline order."""
    found: set[str] = set()
    changed = True
    while changed:
        changed = False
        for s in STAGES:
            if s.hidden:
                continue
            if s.name not in found and (name in s.requires or found & set(s.requires)):
                found.add(s.name)
                changed = True
    return [s.name for s in STAGES if s.name in found]


def invalidate_after(ep: Episode, name: str) -> list[str]:
    """When a stage is redone, approvals that came after it no longer hold."""
    reset = []
    for d in dependents(name):
        st = ep.stage_status(d)["status"]
        if st in ("approved", "awaiting_approval"):
            ep.record(d, "reset", f"{name} changed; look at this again")
            reset.append(d)
    return reset


# What each stage leaves in the episode folder (files or whole folders), for Clear.
OUTPUTS = {
    "research": ["research.json", "research.md"],
    "stories": ["stories.json"],
    "script": ["script.md"],
    "storyboard": ["storyboard.json", "images"],
    "video_plan": ["video/plan.json"],
    "video": ["video"],
    "narration": ["audio/narration.json", "audio/narration"],
    "captions": ["captions"],
    "music": ["audio/music"],
    "production": ["production.json"],
    "preview": ["render/preview.mp4", "render/preview.json"],
    "render": ["render"],
    "package": ["publish"],
    "upload": [],   # what's on YouTube stays there
}
KEEP = {"publish/upload.json"}
CLEARED = "cleared"   # a step you cleared reads as not started (the history keeps the event)   # the record of an upload is never deleted


def clear_plan(name: str) -> list[str]:
    """The stage and everything built from it, in order (what Clear would remove)."""
    out = [name] + dependents(name)
    if "video" in out or "narration" in out:
        out.append("preview")
    return [s.name for s in STAGES if s.name in out and s.name != "upload"]


def clear(ep: Episode, name: str) -> list[str]:
    """Start over from this step: delete its files and everything made after it, reset their status and
    drop their waiting jobs. Research, ticks and earlier steps are kept. Returns the labels cleared."""
    import shutil

    from . import db
    names = clear_plan(name)
    marks = ",".join("?" * len(names))
    running = db.rows(f"SELECT stage FROM job WHERE project_id=? AND status='running' AND stage IN ({marks})",
                      (ep.project_id, *names))
    if running:
        raise StageError(f"{stage(running[0]['stage']).label} is running right now. Cancel it (top bar) or wait "
                         "for it to finish, then Clear.")
    from .util import utc_now
    db.execute(f"UPDATE job SET status='cancelled', finished_at=? WHERE project_id=? AND "
               f"status='queued' AND stage IN ({marks})", (utc_now(), ep.project_id, *names))
    root = ep.folder.resolve()
    for n in names:
        for rel in OUTPUTS.get(n, []):
            p = (ep.folder / rel).resolve()
            if root not in p.parents:      # never outside the episode folder
                continue
            if p.is_dir():
                for child in list(p.iterdir()):
                    if ep.rel(child) in KEEP:
                        continue
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
            elif p.exists() and ep.rel(p) not in KEEP:
                p.unlink()
        ep.record(n, "reset", f"{CLEARED} (started over from {stage(name).label})")
    return [stage(n).label for n in names if not stage(n).hidden]


def checks(ep: Episode, name: str) -> list[Check]:
    try:
        return stage(name).check(ep)
    except StageError as exc:
        return [Check(BLOCK, str(exc))]
    except FileNotFoundError as exc:
        return [Check(BLOCK, f"Missing file: {exc}")]


def approve(ep: Episode, name: str, note: str = "") -> list[Check]:
    missing = missing_requirements(ep, name)
    if missing:
        raise StageError(f"Approve {', '.join(missing)} first.")
    results = checks(ep, name)
    blocking = [c for c in results if c.level == BLOCK]
    if blocking:
        raise StageError("Can't approve yet:\n- " + "\n- ".join(c.message for c in blocking))
    ep.record(name, "approved", note)
    return results


def skip(ep: Episode, name: str, note: str = "") -> None:
    if not stage(name).optional:
        raise StageError(f"{stage(name).label} can't be skipped.")
    ep.record(name, "approved", f"SKIPPED {note}".strip())
    invalidate_after(ep, name)


def reject(ep: Episode, name: str, note: str = "") -> None:
    ep.record(name, "rejected", note)


def overview(ep: Episode) -> list[dict[str, Any]]:
    out = []
    for s in STAGES:
        if s.hidden:
            continue
        st = ep.stage_status(s.name)
        out.append({"name": s.name, "label": s.label, "optional": s.optional,
                    "engine": s.engine, "status": st["status"], "note": st.get("note") or "",
                    "at": st.get("at"), "missing": missing_requirements(ep, s.name),
                    "skipped": (st.get("note") or "").startswith("SKIPPED")})
    return out


def next_stage(ep: Episode) -> str | None:
    for s in STAGES:
        if s.hidden:
            continue
        if not is_satisfied(ep, s.name) and not missing_requirements(ep, s.name):
            return s.name
    return None


def run_now(ep: Episode, name: str, options: dict[str, Any] | None = None, log=print,
            progress=lambda t, p=None: None, cancelled=lambda: False) -> list[Check]:
    """Run a stage in this process (the worker uses this; so do tests and the CLI)."""
    missing = missing_requirements(ep, name)
    if missing:
        raise StageError(f"Approve {', '.join(missing)} first.")
    ep.record(name, "running")
    if not stage(name).hidden:
        invalidate_after(ep, name)
    ctx = Context(ep, options or {}, log=log, progress=progress, cancelled=cancelled)
    try:
        stage(name).run(ctx)
    except StageError as exc:
        ep.record(name, "cancelled" if str(exc) == "Cancelled." else "failed", str(exc)[:2000])
        raise
    except Exception as exc:
        ep.record(name, "failed", f"{type(exc).__name__}: {exc}"[:2000])
        raise
    if stage(name).hidden:
        ep.record(name, "approved", "done")
        return []
    results = checks(ep, name)
    ep.record(name, "awaiting_approval",
              "; ".join(c.message for c in results if c.level == BLOCK)[:1000])
    return results
