"""Unreal Engine, done for you (Dave, 2026-10-31: "make a script that can do what you need, that way it will be
done correctly"; 2026-11-01: ran it by hand in Play mode and nothing happened, so now the Studio runs Unreal itself).

  start(ep)     one button: finds Unreal (the Epic launcher's list of installs), makes a small project of its own
                with the Python plugin switched on (<data>/unreal/FoFGuides/), and opens Unreal with
                -ExecutePythonScript so the script runs as soon as the level has loaded and Unreal closes when it
                finishes. The first time can take 10-20 minutes while Unreal prepares its shaders.

  prepare(ep)   writes the job (the places in this video's bible) and a ready-to-run copy of the Unreal script,
                fof_unreal_guides.py, in <data>/unreal/. In Unreal: Tools > Execute Python Script > that file.
                The script builds a rough set for each place from Unreal's built-in shapes, puts six cameras
                around it, captures a depth picture and a plain layout picture from each, saves them, and removes
                everything it added (data/unreal/fof_unreal_guides.py).
  bring_in()    turns what Unreal saved into guide pictures: depth (near = white) and outlines, at the painting's
                size, in <data>/control-maps/<place id>/ where the storyboard finds them (controlmaps.py). It runs
                by itself when the storyboard looks for guides, so pressing Make pictures is enough.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

from .config import data_dir, settings
from .episode import Episode
from .util import StageError, read_json, utc_now, write_json

SCRIPT = Path(__file__).resolve().parent / "data" / "unreal" / "fof_unreal_guides.py"


def folder() -> Path:
    return data_dir() / "unreal"


def out_dir() -> Path:
    return folder() / "out"


def prepare(ep: Episode, auto: bool = False) -> dict[str, Any]:
    """The job for this video's places, and the script with the job's path filled in."""
    from . import bible
    b = bible.load(ep)
    places = [{"id": k, **{f: v.get(f, "") for f in ("name", "architecture", "props", "colours")}}
              for k, v in (b.get("locations") or {}).items()]
    if not places:
        raise StageError("This video's bible has no places yet. Approve the script, then press Make pictures once "
                         "(it writes the bible), then come back here.")
    folder().mkdir(parents=True, exist_ok=True)
    out_dir().mkdir(parents=True, exist_ok=True)
    for old in ("done.json", "run-log.txt"):
        (out_dir() / old).unlink(missing_ok=True)
    job = {"out": str(out_dir()), "places": places, "episode": ep.project_id, "made_at": utc_now(), "auto": auto}
    write_json(folder() / "job.json", job)
    script = folder() / "fof_unreal_guides.py"
    script.write_text(SCRIPT.read_text(encoding="utf-8").replace("{{JOB_PATH}}", str(folder() / "job.json")),
                      encoding="utf-8")
    return {"script": script, "job": folder() / "job.json", "places": places}


# ---------------------------------------------------------------- running Unreal by itself
LAUNCHER_LIST = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Epic" / "UnrealEngineLauncher" / \
    "LauncherInstalled.dat"
PROJECT = "FoFGuides"
FIRST_RUN_MINUTES = 40           # the first open compiles shaders; after that a run takes a few minutes


def _version(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _engine_version(exe: Path) -> tuple[int, ...] | None:
    """The version written in the install itself (Engine/Build/Build.version)."""
    try:
        b = json.loads((Path(exe).parents[2] / "Build" / "Build.version").read_text(encoding="utf-8"))
        return int(b["MajorVersion"]), int(b["MinorVersion"])
    except (OSError, ValueError, KeyError, IndexError):
        return None


def find_editor() -> tuple[Path, str] | None:
    """(UnrealEditor-Cmd.exe or UnrealEditor.exe, "5.x") for the newest Unreal Engine 5 installed, or None.
    Settings > paths > unreal_editor wins; then the Epic launcher's list; then the registry; then Program Files."""
    def exe_in(root: Path) -> Path | None:
        b = Path(root) / "Engine" / "Binaries" / "Win64"
        for name in ("UnrealEditor-Cmd.exe", "UnrealEditor.exe"):
            if (b / name).exists():
                return b / name
        return None
    custom = (settings()["paths"].get("unreal_editor") or "").strip().strip('"')
    if custom:
        c = Path(custom)
        exe = c if c.is_file() else exe_in(c)
        if exe:
            v = _engine_version(exe) or _version(custom)
            return exe, f"{v[0]}.{v[1]}" if v[0] else "5.6"
    found: list[tuple[tuple[int, ...], Path]] = []
    try:
        for it in json.loads(LAUNCHER_LIST.read_text(encoding="utf-8")).get("InstallationList", []):
            name = it.get("AppName", "")
            if name.startswith("UE_5") and exe_in(Path(it.get("InstallLocation", ""))):
                found.append((_version(name), exe_in(Path(it["InstallLocation"]))))
    except (OSError, ValueError):
        pass
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EpicGames\Unreal Engine") as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    ver = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, ver) as sub:
                        root = Path(winreg.QueryValueEx(sub, "InstalledDirectory")[0])
                    if ver.startswith("5") and exe_in(root):
                        found.append((_version(ver), exe_in(root)))
        except OSError:
            pass
    for pf in {os.environ.get("ProgramFiles", "C:/Program Files"), "C:/Program Files", "D:/Program Files",
               "F:/Program Files", "D:/Epic Games", "F:/Epic Games"}:
        for root in sorted(Path(pf).glob("Epic Games/UE_5.*")) + sorted(Path(pf).glob("UE_5.*")):
            if exe_in(root):
                found.append((_version(root.name), exe_in(root)))
    if not found:
        return None
    ver, exe = max(found, key=lambda f: f[0])
    ver = _engine_version(exe) or ver
    return exe, f"{ver[0]}.{ver[1]}"


def make_project(version: str) -> Path:
    """A tiny project of the Studio's own, so nothing of yours is touched: no content, just the Python plugin
    (and Editor Scripting Utilities) switched on, so there is nothing to tick by hand."""
    proj = folder() / PROJECT
    (proj / "Config").mkdir(parents=True, exist_ok=True)
    (proj / "Content").mkdir(exist_ok=True)
    uproject = proj / f"{PROJECT}.uproject"
    write_json(uproject, {
        "FileVersion": 3, "EngineAssociation": version, "Category": "", "Description":
        "Followers or Facts Studio: builds rough sets and captures guide pictures (made by the Studio)",
        "Plugins": [{"Name": "PythonScriptPlugin", "Enabled": True},
                    {"Name": "EditorScriptingUtilities", "Enabled": True}]})
    ini = proj / "Config" / "DefaultEditorSettings.ini"
    if not ini.exists():   # don't stop to ask anything on the way in or out
        ini.write_text("[/Script/UnrealEd.EditorLoadingSavingSettings]\nbRestoreOpenAssetTabsOnRestart=False\n"
                       "[/Script/UnrealEd.EditorPerProjectUserSettings]\nbShowStartupTips=False\n",
                       encoding="utf-8")
    return uproject


_RUN: dict[str, Any] = {}


def start(ep: Episode) -> dict[str, Any]:
    """Open Unreal with the Studio's project and the script; Unreal closes by itself when it's done."""
    if running():
        raise StageError("Unreal is already making the guides. Wait for it to finish (or press Stop).")
    found = find_editor()
    if not found:
        raise StageError("Couldn't find Unreal Engine 5. If it's installed somewhere unusual, open Settings > "
                         "paths > unreal_editor and paste the folder it's in (for example "
                         "C:\\Program Files\\Epic Games\\UE_5.6).")
    exe, version = found
    job = prepare(ep, auto=True)
    uproject = make_project(version)
    log = folder() / "unreal-editor.log"
    log.unlink(missing_ok=True)
    cmd = [str(exe), str(uproject), f"-ExecutePythonScript={job['script']}", "-unattended", "-nosplash",
           "-nop4", "-NoSound", "-log", f"-abslog={log}"]
    kwargs: dict[str, Any] = {"cwd": str(exe.parent), "stdin": subprocess.DEVNULL,
                              "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000      # no console window; Unreal's own window still shows
    proc = subprocess.Popen(cmd, **kwargs)
    first = not (uproject.parent / "DerivedDataCache").exists() and not (uproject.parent / "Saved").exists()
    _RUN.clear()
    _RUN.update({"proc": proc, "started": time.time(), "exe": str(exe), "version": version, "first": first,
                 "places": len(job["places"]), "log": log, "done_at": None})
    write_json(folder() / "last-run.json", {"exe": str(exe), "version": version, "at": utc_now(),
                                            "places": len(job["places"])})
    return {"exe": exe, "version": version, "places": job["places"], "first": first}


def running() -> bool:
    p = _RUN.get("proc")
    return bool(p) and p.poll() is None


def stop() -> None:
    p = _RUN.get("proc")
    if p and p.poll() is None:
        p.kill()


def run_log() -> list[str]:
    f = out_dir() / "run-log.txt"
    try:
        return f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def editor_errors(limit: int = 12) -> list[str]:
    """The lines from Unreal's own log that say what went wrong (Python errors, fatal errors)."""
    log = _RUN.get("log") or folder() / "unreal-editor.log"
    try:
        lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    bad = [ln for ln in lines if re.search(r"LogPython: Error|Error: |Fatal error|Assertion failed|LogWindows: Error",
                                         ln)]
    return bad[-limit:]


def check() -> dict[str, Any]:
    """Where the Unreal run is up to, in plain words, for the window to show every couple of seconds.
    Keeps Unreal from hanging forever: once the script says it finished, Unreal gets a minute to close; a run
    that goes far past the expected time is stopped."""
    proc = _RUN.get("proc")
    if not proc:
        return {"state": "idle", "text": ""}
    lines = run_log()
    done = (out_dir() / "done.json").exists()
    elapsed = time.time() - _RUN["started"]
    if done and _RUN.get("done_at") is None:
        _RUN["done_at"] = time.time()
    if proc.poll() is None:
        if _RUN.get("done_at") and time.time() - _RUN["done_at"] > 90:
            proc.kill()                      # finished but stuck on a question while closing
        elif elapsed > 60 * (FIRST_RUN_MINUTES if _RUN["first"] else 15) + 120 * _RUN["places"]:
            proc.kill()
            return {"state": "failed", "text": "Unreal took far too long and was stopped.", "log": lines,
                    "errors": editor_errors()}
        else:
            if lines:
                text = lines[-1].split(" ", 1)[-1]
            elif _RUN["first"]:
                text = (f"Unreal {_RUN['version']} is opening for the first time. It prepares its shaders once, "
                        "which can take 10-20 minutes. Leave it be; it closes by itself.")
            else:
                text = f"Unreal {_RUN['version']} is opening..."
            return {"state": "running", "text": text, "minutes": int(elapsed // 60), "log": lines}
    if done:
        r = bring_in()
        info = read_json(out_dir() / "done.json") if (out_dir() / "done.json").exists() else {}
        n = sum(len(v) for v in r["made"].values())
        _RUN.clear()
        return {"state": "done", "text": f"Done: {n} guide picture(s) made.", "made": r["made"],
                "problems": (info or {}).get("problems", []) + r["problems"], "log": lines}
    errors = editor_errors()
    _RUN.clear()
    why = next((ln.split("STOPPED: ", 1)[1] for ln in lines if "STOPPED: " in ln), "")
    if not why:
        why = next((ln.split("ERROR: ", 1)[1] for ln in lines if "ERROR: " in ln), "")
    if not why and not lines:
        why = ("Unreal closed before the script started. The lines below are from Unreal's own log; send them "
               "to Claude if they don't make sense.")
    return {"state": "failed", "text": why or "Unreal stopped before it finished.", "log": lines,
            "errors": errors}


def pending() -> list[Path]:
    """Captures Unreal saved that haven't been turned into guide pictures yet."""
    if not out_dir().is_dir():
        return []
    return sorted(p for p in out_dir().glob("*/*.json") if p.name != "place.json")


def _depth(raw: Path, w: int, h: int, size: tuple[int, int]) -> np.ndarray:
    """Unreal's depth (centimetres per pixel) as 0..255 at the painting's size: near = white, far = dark."""
    import cv2
    d = np.fromfile(raw, dtype="<f4")
    if d.size != w * h:
        raise StageError(f"{raw.name} isn't the size Unreal said it was")
    d = d.reshape(h, w)
    valid = np.isfinite(d) & (d > 0) & (d < 1e6)         # the sky / nothing comes back huge
    if not valid.any():
        raise StageError(f"{raw.name} saw nothing (the set wasn't in front of the camera)")
    near, far = np.percentile(d[valid], 1), np.percentile(d[valid], 99)
    norm = np.zeros_like(d)
    norm[valid] = 1.0 - np.clip((d[valid] - near) / max(1e-3, far - near), 0, 1)
    return cv2.resize((norm * 255).astype(np.uint8), size, interpolation=cv2.INTER_LANCZOS4)


def _lines(layout: Path | None, depth: np.ndarray | None, w: int, h: int, size: tuple[int, int]) -> np.ndarray:
    """Outlines: where the depth jumps (the edge of every wall, desk and figure) plus the creases the lighting
    shows in the plain grey layout picture. Either alone is enough, so a dark capture still gives outlines."""
    import cv2
    edges = np.zeros((size[1], size[0]), np.uint8)
    if depth is not None:
        edges |= cv2.Canny(cv2.GaussianBlur(depth, (5, 5), 0), 12, 36)
    if layout is not None and layout.exists():
        rgb = np.fromfile(layout, dtype=np.uint8)
        if rgb.size != w * h * 3:
            raise StageError(f"{layout.name} isn't the size Unreal said it was")
        grey = cv2.cvtColor(rgb.reshape(h, w, 3), cv2.COLOR_RGB2GRAY)
        grey = cv2.resize(grey, size, interpolation=cv2.INTER_CUBIC)
        edges |= cv2.Canny(cv2.GaussianBlur(grey, (5, 5), 0), 30, 90)
    return edges


def bring_in() -> dict[str, Any]:
    """Turn every finished Unreal capture into guide pictures. Returns what was made, by place."""
    from PIL import Image

    from .controlmaps import folder_for_location
    cfg = settings()["comfyui"]
    size = (int(cfg["image_width"]), int(cfg["image_height"]))
    made: dict[str, list[str]] = {}
    problems: list[str] = []
    for meta_path in pending():
        meta = read_json(meta_path) or {}
        place = meta_path.parent.name
        cam = meta.get("camera") or meta_path.stem
        dest = folder_for_location(place)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            depth = meta_path.with_name(f"{cam}.depth.bin")
            layout = meta_path.with_name(f"{cam}.layout.bin")
            w, h = int(meta["width"]), int(meta["height"])
            dmap = _depth(depth, w, h, size) if depth.exists() else None
            if dmap is not None:
                Image.fromarray(dmap, "L").convert("RGB").save(dest / f"{cam}-depth.png")
                made.setdefault(place, []).append(f"{cam}-depth.png")
            if dmap is not None or layout.exists():
                lines = _lines(layout, dmap, w, h, size)
                if lines.any():
                    Image.fromarray(lines, "L").convert("RGB").save(dest / f"{cam}-lines.png")
                    made.setdefault(place, []).append(f"{cam}-lines.png")
        except (StageError, KeyError, ValueError, OSError) as exc:
            problems.append(f"{place}/{cam}: {exc}")
            continue
        for f in (meta_path, meta_path.with_name(f"{cam}.depth.bin"), meta_path.with_name(f"{cam}.layout.bin")):
            f.unlink(missing_ok=True)
    for place_dir in list(out_dir().glob("*")) if out_dir().is_dir() else []:
        if place_dir.is_dir() and not any(p.suffix == ".bin" for p in place_dir.iterdir()):
            if (place_dir / "place.json").exists():
                folder_for_location(place_dir.name).mkdir(parents=True, exist_ok=True)
                shutil.copy2(place_dir / "place.json", folder_for_location(place_dir.name) / "place.json")
            shutil.rmtree(place_dir, ignore_errors=True)
    if made or problems:
        write_json(folder() / "last-import.json", {"made": made, "problems": problems, "at": utc_now()})
    return {"made": made, "problems": problems}


def status(ep: Episode) -> list[dict[str, Any]]:
    """For each place in this video: how many guide pictures it has."""
    from . import bible
    from .controlmaps import KINDS, folder_for_location
    out = []
    for pid, loc in (bible.load(ep).get("locations") or {}).items():
        d = folder_for_location(pid)
        n = len([p for p in d.iterdir() if p.suffix.lower() in KINDS]) if d.is_dir() else 0
        out.append({"id": pid, "name": loc.get("name", pid), "guides": n, "folder": d})
    return out

