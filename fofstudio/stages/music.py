"""Stage 8 (optional) - Music bed.

Either generate an instrumental bed with ACE-Step in ComfyUI (MIT/Apache,
commercial use allowed), or pick a track from <data>/music-library/ (put only
music you have the rights to there, with a .txt note of where it came from).
The render stage loops it under the whole video and ducks it under the voice.
"""

from __future__ import annotations

import shutil

from ..comfy import new_seed, run_template
from ..config import Paths, settings
from ..episode import Episode
from ..util import StageError, read_json, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context

DEFAULT_TAGS = ("instrumental, documentary underscore, calm, curious, soft piano, warm strings, "
                "light pizzicato, slow tempo, no vocals")


def run(ctx: Context) -> None:
    ep = ctx.episode
    choice = ctx.options.get("library_file")
    out_dir = ep.path("audio", "music")
    if choice:
        src = Paths().music_library / choice
        if not src.exists():
            raise StageError(f"{src} doesn't exist.")
        note = src.with_suffix(".txt")
        if not note.exists():
            raise StageError(f"Add {note.name} next to the track saying where it came from and "
                             "its licence, so the episode has a record.")
        dest = out_dir / f"bed{src.suffix}"
        shutil.copy2(src, dest)
        meta = {"path": ep.rel(dest), "model": "music library", "source": src.name,
                "licence_note": note.read_text(encoding="utf-8")[:500], "made_at": utc_now()}
    else:
        narration = read_json(ep.path("audio", "narration.json"), {}) or {}
        total = sum(m["seconds"] for m in narration.values()) or 240
        seconds = int(min(max(total / 3, 60), 180))  # a 1-3 minute bed, looped by the render
        seed = new_seed()
        tags = ctx.options.get("tags") or DEFAULT_TAGS
        ctx.progress(f"Making a {seconds}s music bed with ACE-Step")
        saved, wf = run_template("music_workflow", {
            "TAGS": tags, "LYRICS": "[instrumental]", "SECONDS": seconds, "SEED": seed,
            "FILENAME_PREFIX": f"fof/{ep.project_id}/music",
        }, out_dir / f"bed-{seed}", on_progress=ctx.progress, cancelled=ctx.cancelled)
        meta = {"path": ep.rel(saved[0]), "model": settings()["comfyui"]["music_model_name"],
                "tags": tags, "seed": seed, "workflow": wf["workflow"],
                "licence": "Apache-2.0/MIT model; output ours", "made_at": utc_now()}
    write_json(out_dir / "music.json", meta)


def check(ep: Episode) -> list[Check]:
    meta = read_json(ep.path("audio", "music", "music.json"))
    if not meta:
        return [Check(BLOCK, "No music yet. Run this stage, or Skip it for a voice-only video.")]
    if not ep.abs(meta["path"]).exists():
        return [Check(BLOCK, "The music file is missing. Run again.")]
    out = [Check(OK, f"Music bed: {meta['model']}. Listen before approving.")]
    if meta.get("model") == "music library":
        out.append(Check(WARN, "Library track: make sure the licence allows monetized YouTube use."))
    return out
