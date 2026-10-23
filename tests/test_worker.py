"""The background worker: jobs must never sit at "queued" forever."""

import subprocess
import sys
import time

import pytest

from fofstudio import jobs
from fofstudio.config import Paths
from fofstudio.episode import Episode
from fofstudio.util import read_json
from tests.test_pipeline import episode  # noqa: F401 - shared fixture


@pytest.fixture()
def worker_state(monkeypatch):
    """Each test starts with a clean worker state and stops any worker it started."""
    monkeypatch.setattr(jobs, "_thread", None)
    monkeypatch.setattr(jobs, "_spawned", None)
    monkeypatch.setattr(jobs, "_spawn_failures", 0)
    monkeypatch.setattr(jobs, "_last_spawn", 0.0)
    monkeypatch.setattr(jobs, "_counted", None)
    yield
    proc = jobs._spawned
    if proc is not None and proc.poll() is None:
        proc.terminate()
        proc.wait(10)


def _wait_done(job_id, seconds=40):
    end = time.time() + seconds
    while time.time() < end:
        row = next(j for j in jobs.jobs() if j["job_id"] == job_id)
        if row["status"] not in ("queued", "running"):
            return row
        time.sleep(0.5)
    return next(j for j in jobs.jobs() if j["job_id"] == job_id)


def test_leftover_lock_from_another_program_is_ignored(data, worker_state):
    """After a restart, the old lock can name a process number Windows gave to some other program."""
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        Paths().ensure().worker_lock.write_text(str(other.pid))
        assert jobs.worker_running() is None
        assert not Paths().worker_lock.exists()
    finally:
        other.terminate()


def test_background_worker_picks_up_a_job(data, worker_state):
    ep = Episode.create("W1", "Worker test", "A-Y2K-FEAR-INDUSTRY")
    job = jobs.enqueue(ep.project_id, "selftest")
    jobs.start_worker(force=True)
    row = _wait_done(job)
    assert row["status"] == "done", (row, jobs.worker_problem())
    assert read_json(ep.path("worker-test.json"))["ok"]
    assert jobs.worker_mode() == "background"


def test_paused_queue_does_not_hide_a_dead_running_job(data, worker_state):
    """A job left 'running' by a worker that died is marked interrupted, so the queue isn't blocked by it."""
    ep = Episode.create("W2", "Worker test", "A-Y2K-FEAR-INDUSTRY")
    job = jobs.enqueue(ep.project_id, "selftest")
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        from fofstudio import db
        db.execute("UPDATE job SET status='running', pid=?, started_at='2020-01-01T00:00:00+00:00', "
                   "heartbeat_at='2020-01-01T00:00:00+00:00' WHERE job_id=?", (other.pid, job))
        assert jobs.recover_stale() == [job]
    finally:
        other.terminate()


def test_worker_that_wont_start_falls_back_to_running_inside_the_studio(data, worker_state, monkeypatch):
    ep = Episode.create("W3", "Worker test", "A-Y2K-FEAR-INDUSTRY")
    job = jobs.enqueue(ep.project_id, "selftest")
    broken = Paths().root / "broken-python.py"
    broken.write_text("import sys; print('ModuleNotFoundError: No module named cv2'); sys.exit(1)\n")
    # a "python" that dies straight away, like a worker missing a package
    monkeypatch.setattr(jobs.sys, "executable", sys.executable)
    real_popen = subprocess.Popen

    def failing_popen(cmd, **kw):
        return real_popen([sys.executable, str(broken)], **kw)
    monkeypatch.setattr(jobs.subprocess, "Popen", failing_popen)
    for _ in range(3):
        jobs.start_worker(force=True)
        if jobs._spawned is not None:
            jobs._spawned.wait(10)
        if jobs.worker_mode() == "inside the Studio":
            break
    assert "cv2" in jobs.worker_problem() or jobs.worker_mode() == "inside the Studio"
    jobs.start_worker()
    assert jobs.worker_mode() == "inside the Studio"
    assert _wait_done(job)["status"] == "done"


def test_clear_starts_a_step_over(episode):
    """Clear removes this step's work and everything after it, keeps research and the earlier steps."""
    from fofstudio import pipeline
    from tests.test_pipeline import research_and_story
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    assert ep.storyboard()["scenes"] and any(ep.path("images").iterdir())
    cleared = pipeline.clear(ep, "script")
    assert "Script" in cleared and "Storyboard" in cleared
    assert not ep.path("script.md").exists() and not ep.storyboard()
    assert not any(p.is_file() for p in ep.path("images").rglob("*"))
    assert ep.stage_status("script")["status"] == "not_started"
    assert ep.stage_status("stories")["status"] == "approved"          # earlier steps untouched
    assert ep.path("research.json").exists() and ep.path("stories.json").exists()
    pipeline.run_now(ep, "script")                                     # and the step runs again
    assert ep.path("script.md").exists()


def test_clear_refuses_while_running(episode):
    from fofstudio import db, pipeline
    from fofstudio.util import StageError
    from tests.test_pipeline import research_and_story
    ep = episode
    research_and_story(ep)
    job = jobs.enqueue(ep.project_id, "script")
    db.execute("UPDATE job SET status='running' WHERE job_id=?", (job,))
    with pytest.raises(StageError, match="running"):
        pipeline.clear(ep, "stories")
