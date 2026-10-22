"""Render Mode: pause memory-hungry programs (Steam, Discord, Wallpaper Engine...)
while the GPU works, then bring them back.

Programs are SUSPENDED, never killed: they keep their windows and state and
carry on exactly where they were. The list of what was paused is saved to disk
first, so if the PC or the app crashes, "Resume all" still brings them back.
A process is only resumed if it's the same one (same PID and start time).
"""

from __future__ import annotations

import subprocess
from typing import Any

from .config import Paths, settings
from .util import read_json, utc_now, write_json


def _psutil():
    import psutil
    return psutil


def scan(min_mb: int = 150) -> list[dict[str, Any]]:
    """Programs grouped by name with their total memory, biggest first."""
    psutil = _psutil()
    never = {n.lower() for n in settings()["rendermode"]["never_touch"]}
    suggested = {n.lower() for n in settings()["rendermode"]["suggested"]}
    groups: dict[str, dict[str, Any]] = {}
    for p in psutil.process_iter(["pid", "name", "memory_info", "status"]):
        try:
            name = p.info["name"] or ""
            mem = p.info["memory_info"].rss if p.info["memory_info"] else 0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not name or name.lower() in never:
            continue
        g = groups.setdefault(name, {"name": name, "pids": [], "mb": 0.0, "suspended": False,
                                     "suggested": name.lower() in suggested})
        g["pids"].append(p.info["pid"])
        g["mb"] += mem / 1_048_576
        if p.info["status"] == psutil.STATUS_STOPPED:
            g["suspended"] = True
    out = [g for g in groups.values() if g["mb"] >= min_mb or g["suggested"]]
    for g in out:
        g["mb"] = round(g["mb"])
    return sorted(out, key=lambda g: -g["mb"])


def suggested_names() -> list[str]:
    return [g["name"] for g in scan(0) if g["suggested"]]


def suspend(names: list[str]) -> list[dict[str, Any]]:
    psutil = _psutil()
    never = {n.lower() for n in settings()["rendermode"]["never_touch"]}
    state = read_json(Paths().rendermode_state, {"suspended": []}) or {"suspended": []}
    done = []
    wanted = {n.lower() for n in names if n.lower() not in never}
    for p in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if (p.info["name"] or "").lower() not in wanted:
                continue
            entry = {"pid": p.info["pid"], "name": p.info["name"],
                     "create_time": p.info["create_time"], "at": utc_now()}
            state["suspended"].append(entry)       # write the record BEFORE acting
            write_json(Paths().rendermode_state, state)
            p.suspend()
            done.append(entry)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return done


def resume_all() -> list[dict[str, Any]]:
    psutil = _psutil()
    state = read_json(Paths().rendermode_state, {"suspended": []}) or {"suspended": []}
    resumed, left = [], []
    for entry in state["suspended"]:
        try:
            p = psutil.Process(entry["pid"])
            if abs(p.create_time() - entry["create_time"]) > 1:
                continue  # PID reused by another program: leave it alone
            p.resume()
            resumed.append(entry)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            left.append(entry)
    write_json(Paths().rendermode_state, {"suspended": left})
    return resumed


def gpu_memory() -> dict[str, Any] | None:
    """VRAM use from nvidia-smi (ships with the NVIDIA driver)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True,
                             timeout=5, creationflags=0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0)
        name, used, total, util = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
        return {"name": name, "used_mb": int(used), "total_mb": int(total), "util": int(util)}
    except Exception:  # noqa: BLE001 - no NVIDIA driver here
        return None


def ram() -> dict[str, float]:
    vm = _psutil().virtual_memory()
    return {"used_gb": round(vm.used / 1e9, 1), "total_gb": round(vm.total / 1e9, 1)}
