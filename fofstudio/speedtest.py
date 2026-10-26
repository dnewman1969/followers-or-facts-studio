"""Speed test: time every kind of work on this PC, so the length and GPU-time estimates use real numbers.

Queue → Speed test runs it as a job (the hidden stage `speedtest`). It times, one at a time:
  * each AI model the jobs use (Settings → models): words per second while writing, and load time
  * one storyboard picture (the second of two, so the model is already loaded)
  * optionally one Wan animated clip (adds about 10 minutes)
  * one 2.5D parallax move (depth estimated on the CPU) at the video size
  * Owlbert's voice: how many seconds of speech per second of work
Then it works out how long each step of a 10-minute video would take, writes
<data>/logs/speed-test-<date>.txt (send it to Claude) and keeps the numbers in logs/speed-test.json,
which the Video page's GPU-hours estimate uses from then on.
A step that can't run (ComfyUI closed, no voice installed) says why in the report; the rest still run.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from .config import Paths, settings
from .util import StageError, read_json, write_json

SAMPLE_PROMPT = ("Write about 200 words, in plain English, on why people in 1999 believed the Y2K computer bug "
                 "would end the world, and what really happened on January 1, 2000.")


def results_path() -> Path:
    return Paths().logs / "speed-test.json"


def load() -> dict[str, Any]:
    return read_json(results_path(), {}) or {}


def minutes_per_clip(default: float) -> float:
    """Measured minutes for one Wan clip on this PC, if the speed test timed one."""
    clip = (load().get("steps") or {}).get("wan_clip") or {}
    return float(clip.get("minutes") or default)


def llm_speed(url: str, model: str) -> dict[str, Any]:
    with requests.Session() as s:
        s.trust_env = False
        r = s.post(url + "/api/generate", json={
            "model": model, "prompt": SAMPLE_PROMPT, "stream": False, "think": False,
            "options": {"num_ctx": int(settings()["ollama"]["num_ctx"]), "num_predict": 320}}, timeout=900)
        r.raise_for_status()
        d = r.json()
    if d.get("error"):
        raise StageError(d["error"])
    tokens = int(d.get("eval_count") or 0)
    secs = int(d.get("eval_duration") or 0) / 1e9
    return {"model": model, "tokens_per_second": round(tokens / secs, 1) if secs else 0.0,
            "words_per_second": round(len((d.get("response") or "").split()) / secs, 1) if secs else 0.0,
            "load_seconds": round(int(d.get("load_duration") or 0) / 1e9, 1),
            "total_seconds": round(int(d.get("total_duration") or 0) / 1e9, 1)}


def _timed(fn) -> tuple[Any, float]:
    t0 = time.time()
    out = fn()
    return out, time.time() - t0


def run(ctx) -> None:
    from .comfy import Comfy, new_seed, run_template
    from .llm import JOBS, Ollama, model_for
    cfg = settings()
    logs = Paths().logs
    logs.mkdir(parents=True, exist_ok=True)
    work = logs / "speed-test-files"
    work.mkdir(exist_ok=True)
    steps: dict[str, Any] = {}
    problems: list[str] = []

    # 1. the local AI models
    url = cfg["ollama"]["url"].rstrip("/")
    models = sorted({model_for(j) for j in JOBS})
    steps["models"] = []
    for k, m in enumerate(models):
        ctx.check_cancel()
        ctx.progress(f"Timing the AI model {m} ({k + 1} of {len(models)})", 3 + 25 * k / max(1, len(models)))
        try:
            steps["models"].append(llm_speed(url, m))
        except Exception as exc:  # noqa: BLE001 - written in the report
            problems.append(f"AI model {m}: {exc}")
    Ollama().unload_all()

    # 2. a storyboard picture (twice: the first one includes loading the model)
    picture = None
    try:
        ctx.progress("Making a test picture (the first one loads the model)", 30)
        c = cfg["comfyui"]

        def one(n: int):
            return run_template("image_workflow", {
                "PROMPT": "A cozy cartoon professor's study with an old desk, a newspaper dated 1999 and a wall clock, "
                          "warm light", "SEED": new_seed(), "WIDTH": c["image_width"], "HEIGHT": c["image_height"],
                "FILENAME_PREFIX": "fof/speedtest/picture"}, work / f"picture-{n}", cancelled=ctx.cancelled)[0][0]
        _, first = _timed(lambda: one(1))
        ctx.progress("Making a second test picture (model already loaded)", 40)
        picture, second = _timed(lambda: one(2))
        steps["picture"] = {"seconds": round(second, 1), "first_seconds": round(first, 1),
                            "size": f"{c['image_width']}x{c['image_height']}", "model": c.get("image_model_name")}
    except Exception as exc:  # noqa: BLE001
        problems.append(f"Picture: {exc}")

    # 3. one Wan clip (optional: it takes several minutes)
    if ctx.options.get("video") and picture:
        try:
            ctx.progress("Animating the test picture with Wan 2.2 (several minutes)", 45)
            c = cfg["comfyui"]
            client = Comfy()
            uploaded = client.upload_image(picture)

            def clip():
                return run_template("video_workflow", {
                    "IMAGE": uploaded, "PROMPT": "slow push in, the clock's hands move, dust floats in the light",
                    "SEED": new_seed(), "WIDTH": c["video_width"], "HEIGHT": c["video_height"],
                    "FRAMES": c["video_frames"], "FPS": c["video_fps"], "FILENAME_PREFIX": "fof/speedtest/clip"},
                    work / "clip", cancelled=ctx.cancelled,
                    on_progress=lambda t, p=None: ctx.progress(f"Animating the test picture: {t}"))
            _, secs = _timed(clip)
            steps["wan_clip"] = {"minutes": round(secs / 60, 2), "seconds_of_video":
                                 round(int(c["video_frames"]) / max(1, int(c["video_fps"])), 1),
                                 "size": f"{c['video_width']}x{c['video_height']}", "model": c.get("video_model_name")}
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Wan clip: {exc}")
    try:
        Comfy().free_memory()
    except Exception:  # noqa: BLE001 - ComfyUI not running: nothing to free
        pass

    # 4. a 2.5D parallax move, rendered on this PC (no AI)
    try:
        ctx.check_cancel()
        ctx.progress("Rendering a 5-second 2.5D move", 75)
        from . import media
        from .engines.render import Segment, Timeline, _render_segment
        vid = cfg["video"]
        still = picture or _plain_still(work / "still.png", int(vid["width"]), int(vid["height"]))
        tl = Timeline([], width=int(vid["width"]), height=int(vid["height"]), fps=int(vid["fps"]))
        seg = Segment(Path(still), 5.0, camera="zoom_in", label="speedtest", depth=Path("estimated"))
        _, secs = _timed(lambda: _render_segment(tl, seg, work / "parallax.mp4", media.encoder("libx264")))
        steps["parallax"] = {"seconds_per_5s_clip": round(secs, 1), "size": f"{vid['width']}x{vid['height']}"}
    except Exception as exc:  # noqa: BLE001
        problems.append(f"2.5D move: {exc}")

    # 5. Owlbert's voice
    try:
        ctx.progress("Timing Owlbert's voice", 88)
        from .stages.narration import synth_line
        line = ("Hoo! Let's look at what the record really shows. In 1999, the fear was everywhere, but on "
                "January first the lights stayed on, the planes kept flying, and the banks opened on time.")
        audio, secs = _timed(lambda: synth_line(line, work / "voice.wav"))
        steps["voice"] = {"speech_seconds": round(float(audio), 1), "work_seconds": round(secs, 1),
                          "times_real_time": round(float(audio) / secs, 1) if secs else 0}
    except Exception as exc:  # noqa: BLE001
        problems.append(f"Voice: {exc}")

    result = {"tested_at": time.strftime("%Y-%m-%d %H:%M"), "steps": steps, "problems": problems,
              "estimate_10_min": estimate(steps, 10)}
    write_json(results_path(), result)
    report = logs / f"speed-test-{time.strftime('%Y%m%d-%H%M')}.txt"
    report.write_text(text_report(result), encoding="utf-8")
    ctx.progress(f"Speed test done: {report.name} is in the logs folder (send it to Claude)."
                 + (f" {len(problems)} step(s) couldn't run; see the report." if problems else ""), 100)


def _plain_still(path: Path, w: int, h: int) -> Path:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), (40, 60, 90))
    d = ImageDraw.Draw(im)
    for i in range(0, w, 40):
        d.line([(i, 0), (w - i, h)], fill=(200, 180, 120), width=3)
    im.save(path)
    return path


def estimate(steps: dict[str, Any], minutes: float) -> dict[str, Any]:
    """Rough time per step for a video of this length (balanced animation, 2 pictures per shot)."""
    from .styles import get
    st = get(None)
    shots = int(minutes * 60 / max(2.0, st.shot_seconds))
    out: dict[str, Any] = {"shots": shots}
    writer = next((m for m in steps.get("models", []) if m["tokens_per_second"]), None)
    if writer:
        # ~150 words a minute of narration, written about 3 times over (outline, scenes, fixes)
        out["script_minutes"] = round(minutes * 150 * 3 / max(0.1, writer["words_per_second"]) / 60, 1)
    if steps.get("picture"):
        out["pictures_minutes"] = round(shots * 2 * steps["picture"]["seconds"] / 60, 1)
    clip_min = (steps.get("wan_clip") or {}).get("minutes")
    animated = round(shots * 0.34)
    out["animated_shots"] = animated
    if clip_min:
        out["wan_hours"] = round(animated * clip_min / 60, 1)
    if steps.get("parallax"):
        out["parallax_minutes"] = round((shots - animated) * steps["parallax"]["seconds_per_5s_clip"] / 60, 1)
    if steps.get("voice", {}).get("times_real_time"):
        out["voice_minutes"] = round(minutes / steps["voice"]["times_real_time"], 1)
    return out


def text_report(r: dict[str, Any]) -> str:
    s = r["steps"]
    lines = [f"Followers or Facts Studio speed test, {r['tested_at']}", ""]
    gpu = ""
    try:
        from .gpucheck import smi
        cards = smi()
        gpu = ", ".join(f"{c.get('name')} ({c.get('memory.total')} MB)" for c in cards)
    except Exception:  # noqa: BLE001
        pass
    lines.append(f"Graphics card: {gpu or 'unknown'}")
    lines.append("")
    lines.append("AI models (writing speed):")
    for m in s.get("models", []):
        lines.append(f"  {m['model']}: {m['tokens_per_second']} tokens/s, about {m['words_per_second']} words/s "
                     f"(loading took {m['load_seconds']} s)")
    if s.get("picture"):
        p = s["picture"]
        lines.append(f"Picture ({p['model']}, {p['size']}): {p['seconds']} s each (the first, with loading: "
                     f"{p['first_seconds']} s)")
    if s.get("wan_clip"):
        w = s["wan_clip"]
        lines.append(f"Wan clip ({w['model']}, {w['size']}, {w['seconds_of_video']} s of video): {w['minutes']} minutes")
    else:
        lines.append("Wan clip: not timed (tick 'include a Wan clip' to time one)")
    if s.get("parallax"):
        lines.append(f"2.5D move ({s['parallax']['size']}): {s['parallax']['seconds_per_5s_clip']} s per 5-second clip")
    if s.get("voice"):
        v = s["voice"]
        lines.append(f"Owlbert's voice: {v['speech_seconds']} s of speech in {v['work_seconds']} s "
                     f"({v['times_real_time']}x real time)")
    e = r.get("estimate_10_min", {})
    lines += ["", f"A 10-minute video (about {e.get('shots')} shots, {e.get('animated_shots')} animated by Wan) "
                  "would take roughly:"]
    names = {"script_minutes": "script writing (minutes)", "pictures_minutes": "storyboard pictures, 2 per shot (minutes)",
             "wan_hours": "Wan animation (hours)", "parallax_minutes": "2.5D moves (minutes)",
             "voice_minutes": "Owlbert's voice (minutes)"}
    for k, label in names.items():
        if k in e:
            lines.append(f"  {label}: {e[k]}")
    if r.get("problems"):
        lines += ["", "Couldn't run:"] + [f"  {p}" for p in r["problems"]]
    return "\n".join(lines) + "\n\n" + json.dumps(r, indent=1) + "\n"
