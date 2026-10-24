"""GPU check: is the local AI really using the graphics card?

Two things, both in <data>/logs:
  * gpu-usage.csv - while any job runs, every few seconds: which job and step, how busy the GPU is,
    how much of its memory is used, temperature and power. Written by the worker.
  * gpu-report-<date>.txt - made when you press "GPU check" (Settings or Queue page): the card and driver,
    what Ollama has loaded and how much of it sits on the GPU (anything below 100% runs partly on the CPU,
    which is much slower), what ComfyUI sees, whether ffmpeg can use NVENC, a short live test of the writer
    model with the GPU watched while it runs, and a summary of gpu-usage.csv by step.
Send the report file to Claude to check the setup.
"""

from __future__ import annotations

import csv
import json
import platform
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from . import __version__
from .config import Paths, settings

NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0
FIELDS = "timestamp,name,driver_version,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu," \
         "power.draw,clocks.sm,pstate"


def smi(query: str = FIELDS) -> list[dict[str, str]]:
    """nvidia-smi readings (empty if there's no NVIDIA driver)."""
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=8, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    keys = query.split(",")
    return [dict(zip(keys, (x.strip() for x in line.split(",")))) for line in out.stdout.strip().splitlines()
            if line.strip()]


def smi_apps() -> str:
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=8,
                             creationflags=NO_WINDOW)
        return out.stdout.strip() or "(no programs using the GPU right now)"
    except (OSError, subprocess.SubprocessError):
        return "(nvidia-smi not found)"


def _get(url: str, timeout: float = 5) -> Any:
    with requests.Session() as s:
        s.trust_env = False
        r = s.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()


def ollama_models() -> list[dict[str, Any]]:
    """What Ollama has loaded, and what share of each sits on the GPU."""
    url = settings()["ollama"]["url"].rstrip("/")
    out = []
    for m in _get(url + "/api/ps").get("models", []):
        size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
        out.append({"name": m.get("name"), "size_gb": round(size / 1e9, 2), "on_gpu_gb": round(vram / 1e9, 2),
                    "on_gpu_pct": round(100 * vram / size) if size else 0, "context": m.get("context_length")})
    return out


# ---------------------------------------------------------------- sampling while jobs run
class Sampler:
    """Writes a GPU reading to gpu-usage.csv every few seconds while a job runs."""

    def __init__(self, job_id: int | str, stage: str, project: str, every: float = 5.0):
        self.job, self.stage, self.project, self.every = job_id, stage, project, every
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        if smi("name"):
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()

    def _run(self) -> None:
        path = Paths().logs / "gpu-usage.csv"
        new = not path.exists()
        last_ollama = 0.0
        on_gpu = ""
        while not self._stop.wait(self.every):
            r = (smi() or [{}])[0]
            if time.time() - last_ollama > 30:
                last_ollama = time.time()
                try:
                    on_gpu = "; ".join(f"{m['name']} {m['on_gpu_pct']}% on GPU" for m in ollama_models())
                except Exception:  # noqa: BLE001 - Ollama not running is fine
                    on_gpu = ""
            try:
                with path.open("a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(["time", "job", "project", "step", "gpu_busy_pct", "vram_used_mb", "vram_total_mb",
                                    "temp_c", "power_w", "clock_mhz", "pstate", "ollama"])
                        new = False
                    w.writerow([datetime.now().isoformat(timespec="seconds"), self.job, self.project, self.stage,
                                r.get("utilization.gpu"), r.get("memory.used"), r.get("memory.total"),
                                r.get("temperature.gpu"), r.get("power.draw"), r.get("clocks.sm"), r.get("pstate"),
                                on_gpu])
            except OSError:
                pass


def usage_summary(path: Path | None = None, last: int = 4000) -> list[str]:
    path = path or Paths().logs / "gpu-usage.csv"
    if not path.exists():
        return ["(no readings yet: run a job, then make the report again)"]
    rows = list(csv.DictReader(path.open(encoding="utf-8")))[-last:]
    by: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by.setdefault(r["step"], []).append(r)
    out = []
    for step, rs in by.items():
        busy = [float(r["gpu_busy_pct"]) for r in rs if (r["gpu_busy_pct"] or "").replace(".", "").isdigit()]
        mem = [float(r["vram_used_mb"]) for r in rs if (r["vram_used_mb"] or "").replace(".", "").isdigit()]
        if not busy:
            continue
        idle = sum(1 for b in busy if b < 15) / len(busy)
        out.append(f"{step:<14} {len(rs):>5} readings   GPU busy avg {sum(busy) / len(busy):5.1f}%  max {max(busy):5.1f}%"
                   f"   idle {100 * idle:4.0f}% of the time   VRAM max {max(mem) / 1024 if mem else 0:5.1f} GB")
    return out or ["(no readings with numbers yet)"]


# ---------------------------------------------------------------- the report
def report(progress=lambda t: None, live_test: bool = True) -> Path:
    """Write gpu-report-<date>.txt in the logs folder and return its path."""
    lines: list[str] = []
    add = lines.append
    cfg = settings()
    add(f"Followers or Facts Studio {__version__} - GPU report - {datetime.now():%Y-%m-%d %H:%M:%S}")
    add(f"Windows/OS: {platform.platform()}   Python {platform.python_version()}")
    try:
        import psutil
        vm = psutil.virtual_memory()
        add(f"CPU: {platform.processor()} ({psutil.cpu_count()} threads)   RAM: {vm.total / 1e9:.0f} GB "
            f"({vm.percent:.0f}% used)")
    except Exception:  # noqa: BLE001
        pass
    add("")
    add("== Graphics card (nvidia-smi) ==")
    progress("Reading the graphics card")
    cards = smi()
    if not cards:
        add("nvidia-smi didn't answer: the NVIDIA driver may be missing, or this isn't an NVIDIA card. "
            "Nothing will run on the GPU until that's fixed.")
    for c in cards:
        add(f"{c.get('name')}  driver {c.get('driver_version')}  VRAM {c.get('memory.used')}/{c.get('memory.total')} MB  "
            f"busy {c.get('utilization.gpu')}%  {c.get('temperature.gpu')} C  {c.get('power.draw')} W  "
            f"{c.get('clocks.sm')} MHz  {c.get('pstate')}")
    add("Programs using the GPU:")
    add(smi_apps())
    add("")
    add("== Ollama (the writer) ==")
    progress("Asking Ollama what it has loaded")
    url = cfg["ollama"]["url"].rstrip("/")
    try:
        add(f"Ollama {(_get(url + '/api/version') or {}).get('version')} at {url}")
        add(f"Writer model: {cfg['ollama']['writer_model']}   context {cfg['ollama']['num_ctx']} "
            f"(up to {cfg['ollama'].get('max_ctx')})")
        models = ollama_models()
        for m in models:
            verdict = "all on the GPU (good)" if m["on_gpu_pct"] >= 99 else \
                f"ONLY {m['on_gpu_pct']}% on the GPU - the rest runs on the CPU, which is slow"
            add(f"  loaded: {m['name']}  {m['size_gb']} GB, {m['on_gpu_gb']} GB on the GPU -> {verdict}  "
                f"(context {m['context']})")
        if not models:
            add("  nothing loaded right now")
    except Exception as exc:  # noqa: BLE001
        add(f"Ollama didn't answer: {exc}")
    if live_test:
        add("")
        add("== Live test: the writer writes ~150 words while the GPU is watched ==")
        progress("Live test: the writer is writing while the GPU is watched")
        add(_live_test(url, cfg["ollama"]["writer_model"], int(cfg["ollama"]["num_ctx"])))
    add("")
    add("== ComfyUI (pictures, video, music) ==")
    progress("Asking ComfyUI what it sees")
    curl = cfg["comfyui"]["url"].rstrip("/")
    try:
        st = _get(curl + "/system_stats")
        sysinfo = st.get("system", {})
        add(f"ComfyUI {sysinfo.get('comfyui_version')}  PyTorch {sysinfo.get('pytorch_version')}  "
            f"Python {sysinfo.get('python_version', '')[:12]}")
        add(f"Started with: {' '.join(sysinfo.get('argv', []))}")
        for d in st.get("devices", []):
            add(f"  device: {d.get('name')}  type {d.get('type')}  VRAM free {int(d.get('vram_free', 0)) / 2**30:.1f}"
                f" of {int(d.get('vram_total', 0)) / 2**30:.1f} GB")
            if d.get("type") != "cuda":
                add("  !! ComfyUI is NOT using CUDA: pictures and video will be very slow. Reinstall the NVIDIA "
                    "(CUDA) build of PyTorch for ComfyUI.")
        if "--cpu" in sysinfo.get("argv", []):
            add("  !! ComfyUI was started with --cpu")
    except Exception as exc:  # noqa: BLE001
        add(f"ComfyUI didn't answer at {curl}: {exc}")
    add("")
    add("== ffmpeg (making the video file) ==")
    try:
        from . import media
        enc = media.encoder(cfg["video"].get("encoder", "auto"))
        add(f"Encoder in use: {enc['name']}" + ("  (the GPU's NVENC chip: fast)" if "nvenc" in enc["name"]
                                                else "  (the CPU: slower, but fine)"))
    except Exception as exc:  # noqa: BLE001
        add(f"ffmpeg check failed: {exc}")
    add("")
    add("== GPU use during recent jobs (gpu-usage.csv) ==")
    lines += usage_summary()
    add("")
    add("What good looks like: Ollama models 100% on the GPU; the GPU busy 80-100% while writing, painting and "
        "animating; ComfyUI type cuda; VRAM under the card's total. Long 'idle' while a GPU step runs means it's "
        "waiting on the CPU or the disk.")
    out = Paths().logs / f"gpu-report-{datetime.now():%Y%m%d-%H%M%S}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    progress(f"GPU report saved: {out}")
    return out


def _live_test(url: str, model: str, ctx: int) -> str:
    readings: list[dict[str, str]] = []
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(0.5):
            r = smi("utilization.gpu,memory.used,power.draw")
            if r:
                readings.append(r[0])
    t = threading.Thread(target=watch, daemon=True)
    t.start()
    t0 = time.time()
    try:
        with requests.Session() as s:
            s.trust_env = False
            r = s.post(url + "/api/generate", json={
                "model": model, "prompt": "Write about 150 words on why people believed the Y2K bug would end the "
                                          "world.", "stream": False, "think": False,
                "options": {"num_ctx": ctx, "num_predict": 260}}, timeout=600)
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        stop.set()
        return f"The test didn't run: {exc}"
    stop.set()
    secs = time.time() - t0
    toks = int(data.get("eval_count") or 0)
    speed = toks / (int(data.get("eval_duration") or 1) / 1e9) if data.get("eval_duration") else 0
    load = (int(data.get("load_duration") or 0)) / 1e9
    busy = [float(x["utilization.gpu"]) for x in readings if x.get("utilization.gpu", "").replace(".", "").isdigit()]
    msg = [f"{toks} tokens in {secs:.1f} s ({speed:.1f} tokens/s writing; model load {load:.1f} s)"]
    if busy:
        msg.append(f"GPU busy during the test: avg {sum(busy) / len(busy):.0f}%, max {max(busy):.0f}%")
    try:
        on = ollama_models()
        msg += [f"after the test: {m['name']} {m['on_gpu_pct']}% on the GPU" for m in on]
    except Exception:  # noqa: BLE001
        pass
    if speed and speed < 12:
        msg.append("!! Slow for a 12 GB RTX card with a 14B model (expect about 25-35 tokens/s). Part of the model "
                   "is probably on the CPU: lower [ollama] num_ctx, or close other programs using the GPU.")
    return "\n".join(msg)


def open_folder(path: Path) -> None:
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError:
        pass


def as_json(path: Path) -> str:
    return json.dumps({"report": str(path)})
