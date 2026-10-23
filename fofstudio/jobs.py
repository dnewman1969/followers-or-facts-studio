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
# Why jobs could sit at "queued" forever before: the lock file of a worker that was killed (PC shut
# down, crash) stayed behind, and after a restart Windows gives its process number to some other
# program, so the app thought the worker was still running and never started a new one. A worker that
# crashed on start-up also vanished without a word. Now the app checks that the process really is our
# worker, the worker keeps its lock fresh, start-up errors go to logs/worker-console.log, and if the
# separate worker won't start the job runs inside the Studio instead.
LOCK_FRESH_SECONDS = 60
_thread: threading.Thread | None = None
_spawned: subprocess.Popen | None = None
_counted: subprocess.Popen | None = None
_spawn_failures = 0
_last_spawn = 0.0


def _is_our_worker(pid: int | None) -> bool | None:
    """True/False if we can tell whether pid is a Followers or Facts worker, None if we can't tell."""
    if not pid:
        return False
    if pid == os.getpid():
        return bool(_thread and _thread.is_alive())
    try:
        import psutil
    except ImportError:
        return None
    try:
        proc = psutil.Process(pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            return False
        args = [a.lower() for a in proc.cmdline()]
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, OSError):
        return None
    # "python -m fofstudio worker ..." (the background worker), never the window itself
    return "worker" in args and any(a == "fofstudio" or a.endswith("fofstudio") for a in args)


def _alive(pid: int | None) -> bool:
    ours = _is_our_worker(pid)
    if ours is not None:
        return ours
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        return True


def worker_running() -> int | None:
    """The worker's process number if one is really running (in the background or inside the Studio)."""
    if _thread and _thread.is_alive():
        return os.getpid()
    lock = Paths().worker_lock
    if not lock.exists():
        return None
    try:
        pid = int(lock.read_text().strip())
        age = time.time() - lock.stat().st_mtime
    except (ValueError, OSError):
        return None
    ours = _is_our_worker(pid) if pid != os.getpid() else False
    if ours is None:  # can't look at the process: trust the lock only while the worker keeps it fresh
        ours = age < LOCK_FRESH_SECONDS
    if not ours:
        try:
            lock.unlink()   # a leftover from a worker that's gone
        except OSError:
            pass
        return None
    return pid


def worker_problem() -> str:
    """The last lines a background worker printed if it died while starting (else empty)."""
    if _spawned is None or _spawned.poll() is None:
        return ""
    path = Paths().logs / "worker-console.log"
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError:
        return "The worker stopped straight after starting."
    return "\n".join(lines[-6:]) or "The worker stopped straight after starting."


def start_worker(force: bool = False) -> int:
    """Start the background worker if it isn't already running. Returns its PID.
    If the separate worker process won't start (twice), run the queue inside the Studio instead."""
    global _spawned, _spawn_failures, _last_spawn, _counted
    pid = worker_running()
    if pid:
        return pid
    if _spawned is not None and _spawned.poll() is not None and _spawned is not _counted:
        _counted = _spawned
        if time.time() - _last_spawn < 30:
            _spawn_failures += 1   # the last one died straight after starting
    if _spawned is not None and _spawned.poll() is None and time.time() - _last_spawn < 20:
        return _spawned.pid    # still starting up; give it a moment to write its lock
    if _spawn_failures >= 2 or os.environ.get("FOF_WORKER_IN_APP"):
        return start_thread_worker()
    if not force and time.time() - _last_spawn < 5:
        return _spawned.pid if _spawned else 0
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("python.exe"):
        pythonw = exe[:-10] + "pythonw.exe"
        if Path(pythonw).exists():
            exe = pythonw
    logs = Paths().ensure().logs
    console = open(logs / "worker-console.log", "a", encoding="utf-8")   # start-up errors land here
    console.write(f"\n--- starting worker {utc_now()} ({exe})\n")
    console.flush()
    kwargs: dict[str, Any] = {"cwd": str(REPO), "stdin": subprocess.DEVNULL, "stdout": console, "stderr": console}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    env = dict(os.environ)
    env["FOF_DATA"] = str(Paths().root)   # the worker uses exactly the same data folder as the window
    kwargs["env"] = env
    try:
        _spawned = subprocess.Popen([exe, "-m", "fofstudio", "worker"], **kwargs)
    except OSError as exc:
        console.write(f"Couldn't start the worker: {exc}\n")
        _spawn_failures += 1
        return start_thread_worker() if _spawn_failures >= 2 else 0
    finally:
        console.close()
    _last_spawn = time.time()
    return _spawned.pid


def start_thread_worker() -> int:
    """Run the queue on a thread inside the Studio (jobs stop if you close the window)."""
    global _thread
    if _thread and _thread.is_alive():
        return os.getpid()
    _thread = threading.Thread(target=worker_loop, kwargs={"in_app": True}, daemon=True, name="fof-worker")
    _thread.start()
    return os.getpid()


def worker_mode() -> str:
    if _thread and _thread.is_alive():
        return "inside the Studio"
    return "background" if worker_running() else "stopped"


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
        _after(job, ep, options)
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


def _after(job: dict[str, Any], ep: Episode, options: dict[str, Any]) -> None:
    """Follow-on jobs: a finished final render is uploaded privately (if you're signed in and want that)."""
    if job["stage"] != "render" or options.get("draft") or not settings()["youtube"].get("auto_upload"):
        return
    from . import youtube
    if not youtube.account():
        log.info("Render finished; not uploading automatically because you're not signed in to YouTube.")
        return
    try:
        enqueue(job["project_id"], "autopublish")
        log.info("Render finished; queued the automatic private upload.")
    except StageError as exc:
        log.info("Couldn't queue the automatic upload: %s", exc)


def worker_loop(once: bool = False, in_app: bool = False) -> None:
    paths = Paths().ensure()
    if not in_app and worker_running():
        print("A worker is already running.")
        return
    if not in_app:
        paths.worker_lock.write_text(str(os.getpid()))
    if not logging.getLogger().handlers or in_app:
        handler = logging.FileHandler(paths.logs / "worker.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
    log.info("worker started (pid %s%s)", os.getpid(), ", inside the Studio" if in_app else "")
    stop = threading.Event()

    def keep_lock_fresh() -> None:
        while not stop.wait(10):
            try:
                paths.worker_lock.write_text(str(os.getpid()))
            except OSError:
                pass
    if not in_app:
        threading.Thread(target=keep_lock_fresh, daemon=True).start()
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
            time.sleep(2)
    except Exception:  # noqa: BLE001 - never die silently
        log.error("worker crashed:\n%s", traceback.format_exc())
        raise
    finally:
        stop.set()
        if not in_app:
            try:
                if paths.worker_lock.read_text().strip() == str(os.getpid()):
                    paths.worker_lock.unlink()
            except OSError:
                pass
