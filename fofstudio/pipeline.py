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
