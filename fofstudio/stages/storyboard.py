"""Stage 3 - Storyboard: turn each scene into shots.

Shot types:
  ai_image    an illustration made by ComfyUI (always labelled "AI illustration")
  quote_card  a verified quote drawn as text on a card (never an AI image)
  title_card  a date, place or short label
  receipt     a real document screenshot/scan you supply in the receipts/ folder
  credits     the closing sources-and-credit card
"""

from __future__ import annotations

import re
from typing import Any

from .. import db
from ..config import settings
from ..episode import Episode
from ..llm import Ollama
from ..scriptfmt import parse, quotes_in
from ..util import StageError, normalize_for_match, read_json, utc_now
from .base import BLOCK, OK, WARN, Check, Context

STYLES = {
    "documentary": ("documentary photograph, cinematic lighting, 16:9 landscape, photorealistic, "
                    "moody dark color grade, shallow depth of field"),
    "scrapbook": ("scrapbook documentary collage, aged paper texture, warm desk lamp light, "
                  "muted navy and cream palette with gold accents, 16:9"),
    "illustrated": ("editorial illustration, clean shapes, muted navy, cream and gold palette, "
                    "soft grain, 16:9"),
}
GUARD = ("no text, no letters, no words, no watermark, no logos, "
         "no recognizable real people, faces turned away or in silhouette")

CAMERA_MOVES = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "dolly_in", "static"]
SHOT_TYPES = ["ai_image", "quote_card", "title_card", "receipt"]

SHOT_SCHEMA = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": SHOT_TYPES},
                    "prompt": {"type": "string"},
                    "text": {"type": "string"},
                    "excerpt_id": {"type": "integer"},
                    "source_id": {"type": "string"},
                    "weight": {"type": "number"},
                    "camera": {"type": "string", "enum": CAMERA_MOVES},
                },
                "required": ["type", "prompt", "text", "weight", "camera"],
            },
        }
    },
    "required": ["shots"],
}


def person_names() -> list[str]:
    names = []
    for r in db.rows("SELECT name, aka FROM person"):
        for n in [r["name"]] + [a.strip() for a in (r["aka"] or "").split(";")]:
            if n and len(n.split()) >= 2:
                names.append(n)
    return names


def names_in(text: str, names: list[str]) -> list[str]:
    low = normalize_for_match(text)
    return sorted({n for n in names if normalize_for_match(n) in low})


def _excerpts(packet: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {e["excerpt_id"]: e for c in packet.get("claims", []) for e in c["excerpts"]}


def _simple_shots(scene: dict[str, Any], excerpts: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    shots = [{"type": "ai_image", "prompt": scene["visual"], "text": "", "weight": 2,
              "camera": "zoom_in"}]
    if scene["on_screen_text"] and scene["on_screen_text"] != "-":
        shots.append({"type": "title_card", "prompt": "", "text": scene["on_screen_text"],
                      "weight": 1, "camera": "static"})
    for quote in quotes_in(scene["narration"]):
        match = next((e for e in excerpts.values()
                      if normalize_for_match(quote) in normalize_for_match(e["text"])), None)
        if match:
            shots.append({"type": "quote_card", "prompt": "", "text": quote,
                          "excerpt_id": match["excerpt_id"], "source_id": match["source_id"],
                          "weight": 1.5, "camera": "zoom_in"})
    return shots


def _llm_shots(ctx: Context, scene: dict[str, Any], excerpts: dict[int, dict[str, Any]],
               restrictions: list[str]) -> list[dict[str, Any]]:
    max_shots = settings()["storyboard"]["max_shots_per_scene"]
    allowed = [{"excerpt_id": int(e), "source_id": excerpts[int(e)]["source_id"],
                "text": excerpts[int(e)]["text"]}
               for e in scene["excerpt_ids"] if e.isdigit() and int(e) in excerpts]
    answer = Ollama().chat_json([
        {"role": "system", "content": (
            "You are a documentary storyboard artist. Break one narrated scene into 2 to "
            f"{max_shots} shots that follow the narration in order.\n"
            "ai_image: prompt describes one picture (objects, places, documents, crowds from "
            "behind, moods). Never name a real person, never ask for readable text or logos.\n"
            "quote_card: ONLY for a quote listed under 'quotes you may show'; copy its text "
            "exactly and give its excerpt_id and source_id.\n"
            "title_card: a date, place or short label (max 8 words) in text.\n"
            "receipt: a real document from the listed sources that the producer will screenshot; "
            "put what to capture in prompt and the source_id.\n"
            "weight = how long the shot stays on screen relative to the others (1 to 3).")},
        {"role": "user", "content": (
            f"Scene visual idea: {scene['visual']}\n"
            f"Narration: {scene['narration']}\n"
            f"On-screen text: {scene['on_screen_text']}\n"
            f"Sources in this scene: {', '.join(scene['source_ids']) or 'none'}\n"
            f"Quotes you may show: {allowed or 'none'}\n"
            f"Careful-topic rules: {restrictions or 'none'}")},
    ], SHOT_SCHEMA, temperature=0.5)
    shots = answer.get("shots") or []
    if not shots:
        raise StageError(f"{scene['scene_id']}: the storyboard came back empty. Run again.")
    return shots[:max_shots]


def run(ctx: Context) -> None:
    ep = ctx.episode
    if not ep.path("script.md").exists():
        raise StageError("Approve the Script stage first.")
    script = parse(ep.path("script.md").read_text(encoding="utf-8"))
    packet = read_json(ep.path("research.json")) or {"claims": [], "restrictions": []}
    excerpts = _excerpts(packet)
    restrictions = [f"{r['rule']} ({r['subject_id']})" for r in packet.get("restrictions", [])]
    style_name = ctx.options.get("style", "documentary")
    style = STYLES.get(style_name, STYLES["documentary"])
    mode = ctx.options.get("mode", settings()["storyboard"]["mode"])
    animate_per_scene = int(settings()["storyboard"]["animate_shots_per_scene"])

    old = {s["shot_id"]: s for s in (ep.storyboard().get("shots") or [])}
    shots: list[dict[str, Any]] = []
    for n, scene in enumerate(script["scenes"], 1):
        ctx.check_cancel()
        ctx.progress(f"Storyboarding {scene['scene_id']} ({n}/{len(script['scenes'])})")
        raw = _llm_shots(ctx, scene, excerpts, restrictions) if mode == "llm" else \
            _simple_shots(scene, excerpts)
        animated = 0
        for i, s in enumerate(raw, 1):
            shot_id = f"{scene['scene_id']}-{i:02d}"
            shot = {
                "shot_id": shot_id, "scene_id": scene["scene_id"], "type": s["type"],
                "prompt": (s.get("prompt") or "").strip(), "text": (s.get("text") or "").strip(),
                "excerpt_id": s.get("excerpt_id") or None, "source_id": s.get("source_id") or None,
                "weight": max(0.5, min(3.0, float(s.get("weight") or 1))),
                "camera": s.get("camera") if s.get("camera") in CAMERA_MOVES else "zoom_in",
                "animate": False, "label_ai": s["type"] == "ai_image",
            }
            if shot["type"] == "ai_image":
                shot["full_prompt"] = f"{shot['prompt']}. {style}. {GUARD}"
                if animated < animate_per_scene:
                    shot["animate"] = True
                    animated += 1
            # keep an image you already approved if the shot didn't change
            prev = old.get(shot_id)
            if prev and prev.get("image") and prev.get("prompt") == shot["prompt"] and \
                    prev.get("text") == shot["text"] and prev.get("type") == shot["type"]:
                shot["image"] = prev["image"]
                shot["clip"] = prev.get("clip")
            shots.append(shot)
    shots.append({"shot_id": "CREDITS-01", "scene_id": "CREDITS", "type": "credits", "prompt": "",
                  "text": "", "weight": 1, "camera": "static", "animate": False, "label_ai": False,
                  "seconds": 10})
    ep.save_storyboard({"style": style_name, "mode": mode, "built_at": utc_now(), "shots": shots})
    ctx.log(f"Storyboard: {len(shots)} shots across {len(script['scenes'])} scenes.")


def check(ep: Episode) -> list[Check]:
    board = ep.storyboard()
    if not board.get("shots"):
        return [Check(BLOCK, "No storyboard yet. Run this stage.")]
    packet = read_json(ep.path("research.json")) or {"claims": [], "restrictions": []}
    excerpts = _excerpts(packet)
    names = person_names()
    rules = {r["rule"] for r in packet.get("restrictions", [])}
    out: list[Check] = []
    script_ids = set()
    if ep.path("script.md").exists():
        script_ids = {s["scene_id"] for s in parse(ep.path("script.md").read_text(encoding="utf-8"))["scenes"]}
    board_ids = {s["scene_id"] for s in board["shots"]} - {"CREDITS"}
    if script_ids and script_ids != board_ids:
        out.append(Check(BLOCK, "The script changed since this storyboard was made. Run it again."))
    for s in board["shots"]:
        sid = s["shot_id"]
        if s["type"] == "ai_image":
            found = names_in(s["prompt"], names)
            if found:
                out.append(Check(BLOCK, f"{sid}: the image prompt names a real person "
                                        f"({', '.join(found)}). AI never draws real people."))
            if not s["prompt"]:
                out.append(Check(BLOCK, f"{sid}: picture shot with no prompt."))
            if "no_footage" in rules or "no_person_imagery" in rules:
                out.append(Check(WARN, f"{sid}: careful topic - make sure this picture shows no "
                                       "victims and no scene of the event."))
        if s["type"] == "quote_card":
            e = excerpts.get(s.get("excerpt_id") or -1)
            if not e:
                out.append(Check(BLOCK, f"{sid}: quote card without a verified quote (E-number)."))
            elif normalize_for_match(s["text"]) not in normalize_for_match(e["text"]):
                out.append(Check(BLOCK, f"{sid}: quote card text doesn't match verified quote "
                                        f"E{e['excerpt_id']} word for word."))
        if s["type"] == "receipt" and not s.get("source_id"):
            out.append(Check(BLOCK, f"{sid}: a receipt shot must name the source it shows."))
        if s["type"] == "title_card" and len(s["text"].split()) > 10:
            out.append(Check(WARN, f"{sid}: title card text is long."))
    receipts = sum(1 for s in board["shots"] if s["type"] == "receipt")
    if receipts:
        out.append(Check(WARN, f"{receipts} receipt shot(s) need a real screenshot or scan saved "
                               "in the episode's receipts/ folder as <shot id>.png before Images "
                               "can be approved."))
    animated = sum(1 for s in board["shots"] if s.get("animate"))
    out.append(Check(OK, f"{len(board['shots'])} shots, {animated} marked to animate."))
    return out
