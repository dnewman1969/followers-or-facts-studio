from pathlib import Path

from PIL import Image

from fofstudio import jobs, media, pipeline, rendermode
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
    job = jobs.enqueue("Q1", "research", {"fetch_sources": False, "find_quotes": False})
    jobs.worker_loop(once=True)
    assert [j for j in jobs.jobs() if j["job_id"] == job][0]["status"] == "done"
    assert ep.stage_status("research")["status"] == "awaiting_approval"

    pipeline.approve(ep, "research")
    def boom(self, *a, **k):
        raise RuntimeError("model fell over")
    fakes.setattr(Ollama, "chat_json", boom)
    failing = jobs.enqueue("Q1", "script")
    jobs.worker_loop(once=True)
    row = [j for j in jobs.jobs() if j["job_id"] == failing][0]
    assert row["status"] == "failed" and "model fell over" in row["error"]
    assert jobs.control()["paused"] == 1


def test_rendermode_scan_lists_programs(data):
    found = rendermode.scan(min_mb=0)
    assert found and all("mb" in g for g in found)
    assert rendermode.ram()["total_gb"] > 0
