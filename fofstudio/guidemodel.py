"""The guide model for ComfyUI (Dave, 2026-11-01: "I have no idea how to download or add
Z-Image-Turbo-Fun-Controlnet-Union to ComfyUI"). The Studio does it: it finds ComfyUI's models folder and downloads
the file into models/model_patches/, picking up where it left off if the download was interrupted.

The model: Alibaba PAI's Z-Image-Turbo-Fun-Controlnet-Union 2.1, Apache-2.0 (commercial use allowed). The "lite"
2602 8-step file (about 2 GB) is the one meant for smaller graphics cards like the 12 GB RTX 3060; it follows
depth, outlines (canny/HED/MLSD), pose, scribble and grey pictures. ComfyUI needs the "Apply Fun ControlNet" node
(ZImageFunControlnet, in ComfyUI since December 2025): an older ComfyUI must be updated first.
(Research "Unreal automation and guide model setup".)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .config import settings
from .util import StageError

REPO = "https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/"
NODE = "ZImageFunControlnet"


def filename() -> str:
    return settings()["comfyui"].get("guide_model") or \
        "Z-Image-Turbo-Fun-Controlnet-Union-2.1-lite-2602-8steps.safetensors"


def models_folder() -> Path | None:
    """ComfyUI's models folder: Settings > paths > comfyui_models, else next to ComfyUI's main.py, else the
    desktop app's usual place (Documents/ComfyUI)."""
    custom = (settings()["paths"].get("comfyui_models") or "").strip().strip('"')
    if custom:
        return Path(custom)
    base = Path(settings()["paths"]["comfyui_dir"])
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for folder in (base, base / "ComfyUI", base.parent / "ComfyUI_windows_portable" / "ComfyUI",
                   home / "Documents" / "ComfyUI", home / "OneDrive" / "Documents" / "ComfyUI"):
        if (folder / "models").is_dir() and ((folder / "main.py").exists() or (folder / "models" / "vae").is_dir()):
            return folder / "models"
    return None


def target() -> Path | None:
    m = models_folder()
    return m / "model_patches" / filename() if m else None


def have() -> bool:
    t = target()
    return bool(t) and t.exists() and t.stat().st_size > 100_000_000


def comfy_ready() -> tuple[bool, str]:
    """Does the running ComfyUI have the node and see the file? In plain words."""
    from .comfy import Comfy
    c = Comfy()
    ok, why = c.health()
    if not ok:
        return False, "ComfyUI isn't running, so it can't be checked yet."
    try:
        if not c.has_node(NODE):
            return False, ("ComfyUI is too old for the guide model. Update it (portable: run "
                           "update\\update_comfyui.bat; desktop app: Manage > Update), then restart it.")
        with c._session() as s:
            info = s.get(c.url + "/object_info/ModelPatchLoader", timeout=6).json()
        names = info["ModelPatchLoader"]["input"]["required"]["name"][0]
        if filename() not in names:
            return False, "ComfyUI doesn't see the guide model yet. Download it, then restart ComfyUI."
    except Exception as exc:  # noqa: BLE001 - shown to Dave as it is
        return False, f"Couldn't ask ComfyUI about the guide model: {exc}"
    return True, "The guide model is ready in ComfyUI."


def download(progress: Callable[[int, int], None] | None = None) -> Path:
    """Download the guide model into ComfyUI's models/model_patches/ (resumes a part-finished download)."""
    import requests
    t = target()
    if t is None:
        raise StageError("Couldn't find ComfyUI's models folder. Open Settings > paths > comfyui_models and paste "
                         "it (the folder that has checkpoints, vae, loras... in it), then try again.")
    if have():
        return t
    t.parent.mkdir(parents=True, exist_ok=True)
    part = t.with_name(t.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    try:
        with requests.get(REPO + filename(), headers=headers, stream=True, timeout=60) as r:
            if r.status_code == 416:            # already complete
                part.replace(t)
                return t
            r.raise_for_status()
            if done and r.status_code != 206:   # the server started again from the beginning
                done = 0
            total = done + int(r.headers.get("Content-Length") or 0)
            with open(part, "ab" if done else "wb") as fh:
                for chunk in r.iter_content(chunk_size=4 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    except requests.RequestException as exc:
        raise StageError(f"The guide model download stopped ({exc}). Try again; it carries on where it left off.")
    if done < 100_000_000:
        raise StageError("The guide model download came back too small. Try again later.")
    part.replace(t)
    return t
