"""The job queue and the background worker (patterns from Nimrod's Tower).

* Jobs live in the database, so closing the app window doesn't stop them.
* One job runs at a time (a database rule), because a 12 GB card can't hold two models.
* Before a ComfyUI job the worker unloads Ollama's models, and the other way round.
* A failed job PAUSES the queue: you look at what went wrong before anything else runs.
* A job whose heartbeat goes quiet for 90 s is marked interrupted, never silently rerun.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db, pipeline
from .config import REPO, Paths, settings
from .episode import Episode
from .util import StageError, utc_now

HEARTBEAT_SECONDS = 15
STALE_SECONDS = 90
log = logging.getLogger("fofstudio.worker")


# ---------------------------------------------------------------- queue operations
def enqueue(project_id: str, stage: str, options: dict[str, Any] | None = None) -> int:
    pipeline.stage(stage)
    ep = Episode.load(project_id)
    missing = pipeline.missing_requirements(ep, stage)
    if missing:
        raise StageError(f"Approve {', '.join(missing)} first.")
    with db.transaction() as con:
        dup = con.execute("SELECT job_id FROM job WHERE project_id=? AND stage=? AND status IN "
                          "('queued','running')", (project_id, stage)).fetchone()
        if dup:
            raise StageError(f"{stage} is already queued for {project_id}.")
        pos = con.execute("SELECT COALESCE(MAX(position),0)+1 FROM job").fetchone()[0]
        cur = con.execute(
            "INSERT INTO job(project_id,stage,gpu,status,options_json,position,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (project_id, stage, int(pipeline.stage(stage).gpu), "queued",
             json.dumps(options or {}), pos, utc_now()))
        job_id = cur.lastrowid
    ep.record(stage, "queued")
    return job_id


def jobs(limit: int = 200) -> list[dict[str, Any]]:
    return db.rows("SELECT * FROM job ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'queued' "
                   "THEN 1 ELSE 2 END, position, job_id DESC LIMIT ?", (limit,))


def cancel(job_id: int) -> None:
    with db.transaction() as con:
        row = con.execute("SELECT status, project_id, stage FROM job WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return
        if row["status"] == "queued":
            con.execute("UPDATE job SET status='cancelled', finished_at=? WHERE job_id=?", (utc_now(), job_id))
            con.execute("INSERT INTO stage_event(project_id,stage,status,note,at) VALUES (?,?,?,?,?)",
                        (row["project_id"], row["stage"], "cancelled", "removed from queue", utc_now()))
        elif row["status"] == "running":
            con.execute("UPDATE job SET cancel_requested=1 WHERE job_id=?", (job_id,))


def move(job_id: int, direction: int) -> None:
    with db.transaction() as con:
        waiting = list(con.execute("SELECT job_id, position FROM job WHERE status='queued' "
                                   "ORDER BY position, job_id"))
        idx = next((i for i, r in enumerate(waiting) if r["job_id"] == job_id), None)
        if idx is None or not 0 <= idx + direction < len(waiting):
            return
        a, b = waiting[idx], waiting[idx + direction]
        con.execute("UPDATE job SET position=? WHERE job_id=?", (b["position"], a["job_id"]))
        con.execute("UPDATE job SET position=? WHERE job_id=?", (a["position"], b["job_id"]))


def control() -> dict[str, Any]:
    return db.one("SELECT * FROM queue_control WHERE id=1") or {"paused": 0, "reason": None}


def set_paused(paused: bool, reason: str | None = None) -> None:
    db.execute("UPDATE queue_control SET paused=?, reason=? WHERE id=1", (int(paused), reason))


# ---------------------------------------------------------------- worker process
def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        return True


def worker_running() -> int | None:
    lock = Paths().worker_lock
    if not lock.exists():
        return None
    try:
        pid = int(lock.read_text().strip())
    except ValueError:
        return None
    return pid if _alive(pid) and pid != os.getpid() else None


def start_worker() -> int:
    """Start the background worker if it isn't already running. Returns its PID."""
    pid = worker_running()
    if pid:
        return pid
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("python.exe"):
        pythonw = exe[:-10] + "pythonw.exe"
        if Path(pythonw).exists():
            exe = pythonw
    kwargs: dict[str, Any] = {"cwd": str(REPO), "stdin": subprocess.DEVNULL,
                              "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([exe, "-m", "fofstudio", "worker"], **kwargs)
    return proc.pid


def recover_stale() -> list[int]:
    """Mark jobs whose worker died as interrupted (never rerun them silently)."""
    found = []
    for job in db.rows("SELECT * FROM job WHERE status='running'"):
        beat = job["heartbeat_at"] or job["started_at"]
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(beat)).total_seconds() if beat else 1e9
        if age > STALE_SECONDS and not _alive(job["pid"]):
            with db.transaction() as con:
                con.execute("UPDATE job SET status='interrupted', finished_at=?, error=? WHERE job_id=?",
                            (utc_now(), "The worker stopped while this was running.", job["job_id"]))
                con.execute("INSERT INTO stage_event(project_id,stage,status,note,at) VALUES (?,?,?,?,?)",
                            (job["project_id"], job["stage"], "interrupted",
                             "The worker stopped (PC asleep, crash or closed). Run it again.", utc_now()))
            found.append(job["job_id"])
    if found:
        set_paused(True, "A job was interrupted. Look at it, then press Resume.")
    return found


def _claim_next() -> dict[str, Any] | None:
    with db.transaction() as con:
        if con.execute("SELECT paused FROM queue_control WHERE id=1").fetchone()[0]:
            return None
        if con.execute("SELECT 1 FROM job WHERE status='running'").fetchone():
            return None
        row = con.execute("SELECT * FROM job WHERE status='queued' ORDER BY position, job_id "
                          "LIMIT 1").fetchone()
        if not row:
            return None
        con.execute("UPDATE job SET status='running', pid=?, started_at=?, heartbeat_at=? "
                    "WHERE job_id=?", (os.getpid(), utc_now(), utc_now(), row["job_id"]))
        return dict(row)


def _free_gpu_for(engine: str) -> None:
    from .comfy import Comfy
    from .llm import Ollama
    if engine in ("comfy", "ffmpeg", "cpu"):
        Ollama().unload_all()
    if engine == "ollama":
        Comfy().free_memory()


def run_job(job: dict[str, Any]) -> None:
    job_id = job["job_id"]
    stop = threading.Event()
    progress_text: dict[str, Any] = {"value": "", "pct": None, "written": 0.0}

    def beat() -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            db.execute("UPDATE job SET heartbeat_at=?, progress=?, progress_pct=? WHERE job_id=?",
                       (utc_now(), progress_text["value"][:500], progress_text["pct"], job_id))

    def progress(text: str, pct: float | None = None) -> None:
        """Shown live in the window: a line of text and, when known, a percentage."""
        progress_text["value"] = text
        if pct is not None:
            progress_text["pct"] = max(0, min(100, int(pct)))
        log.info(text)
        if time.time() - progress_text["written"] > 0.8:  # don't hammer the database
            progress_text["written"] = time.time()
            db.execute("UPDATE job SET heartbeat_at=?, progress=?, progress_pct=? WHERE job_id=?",
                       (utc_now(), text[:500], progress_text["pct"], job_id))

    def cancelled() -> bool:
        row = db.one("SELECT cancel_requested FROM job WHERE job_id=?", (job_id,))
        return bool(row and row["cancel_requested"])

    threading.Thread(target=beat, daemon=True).start()
    options = json.loads(job["options_json"] or "{}")
    stage = pipeline.stage(job["stage"])
    suspended = []
    try:
        ep = Episode.load(job["project_id"])
        _free_gpu_for(stage.engine)
        if stage.gpu and settings()["rendermode"]["auto_for_gpu_stages"]:
            from . import rendermode
            suspended = rendermode.suspend(rendermode.suggested_names())
        pipeline.run_now(ep, stage.name, options, log=log.info, progress=progress, cancelled=cancelled)
        db.execute("UPDATE job SET status='done', finished_at=?, progress=?, progress_pct=100 WHERE job_id=?",
                   (utc_now(), "Finished - waiting for your approval", job_id))
        if settings()["pipeline"]["auto_continue"]:
            log.info("auto_continue is on, but every stage still waits for your approval.")
    except Exception as exc:  # noqa: BLE001 - every failure is recorded and pauses the queue
        message = str(exc) if isinstance(exc, StageError) else f"{type(exc).__name__}: {exc}"
        status = "cancelled" if message == "Cancelled." else "failed"
        log.error("%s\n%s", message, traceback.format_exc())
        db.execute("UPDATE job SET status=?, finished_at=?, error=? WHERE job_id=?",
                   (status, utc_now(), message[:4000], job_id))
        if status == "failed":
            set_paused(True, f"{job['project_id']} {job['stage']} failed. Read the error, "
                             "fix it, then Resume.")
    finally:
        stop.set()
        if suspended:
            from . import rendermode
            rendermode.resume_all()


def worker_loop(once: bool = False) -> None:
    paths = Paths().ensure()
    if worker_running():
        print("A worker is already running.")
        return
    paths.worker_lock.write_text(str(os.getpid()))
    logging.basicConfig(filename=paths.logs / "worker.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log.info("worker started (pid %s)", os.getpid())
    try:
        recover_stale()
        idle_since = time.time()
        while True:
            job = _claim_next()
            if job:
                log.info("job %s: %s %s", job["job_id"], job["project_id"], job["stage"])
                run_job(job)
                idle_since = time.time()
                if once:
                    return
                continue
            if once:
                return
            # exit after 10 idle minutes; the app starts a new worker when needed
            if time.time() - idle_since > 600:
                log.info("idle; exiting")
                return
            time.sleep(3)
    finally:
        try:
            if paths.worker_lock.read_text().strip() == str(os.getpid()):
                paths.worker_lock.unlink()
        except OSError:
            pass
