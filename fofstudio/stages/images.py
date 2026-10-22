"""Stage 4 - Images.

ai_image shots go to ComfyUI (Z-Image Turbo by default) and get an
"AI illustration" label. Quote, title and credits cards are drawn locally.
Receipt shots use the real screenshot you saved in receipts/<shot id>.png.
Images you've already approved are kept; pass {"redo": ["SCENE_002-01"]} to
remake particular shots, or {"redo": "all"}.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import cards
from ..comfy import new_seed, run_template
from ..config import settings
from ..episode import Episode
from ..util import StageError, utc_now
from .base import BLOCK, OK, WARN, Check, Context
from .common import cited_sources, credit_line, source_line

RECEIPT_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _receipt_file(ep: Episode, shot_id: str) -> Path | None:
    for ext in RECEIPT_EXTS:
        p = ep.path("receipts", shot_id + ext)
        if p.exists():
            return p
    return None


def _attribution(ep: Episode, source_id: str | None) -> str:
    from .. import db
    row = db.one("SELECT title, publisher, date FROM source WHERE source_id=?", (source_id,)) \
        if source_id else None
    if not row:
        return "Source on file"
    return ", ".join(x for x in (row["publisher"] or row["title"], row["date"]) if x)


def run(ctx: Context) -> None:
    ep = ctx.episode
    board = ep.storyboard()
    if not board.get("shots"):
        raise StageError("Approve the Storyboard stage first.")
    cfg = settings()["comfyui"]
    redo = ctx.options.get("redo") or []
    size = (settings()["video"]["width"], settings()["video"]["height"])
    total = len(board["shots"])
    missing_receipts = []
    for n, shot in enumerate(board["shots"], 1):
        ctx.check_cancel()
        sid = shot["shot_id"]
        keep = shot.get("image") and ep.abs(shot["image"]["path"]).exists() and \
            not (redo == "all" or sid in redo)
        if keep:
            continue
        ctx.progress(f"Image {n}/{total}: {sid} ({shot['type']})")
        if shot["type"] == "ai_image":
            seed = new_seed()
            raw_stem = ep.path("images", "raw", f"{sid}-{seed}")
            saved, meta = run_template("image_workflow", {
                "PROMPT": shot.get("full_prompt") or shot["prompt"], "SEED": seed,
                "WIDTH": cfg["image_width"], "HEIGHT": cfg["image_height"],
                "FILENAME_PREFIX": f"fof/{ep.project_id}/{sid}",
            }, raw_stem, on_progress=ctx.progress, cancelled=ctx.cancelled)
            raw = saved[0]
            labeled = cards.ai_label(raw, ep.path("images", f"{sid}.png"))
            shot["image"] = {"path": ep.rel(labeled), "raw": ep.rel(raw), "seed": seed,
                             "model": cfg["image_model_name"], "workflow": meta["workflow"],
                             "prompt": shot.get("full_prompt"), "licence": "Apache-2.0 model; output ours",
                             "made_at": utc_now()}
        elif shot["type"] == "quote_card":
            out = cards.quote_card(shot["text"], _attribution(ep, shot.get("source_id")),
                                   ep.path("images", f"{sid}.png"), size)
            shot["image"] = {"path": ep.rel(out), "model": "quote card", "made_at": utc_now()}
        elif shot["type"] == "title_card":
            out = cards.title_card(shot["text"], ep.path("images", f"{sid}.png"), size)
            shot["image"] = {"path": ep.rel(out), "model": "title card", "made_at": utc_now()}
        elif shot["type"] == "credits":
            lines = [source_line(s) for s in cited_sources(ep)]
            out = cards.credits_card(lines, credit_line(ep), ep.path("images", f"{sid}.png"), size)
            shot["image"] = {"path": ep.rel(out), "model": "credits card", "made_at": utc_now()}
        elif shot["type"] == "receipt":
            found = _receipt_file(ep, sid)
            if not found:
                missing_receipts.append(sid)
                continue
            dest = ep.path("images", f"{sid}{found.suffix}")
            shutil.copy2(found, dest)
            shot["image"] = {"path": ep.rel(dest), "model": "real document (you supplied)",
                             "source_id": shot.get("source_id"), "made_at": utc_now()}
        ep.save_storyboard(board)  # save after every shot so a crash loses nothing
    if missing_receipts:
        ctx.log("Waiting for real screenshots in receipts/: " + ", ".join(missing_receipts))


def check(ep: Episode) -> list[Check]:
    board = ep.storyboard()
    if not board.get("shots"):
        return [Check(BLOCK, "No storyboard.")]
    out = []
    missing = [s["shot_id"] for s in board["shots"]
               if not s.get("image") or not ep.abs(s["image"]["path"]).exists()]
    if missing:
        out.append(Check(BLOCK, f"{len(missing)} shot(s) have no image yet: {', '.join(missing[:12])}"))
    receipts = [s["shot_id"] for s in board["shots"] if s["type"] == "receipt" and s["shot_id"] in missing]
    if receipts:
        out.append(Check(BLOCK, "Save real screenshots as receipts/<shot id>.png for: " + ", ".join(receipts)))
    unlabeled = [s["shot_id"] for s in board["shots"] if s["type"] == "ai_image" and s.get("image")
                 and not s["image"].get("raw")]
    if unlabeled:
        out.append(Check(WARN, f"AI images without the AI label: {', '.join(unlabeled)}"))
    if not out:
        out.append(Check(OK, f"All {len(board['shots'])} shots have images. Look through them on "
                             "the Storyboard tab; mark any to redo."))
    return out
