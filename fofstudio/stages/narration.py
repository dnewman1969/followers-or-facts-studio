"""Stage 6 - Narration: one WAV per scene from the approved script."""

from __future__ import annotations

from ..config import settings
from ..engines.tts import get_engine
from ..episode import Episode
from ..util import StageError, read_json, sha256_text, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context
from .script import load as load_script


def run(ctx: Context) -> None:
    ep = ctx.episode
    script = load_script(ep)
    cfg = settings()["voice"]
    engine = get_engine(ctx.options.get("engine") or cfg["engine"])
    voice = ctx.options.get("voice") or cfg["voice"]
    speed = float(ctx.options.get("speed") or cfg["speed"])
    manifest = read_json(ep.path("audio", "narration.json"), {}) or {}
    redo = ctx.options.get("redo") or []
    for n, sc in enumerate(script["scenes"], 1):
        ctx.check_cancel()
        text = sc["narration"].strip()
        if not text or text == "-":
            continue
        sid = sc["scene_id"]
        digest = sha256_text(f"{engine.name}|{voice}|{speed}|{text}")
        prev = manifest.get(sid)
        if prev and prev.get("digest") == digest and ep.abs(prev["path"]).exists() and \
                not (redo == "all" or sid in redo):
            continue
        ctx.progress(f"Narrating {sid} ({n}/{len(script['scenes'])}) with {engine.name}/{voice}")
        out = ep.path("audio", "narration", f"{sid}.wav")
        info = engine.synthesize(text, out, voice=voice, speed=speed,
                                 emotion=ctx.options.get("emotion", 0.5))
        manifest[sid] = {**info, "path": ep.rel(out), "digest": digest,
                         "text_sha": sha256_text(text), "made_at": utc_now()}
        write_json(ep.path("audio", "narration.json"), manifest)
    if not manifest:
        raise StageError("The script has no narration text.")


def check(ep: Episode) -> list[Check]:
    if not ep.path("script.md").exists():
        return [Check(BLOCK, "No script.")]
    manifest = read_json(ep.path("audio", "narration.json"), {}) or {}
    out = []
    total = 0.0
    for sc in load_script(ep)["scenes"]:
        text = sc["narration"].strip()
        if not text or text == "-":
            continue
        m = manifest.get(sc["scene_id"])
        if not m or not ep.abs(m["path"]).exists():
            out.append(Check(BLOCK, f"{sc['scene_id']} has no narration audio."))
        elif m["text_sha"] != sha256_text(text):
            out.append(Check(BLOCK, f"{sc['scene_id']}: the script text changed after it was "
                                    "recorded. Run Narration again (only changed scenes redo)."))
        else:
            total += m["seconds"]
    if not out:
        out.append(Check(OK, f"Narration ready: {total / 60:.1f} minutes. Listen through before approving."))
    if total and total > 15 * 60:
        out.append(Check(WARN, "Over 15 minutes. Consider trimming the script."))
    return out
