
from PIL import Image

from fofstudio import jobs, pipeline, rendermode
from fofstudio.engines.render import AudioCue, Segment, Timeline, render
from fofstudio.episode import Episode

from .conftest import tone


def test_render_engine_stills_clip_music(tmp_path, data):
    imgs = []
    for i, color in enumerate([(200, 50, 50), (50, 200, 50), (50, 50, 200)]):
        p = tmp_path / f"{i}.png"
        Image.new("RGB", (800, 450), color).save(p)
        imgs.append(p)
    import subprocess
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=416x240:rate=16:duration=2", "-pix_fmt", "yuv420p", str(clip)], check=True)
    tone(tmp_path / "n1.wav", 2.0)
    tone(tmp_path / "n2.wav", 1.5)
    tone(tmp_path / "m.wav", 3.0, 440)
    tl = Timeline([Segment(imgs[0], 3, camera="zoom_in"), Segment(clip, 3, kind="clip"),
                   Segment(imgs[1], 2.5, camera="pan_left", transition="wipe_left"),
                   Segment(imgs[2], 2, camera="static")],
                  [AudioCue(tmp_path / "n1.wav", 0.3), AudioCue(tmp_path / "n2.wav", 5.0)],
                  music=tmp_path / "m.wav", width=640, height=360, fps=15)
    result = render(tl, tmp_path / "out.mp4", encoder="libx264")
    assert abs(result["seconds"] - tl.total) < 0.25
    assert result["has_audio"]


def test_queue_runs_a_job_and_pauses_on_failure(data, fakes):
    from fofstudio.llm import Ollama
    ep = Episode.create("Q1", "Queue test", "A-Y2K-FEAR-INDUSTRY")
    fakes.setattr(Ollama, "chat_json", lambda *a, **k: {"excerpts": []})
    from fofstudio import sources
    fakes.setattr(sources, "fetch_source", lambda sid, refresh=False: {"source_id": sid, "ok": False})
    from fofstudio import config
    config.settings()["research"]["use_wayback"] = False
    job = jobs.enqueue("Q1", "research", {"database_only": True})
    jobs.worker_loop(once=True)
    assert [j for j in jobs.jobs() if j["job_id"] == job][0]["status"] == "done"
    assert ep.stage_status("research")["status"] == "awaiting_approval"
    from fofstudio.stages import research as rs
    from fofstudio.util import read_json
    rs.set_include(ep, [e["id"] for e in read_json(ep.path("research.json"))["evidence"]], True)
    pipeline.approve(ep, "research")
    def boom(self, *a, **k):
        raise RuntimeError("model fell over")
    fakes.setattr(Ollama, "chat_json", boom)
    failing = jobs.enqueue("Q1", "stories")
    jobs.worker_loop(once=True)
    row = [j for j in jobs.jobs() if j["job_id"] == failing][0]
    assert row["status"] == "failed" and "model fell over" in row["error"]
    assert jobs.control()["paused"] == 1


def test_rendermode_scan_lists_programs(data):
    found = rendermode.scan(min_mb=0)
    assert found and all("mb" in g for g in found)
    assert rendermode.ram()["total_gb"] > 0


def test_speed_test_times_what_it_can_and_reports_the_rest(data, monkeypatch):
    """Ollama and ComfyUI are fake here: the AI step reports why it couldn't run; the 2.5D move and the estimate
    still come out, and the Video page uses a measured Wan time once there is one."""
    from fofstudio import speedtest, subjects
    from fofstudio.episode import Episode
    from fofstudio.stages import video
    from fofstudio import pipeline
    monkeypatch.setattr(speedtest, "llm_speed", lambda url, m: {"model": m, "tokens_per_second": 30.0,
                                                                "words_per_second": 20.0, "load_seconds": 2.0,
                                                                "total_seconds": 12.0})
    import fofstudio.comfy as comfy

    def no_comfy(*a, **k):
        raise RuntimeError("ComfyUI isn't running (test)")
    monkeypatch.setattr(comfy, "run_template", no_comfy)
    b = subjects.breakdown("story", "A-Y2K-FEAR-INDUSTRY")
    ep = Episode.create("S09E09", b["title"], "A-Y2K-FEAR-INDUSTRY", b["claim_ids"])
    pipeline.run_now(ep, "speedtest", {"video": False})
    r = speedtest.load()
    assert r["steps"]["models"][0]["tokens_per_second"] == 30.0
    assert r["steps"]["parallax"]["seconds_per_5s_clip"] > 0
    assert any("Picture" in p for p in r["problems"])
    assert "script_minutes" in r["estimate_10_min"]
    reports = list(speedtest.results_path().parent.glob("speed-test-*.txt"))
    assert reports and "A 10-minute video" in reports[0].read_text()
    assert video.MINUTES_PER_CLIP == speedtest.minutes_per_clip(video.MINUTES_PER_CLIP)
    r["steps"]["wan_clip"] = {"minutes": 9.5}
    speedtest.write_json(speedtest.results_path(), r)
    assert speedtest.minutes_per_clip(6.0) == 9.5
