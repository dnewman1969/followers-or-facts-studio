"""Storyboard: three candidate pictures for every scene; you pick which to use.

For each scene the local AI writes three different picture ideas (a wide establishing
view, a close detail, and a symbolic image), ComfyUI paints each one, and the program
stamps "AI illustration" on them. You tick the ones you want (one or more per scene)
and can remake any candidate. Title cards and verified quote cards are added
automatically, drawn as text so quotes are always exact.
"""

from __future__ import annotations

from typing import Any

from .. import cards, db
from ..comfy import new_seed, run_template
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
VARIANTS = ["wide establishing view", "close-up detail", "symbolic or metaphorical image"]

IDEAS_SCHEMA = {
    "type": "object",
    "properties": {"ideas": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3}},
    "required": ["ideas"],
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


def _excerpts(ep: Episode) -> dict[int, dict[str, Any]]:
    packet = read_json(ep.path("research.json")) or {}
    out = {}
    for c in packet.get("claims", []):
        for e in c.get("excerpts", []):
            out[e["excerpt_id"]] = e
    return out


def _ideas(scene: dict[str, Any], restrictions: list[str]) -> list[str]:
    answer = Ollama().chat_json([
        {"role": "system", "content": (
            "You are a documentary art director. Write three different picture ideas for one "
            "narrated scene: 1) a wide establishing view, 2) a close-up detail, 3) a symbolic or "
            "metaphorical image. Each is one or two sentences describing objects, places, documents, "
            "crowds seen from behind, light and mood. Never name a real person. Never ask for "
            "readable text, signs or logos.")},
        {"role": "user", "content": f"Scene visual note: {scene['visual']}\nNarration: {scene['narration']}\n"
                                    f"Careful-topic rules: {restrictions or 'none'}"},
    ], IDEAS_SCHEMA, temperature=0.7)
    ideas = [i.strip() for i in answer.get("ideas", []) if i.strip()][:3]
    while len(ideas) < 3:
        ideas.append(f"{scene['visual']} ({VARIANTS[len(ideas)]})")
    return ideas


def _paint(ep: Episode, scene_id: str, n: int, prompt: str, style: str) -> dict[str, Any]:
    cfg = settings()["comfyui"]
    seed = new_seed()
    full = f"{prompt}. {style}. {GUARD}"
    saved, meta = run_template("image_workflow", {
        "PROMPT": full, "SEED": seed, "WIDTH": cfg["image_width"], "HEIGHT": cfg["image_height"],
        "FILENAME_PREFIX": f"fof/{ep.project_id}/{scene_id}-{n}",
    }, ep.path("images", "raw", f"{scene_id}-c{n}-{seed}"))
    labeled = cards.ai_label(saved[0], ep.path("images", f"{scene_id}-c{n}.png"))
    return {"path": ep.rel(labeled), "raw": ep.rel(saved[0]), "prompt": prompt, "full_prompt": full,
            "seed": seed, "model": cfg["image_model_name"], "workflow": meta["workflow"], "made_at": utc_now()}


def _cards(ep: Episode, scene: dict[str, Any], excerpts: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    size = (settings()["video"]["width"], settings()["video"]["height"])
    out = []
    text = scene["on_screen_text"]
    if text and text != "-":
        p = cards.title_card(text, ep.path("images", f"{scene['scene_id']}-title.png"), size)
        out.append({"type": "title_card", "text": text, "path": ep.rel(p)})
    for k, quote in enumerate(quotes_in(scene["narration"])):
        match = next((e for e in excerpts.values()
                      if normalize_for_match(quote) in normalize_for_match(e["text"])), None)
        if not match:
            continue
        src = db.one("SELECT title, publisher, date FROM source WHERE source_id=?", (match["source_id"],)) or {}
        attribution = ", ".join(x for x in (src.get("publisher") or src.get("title"), src.get("date")) if x)
        p = cards.quote_card(quote, attribution or "Source on file",
                             ep.path("images", f"{scene['scene_id']}-quote{k}.png"), size)
        out.append({"type": "quote_card", "text": quote, "excerpt_id": match["excerpt_id"],
                    "source_id": match["source_id"], "path": ep.rel(p)})
    return out


def run(ctx: Context) -> None:
    ep = ctx.episode
    if not ep.path("script.md").exists():
        raise StageError("Approve the Script first.")
    script = parse(ep.path("script.md").read_text(encoding="utf-8"))
    packet = read_json(ep.path("research.json")) or {}
    restrictions = [f"{r['rule']} ({r['subject_id']})" for r in packet.get("restrictions", [])]
    excerpts = _excerpts(ep)
    board = ep.storyboard() or {}
    style_name = ctx.options.get("style") or board.get("style") or "documentary"
    style = STYLES.get(style_name, STYLES["documentary"])
    remake = ctx.options.get("remake") or []  # ["SCENE_002:1", ...]
    old = {s["scene_id"]: s for s in board.get("scenes", [])}
    scenes = []
    total = len(script["scenes"])
    for n, sc in enumerate(script["scenes"]):
        ctx.check_cancel()
        sid = sc["scene_id"]
        prev = old.get(sid)
        same = prev and prev.get("visual") == sc["visual"] and prev.get("narration") == sc["narration"]
        entry = {"scene_id": sid, "visual": sc["visual"], "narration": sc["narration"],
                 "ideas": prev["ideas"] if same else None,
                 "candidates": prev["candidates"] if same else [None, None, None],
                 "picked": prev.get("picked", []) if same else [],
                 "cards": _cards(ep, sc, excerpts)}
        if not entry["ideas"]:
            ctx.progress(f"Planning pictures for {sid} ({n + 1}/{total})", 100 * n / total)
            entry["ideas"] = _ideas(sc, restrictions)
        for k in range(3):
            ctx.check_cancel()
            have = entry["candidates"][k] and ep.abs(entry["candidates"][k]["path"]).exists()
            if have and f"{sid}:{k}" not in remake:
                continue
            ctx.progress(f"Painting {sid} picture {k + 1} of 3 ({n + 1}/{total} scenes)",
                         100 * (n + (k + 1) / 3) / total)
            entry["candidates"][k] = _paint(ep, sid, k, entry["ideas"][k], style)
            if k in entry["picked"] and f"{sid}:{k}" in remake:
                entry["picked"].remove(k)
        scenes.append(entry)
        # save after every scene so a crash or Cancel keeps the pictures already made
        rest = [old[x["scene_id"]] for x in script["scenes"][n + 1:] if x["scene_id"] in old]
        ep.save_storyboard({"style": style_name, "scenes": scenes + rest, "built_at": utc_now(), "partial": True})
    ep.save_storyboard({"style": style_name, "scenes": scenes, "built_at": utc_now()})
    ctx.progress("Pictures ready. Pick the ones to use for each scene.", 100)


def set_picks(ep: Episode, scene_id: str, picked: list[int]) -> None:
    board = ep.storyboard()
    for s in board.get("scenes", []):
        if s["scene_id"] == scene_id:
            s["picked"] = sorted(set(picked))
    ep.save_storyboard(board)


def set_idea(ep: Episode, scene_id: str, index: int, idea: str) -> None:
    board = ep.storyboard()
    for s in board.get("scenes", []):
        if s["scene_id"] == scene_id:
            s["ideas"][index] = idea
    ep.save_storyboard(board)


def shots(ep: Episode) -> list[dict[str, Any]]:
    """The pictures that go on to the Video stage: your picks, then that scene's cards."""
    out = []
    for s in ep.storyboard().get("scenes", []):
        for k in s.get("picked", []):
            c = s["candidates"][k]
            if c:
                out.append({"shot_id": f"{s['scene_id']}-p{k}", "scene_id": s["scene_id"], "type": "ai_image",
                            "image": c, "prompt": c["prompt"]})
        for j, card in enumerate(s.get("cards", [])):
            out.append({"shot_id": f"{s['scene_id']}-k{j}", "scene_id": s["scene_id"], "type": card["type"],
                        "image": {"path": card["path"]}, "text": card["text"]})
    return out


def check(ep: Episode) -> list[Check]:
    board = ep.storyboard()
    if not board.get("scenes"):
        return [Check(BLOCK, "No pictures yet. Press Make pictures.")]
    out: list[Check] = []
    if ep.path("script.md").exists():
        script_ids = [s["scene_id"] for s in parse(ep.path("script.md").read_text(encoding="utf-8"))["scenes"]]
        if script_ids != [s["scene_id"] for s in board["scenes"]]:
            out.append(Check(BLOCK, "The script changed since these pictures were made. Make pictures again "
                                    "(pictures for unchanged scenes are kept)."))
    names = person_names()
    excerpts = _excerpts(ep)
    for s in board["scenes"]:
        if not s.get("picked"):
            out.append(Check(BLOCK, f"{s['scene_id']}: pick at least one picture."))
        for k in s.get("picked", []):
            c = s["candidates"][k]
            if not c or not ep.abs(c["path"]).exists():
                out.append(Check(BLOCK, f"{s['scene_id']}: picked picture {k + 1} is missing; remake it."))
            elif names_in(c["prompt"], names):
                out.append(Check(BLOCK, f"{s['scene_id']} picture {k + 1}: the idea names a real person "
                                        f"({', '.join(names_in(c['prompt'], names))}). AI never draws real people."))
        for card in s.get("cards", []):
            if card["type"] == "quote_card":
                e = excerpts.get(card.get("excerpt_id"))
                if not e or normalize_for_match(card["text"]) not in normalize_for_match(e["text"]):
                    out.append(Check(BLOCK, f"{s['scene_id']}: a quote card doesn't match its verified quote."))
    if not any(c.level == BLOCK for c in out):
        n = sum(len(s["picked"]) for s in board["scenes"])
        out.append(Check(OK, f"{n} pictures picked across {len(board['scenes'])} scenes."))
    return out
