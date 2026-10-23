"""Storyboard: enough different pictures to cover the whole video, so nothing repeats.

For every scene the program works out how long Owlbert will talk (its words at the style's pace)
and how many shots that needs (the style's shot length), then the local AI writes that many shot
ideas, in order, following the narration. Each shot is one of:
    broll       a picture of places, objects, documents, crowds from behind (any style)
    owl         Owlbert himself: the AI paints the set, then his real artwork is placed in it, so he
                looks the same in every shot (and stays on model when it's animated)
    caricature  a cartoon caricature of a public figure who sold the lie (only in styles that allow
                it, only with your approved design, never on careful topics; see cast.py)
ComfyUI paints each shot a couple of different ways; the first is used unless you pick another.
Title cards, verified quote cards and Owlbert's "Tell" card (the trick he names) are drawn as text,
so quotes are always exact.
"""

from __future__ import annotations

import math
from typing import Any

from PIL import Image, ImageFilter

from .. import cards, cast, db, styles, techniques
from ..comfy import new_seed, run_template
from ..config import settings
from ..episode import Episode
from ..llm import Ollama
from ..scriptfmt import parse, quotes_in
from ..util import StageError, normalize_for_match, read_json, utc_now
from .base import BLOCK, OK, WARN, Check, Context

GUARD = ("no text, no letters, no words, no watermark, no logos, "
         "no recognizable real people, faces turned away or in silhouette")
CARICATURE_GUARD = ("clearly a cartoon caricature drawing, not a photograph, no text, no letters, no logos, "
                    "no speech bubbles")
OWL_SET = "an empty set with no people and no animals, room on one side for a character"
CAMERA_MOVES = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "dolly_in", "static"]
CARD_SECONDS = {"title_card": 3.0, "quote_card": 6.0, "technique_card": 6.0}
VERSION = 2

# kept so old settings files that name a picture style still work
STYLES = {k: v.look for k, v in styles.STYLES.items()}


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


# ---------------------------------------------------------------- how many shots
def scene_seconds(sc: dict[str, Any], style: styles.Style) -> float:
    return len(sc["narration"].split()) / (style.wpm / 60) + 1.0


def shots_needed(sc: dict[str, Any], style: styles.Style, card_seconds: float) -> int:
    limit = int(settings()["storyboard"].get("shot_limit_per_scene", 24))
    room = max(style.shot_seconds, scene_seconds(sc, style) - card_seconds)
    return max(1, min(limit, math.ceil(room / style.shot_seconds)))


# ---------------------------------------------------------------- shot ideas
def _plan_shots(sc: dict[str, Any], n: int, style: styles.Style, kinds: list[str], people: list[dict[str, Any]],
                restrictions: list[str], on_text=None) -> list[dict[str, Any]]:
    schema = {"type": "object", "properties": {"shots": {"type": "array", "minItems": n, "maxItems": n, "items": {
        "type": "object", "properties": {
            "kind": {"type": "string", "enum": kinds},
            "idea": {"type": "string"},
            "person_id": {"type": "string"}},
        "required": ["kind", "idea", "person_id"]}}}, "required": ["shots"]}
    who = ("\nCaricature cast you may use (by person_id; describe what they're DOING from the narration, never "
           f"their looks or name, those are added automatically): {[{'person_id': p['person_id'], 'who': p.get('role_types')} for p in people]}"
           if "caricature" in kinds else "")
    answer = Ollama().chat_json([
        {"role": "system", "content": (
            f"You are the art director for a {style.name} video. Plan a sequence of {n} different shots that "
            "follow the narration in order, so the pictures change as Owlbert talks and never repeat. Each idea is "
            "one or two sentences: the subject, the setting, the framing (wide, medium, close-up, overhead...), the "
            "light and mood, in this style. Vary the framing from shot to shot. Kinds: 'broll' = places, objects, "
            "documents, crowds seen from behind, visual metaphors; 'owl' = Owlbert the owl professor appears (just "
            "describe the set and what he's doing, he's added from his artwork); 'caricature' = a cartoon "
            "caricature of one of the cast doing the documented thing the narration describes. Never name a real "
            "person. Never ask for readable text, signs or logos. Use person_id \"\" unless the kind is caricature.")},
        {"role": "user", "content": f"Style: {style.look}\nOwlbert's scenes look like: {style.owl_look}\n"
                                    f"Scene visual note: {sc['visual']}\nNarration: {sc['narration']}\n"
                                    f"Careful-topic rules: {restrictions or 'none'}{who}"},
    ], schema, temperature=0.7, on_text=on_text)
    allowed = {p["person_id"] for p in people}
    out = []
    for x in (answer.get("shots") or [])[:n]:
        kind = x.get("kind") if x.get("kind") in kinds else "broll"
        pid = (x.get("person_id") or "").strip()
        if kind == "caricature" and pid not in allowed:
            kind, pid = "broll", ""
        out.append({"kind": kind, "idea": (x.get("idea") or "").strip() or sc["visual"],
                    "person_id": pid if kind == "caricature" else ""})
    while len(out) < n:  # the model came back short: fill from the scene's own visual note, varied framing
        framing = ["wide establishing view", "close-up detail", "overhead view", "symbolic image"][len(out) % 4]
        out.append({"kind": "broll", "idea": f"{sc['visual']} ({framing})", "person_id": ""})
    return out


# ---------------------------------------------------------------- painting
def _comfy_image(ep: Episode, name: str, prompt: str) -> tuple[Any, dict[str, Any], int]:
    cfg = settings()["comfyui"]
    seed = new_seed()
    saved, meta = run_template("image_workflow", {
        "PROMPT": prompt, "SEED": seed, "WIDTH": cfg["image_width"], "HEIGHT": cfg["image_height"],
        "FILENAME_PREFIX": f"fof/{ep.project_id}/{name}",
    }, ep.path("images", "raw", f"{name}-{seed}"))
    return saved[0], meta, seed


def _place_owlbert(background, out, side: int) -> None:
    """Put Owlbert's real artwork into a painted set: same owl in every shot."""
    from ..owl import base
    bg = Image.open(background).convert("RGB")
    owl = base()
    owl = owl.crop(owl.getbbox())
    h = int(bg.height * 0.66)
    owl = owl.resize((int(owl.width * h / owl.height), h), Image.LANCZOS)
    if side:
        owl = owl.transpose(Image.FLIP_LEFT_RIGHT)
    x = int(bg.width * 0.08) if side == 0 else bg.width - owl.width - int(bg.width * 0.08)
    y = bg.height - owl.height - int(bg.height * 0.04)
    shadow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    sh = owl.split()[-1].point(lambda a: int(a * 0.45))
    shadow.paste((0, 0, 0, 255), (x + 14, y + 18), sh)
    canvas = bg.convert("RGBA")
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    canvas.alpha_composite(owl, (x, y))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out)


def _paint(ep: Episode, shot: dict[str, Any], k: int, style: styles.Style, people: dict[str, dict[str, Any]]
           ) -> dict[str, Any]:
    name = f"{shot['shot_id']}-c{k}"
    cfg = settings()["comfyui"]
    if shot["kind"] == "caricature":
        person = people[shot["person_id"]]
        full = f"{shot['idea']}. The character: {person['design']}. {style.look}. {CARICATURE_GUARD}"
    elif shot["kind"] == "owl":
        full = f"{shot['idea']}. {OWL_SET}. {style.look}. {GUARD}"
    else:
        full = f"{shot['idea']}. {style.look}. {GUARD}"
    full += f". Avoid: {style.negative}, washed out, low contrast"
    raw, meta, seed = _comfy_image(ep, name, full)
    picture = raw
    if shot["kind"] == "owl":
        picture = ep.path("images", "raw", f"{name}-{seed}-owl.png")
        _place_owlbert(raw, picture, side=k % 2)
    labeled = cards.ai_label(picture, ep.path("images", f"{name}.png"))
    if shot["kind"] == "caricature":
        labeled = cards.name_caption(labeled, labeled, people[shot["person_id"]]["name"])
    return {"path": ep.rel(labeled), "raw": ep.rel(picture), "prompt": shot["idea"], "full_prompt": full,
            "seed": seed, "model": cfg["image_model_name"], "workflow": meta["workflow"], "made_at": utc_now()}


def _cards(ep: Episode, scene: dict[str, Any], excerpts: dict[int, dict[str, Any]],
           story_techniques: list[str]) -> list[dict[str, Any]]:
    size = (settings()["video"]["width"], settings()["video"]["height"])
    out = []
    text = scene["on_screen_text"]
    if scene.get("role") == "tell":
        tech = next((techniques.get(k) for k in story_techniques if techniques.get(k)), None) or \
            next((t for t in techniques.TECHNIQUES.values()
                  if normalize_for_match(t.name) in normalize_for_match(f"{text} {scene['narration']}")), None)
        if tech:
            p = cards.technique_card(tech.name, tech.meaning, tech.ask,
                                     ep.path("images", f"{scene['scene_id']}-tell.png"), size)
            out.append({"type": "technique_card", "text": tech.name, "technique": tech.key, "path": ep.rel(p)})
    elif text and text != "-":
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
    creative = ep.creative()
    if ctx.options.get("style"):
        ep.set_creative(style=ctx.options["style"])
        creative = ep.creative()
    style = styles.get(creative["style"])
    from .stories import chosen
    story_tech = (chosen(ep) or {}).get("techniques", [])
    n_cands = max(1, min(3, int(settings()["storyboard"].get("candidates_per_shot", 2))))
    people = {p["person_id"]: p for p in cast.approved(ep)} if creative["caricatures"] else {}
    board = ep.storyboard() or {}
    old = {s["scene_id"]: s for s in board.get("scenes", [])} if board.get("version") == VERSION else {}
    redo_ids = set(ctx.options.get("remake") or [])   # ["SCENE_002-s03:1", ...] or whole shots "SCENE_002-s03"
    replan = set(ctx.options.get("replan") or [])     # scene ids to plan again
    scenes: list[dict[str, Any]] = []
    total = len(script["scenes"])
    for n, sc in enumerate(script["scenes"]):
        ctx.check_cancel()
        sid = sc["scene_id"]
        prev = old.get(sid)
        same = (prev and prev.get("visual") == sc["visual"] and prev.get("narration") == sc["narration"]
                and prev.get("style") == style.key and sid not in replan)
        card_list = _cards(ep, sc, excerpts, story_tech)
        entry = {"scene_id": sid, "role": sc.get("role", ""), "visual": sc["visual"], "narration": sc["narration"],
                 "style": style.key, "seconds": round(scene_seconds(sc, style), 1), "cards": card_list,
                 "claim_ids": sc.get("claim_ids", []), "source_ids": sc.get("source_ids", [])}
        if same:
            entry["shots"] = prev["shots"]
        else:
            kinds = [k for k in style.shot_types if k in ("broll", "owl", "caricature")] or ["broll"]
            if "owl" not in kinds:
                kinds.append("owl")
            scene_people = [p for p in people.values() if set(p["claims"]) & set(sc.get("claim_ids", []))] \
                if sc.get("source_ids") else []   # caricatures only in scenes that cite the documented act
            if not scene_people and "caricature" in kinds:
                kinds.remove("caricature")
            need = shots_needed(sc, style, sum(CARD_SECONDS.get(c["type"], 4) for c in card_list))
            ctx.progress(f"Planning {need} shots for {sid} ({n + 1}/{total})", 100 * n / total)
            ideas = _plan_shots(sc, need, style, kinds, scene_people, restrictions,
                                on_text=ctx.writing(f"Planning {need} shots for {sid}", 100 * n / total,
                                                    100 * (n + 0.1) / total, need * 30))
            entry["shots"] = [{"shot_id": f"{sid}-s{i + 1:02d}", **idea, "candidates": [None] * n_cands, "pick": 0}
                              for i, idea in enumerate(ideas)]
        shots = entry["shots"]
        for j, shot in enumerate(shots):
            while len(shot["candidates"]) < n_cands:
                shot["candidates"].append(None)
            for k in range(len(shot["candidates"])):
                ctx.check_cancel()
                c = shot["candidates"][k]
                have = c and ep.abs(c["path"]).exists()
                if have and f"{shot['shot_id']}:{k}" not in redo_ids and shot["shot_id"] not in redo_ids:
                    continue
                if shot["kind"] == "caricature" and shot["person_id"] not in people:
                    shot["kind"], shot["person_id"] = "broll", ""
                ctx.progress(f"Painting {shot['shot_id']} ({shot['kind']}), version {k + 1} of {len(shot['candidates'])} "
                             f"- scene {n + 1} of {total}",
                             100 * (n + (j + (k + 1) / len(shot['candidates'])) / max(1, len(shots))) / total)
                shot["candidates"][k] = _paint(ep, shot, k, style, people)
        scenes.append(entry)
        rest = [old[x["scene_id"]] for x in script["scenes"][n + 1:] if x["scene_id"] in old]
        ep.save_storyboard({"version": VERSION, "style": style.key, "scenes": scenes + rest,
                            "built_at": utc_now(), "partial": True})
    ep.save_storyboard({"version": VERSION, "style": style.key, "scenes": scenes, "built_at": utc_now()})
    n_shots = sum(len(s["shots"]) for s in scenes)
    ctx.progress(f"{n_shots} shots painted. Look them over; pick a different version or remake any.", 100)


def set_pick(ep: Episode, shot_id: str, k: int) -> None:
    board = ep.storyboard()
    for s in board.get("scenes", []):
        for shot in s.get("shots", []):
            if shot["shot_id"] == shot_id:
                shot["pick"] = k
    ep.save_storyboard(board)


def set_use(ep: Episode, shot_id: str, use: bool) -> None:
    board = ep.storyboard()
    for s in board.get("scenes", []):
        for shot in s.get("shots", []):
            if shot["shot_id"] == shot_id:
                shot["skip"] = not use
    ep.save_storyboard(board)


def set_idea(ep: Episode, shot_id: str, idea: str) -> None:
    board = ep.storyboard()
    for s in board.get("scenes", []):
        for shot in s.get("shots", []):
            if shot["shot_id"] == shot_id:
                shot["idea"] = idea
    ep.save_storyboard(board)


# older storyboards (three pictures per scene, ticked) still work downstream
def set_picks(ep: Episode, scene_id: str, picked: list[int]) -> None:
    board = ep.storyboard()
    for s in board.get("scenes", []):
        if s["scene_id"] == scene_id:
            if "shots" in s:
                for i, shot in enumerate(s["shots"]):
                    shot["skip"] = i not in picked
            else:
                s["picked"] = sorted(set(picked))
    ep.save_storyboard(board)


def shots(ep: Episode) -> list[dict[str, Any]]:
    """The pictures that go on to the Video stage, in order: each shot's chosen version, then the cards."""
    out = []
    board = ep.storyboard()
    for s in board.get("scenes", []):
        if "shots" in s:
            for shot in s["shots"]:
                if shot.get("skip"):
                    continue
                pick = shot.get("pick", 0)
                c = shot["candidates"][pick] if 0 <= pick < len(shot["candidates"]) else None
                c = c or next((x for x in shot["candidates"] if x), None)
                if c:
                    out.append({"shot_id": shot["shot_id"], "scene_id": s["scene_id"], "type": "ai_image",
                                "kind": shot["kind"], "image": c, "prompt": c["prompt"],
                                "seconds": styles.get(s.get("style")).shot_seconds,
                                "person_id": shot.get("person_id", "")})
        else:
            for k in s.get("picked", []):
                c = s["candidates"][k]
                if c:
                    out.append({"shot_id": f"{s['scene_id']}-p{k}", "scene_id": s["scene_id"], "type": "ai_image",
                                "kind": "broll", "image": c, "prompt": c["prompt"]})
        for j, card in enumerate(s.get("cards", [])):
            out.append({"shot_id": f"{s['scene_id']}-k{j}", "scene_id": s["scene_id"], "type": card["type"],
                        "image": {"path": card["path"]}, "text": card["text"],
                        "seconds": CARD_SECONDS.get(card["type"], 4.0)})
    return out


def check(ep: Episode) -> list[Check]:
    board = ep.storyboard()
    if not board.get("scenes"):
        return [Check(BLOCK, "No pictures yet. Press Make pictures.")]
    out: list[Check] = []
    if board.get("version") != VERSION:
        out.append(Check(BLOCK, "These pictures were made by the older storyboard (too few shots, so pictures "
                                "repeated). Press Make pictures to plan enough shots for the whole video."))
        return out
    if ep.path("script.md").exists():
        script_ids = [s["scene_id"] for s in parse(ep.path("script.md").read_text(encoding="utf-8"))["scenes"]]
        if script_ids != [s["scene_id"] for s in board["scenes"]]:
            out.append(Check(BLOCK, "The script changed since these pictures were made. Make pictures again "
                                    "(pictures for unchanged scenes are kept)."))
    names = person_names()
    excerpts = _excerpts(ep)
    creative = ep.creative()
    style = styles.get(board.get("style"))
    approved = {p["person_id"]: p for p in cast.approved(ep)}
    seen_prompts: dict[str, str] = {}
    covered = 0.0
    for s in board["scenes"]:
        used = [sh for sh in s["shots"] if not sh.get("skip")]
        if not used and not s.get("cards"):
            out.append(Check(BLOCK, f"{s['scene_id']}: every shot is switched off; use at least one."))
        for sh in used:
            pick = sh.get("pick", 0)
            c = sh["candidates"][pick] if 0 <= pick < len(sh["candidates"]) else None
            if not c or not ep.abs(c["path"]).exists():
                out.append(Check(BLOCK, f"{sh['shot_id']}: the chosen picture is missing; remake it."))
                continue
            if names_in(c["full_prompt"] if sh["kind"] != "caricature" else c["prompt"], names):
                out.append(Check(BLOCK, f"{sh['shot_id']}: the picture idea names a real person "
                                        f"({', '.join(names_in(c['prompt'], names))}). Real people only appear as "
                                        "approved caricatures, drawn from their design."))
            key = normalize_for_match(c["prompt"])
            if key in seen_prompts:
                out.append(Check(WARN, f"{sh['shot_id']} repeats the idea of {seen_prompts[key]}. Change one."))
            seen_prompts[key] = sh["shot_id"]
            covered += style.shot_seconds
            if sh["kind"] == "caricature":
                p = approved.get(sh.get("person_id"))
                if creative["careful"]:
                    out.append(Check(BLOCK, f"{sh['shot_id']}: no caricatures on a careful topic (victims: courts "
                                            "and documents only). Switch this shot off or remake it as b-roll."))
                elif not creative["caricatures"] or not style.caricature:
                    out.append(Check(BLOCK, f"{sh['shot_id']}: caricatures are switched off for this video."))
                elif not p:
                    out.append(Check(BLOCK, f"{sh['shot_id']}: this person's caricature design isn't approved."))
                elif not s.get("source_ids") or not set(p["claims"]) & set(s.get("claim_ids", [])):
                    out.append(Check(BLOCK, f"{sh['shot_id']}: a caricature must show a documented act, so its scene "
                                            "has to cite a source about that person's claim."))
                elif names_in(p["design"], names):
                    out.append(Check(BLOCK, f"{sh['shot_id']}: the design text names a person; describe looks only."))
        for card in s.get("cards", []):
            covered += CARD_SECONDS.get(card["type"], 4.0)
            if card["type"] == "quote_card":
                e = excerpts.get(card.get("excerpt_id"))
                if not e or normalize_for_match(card["text"]) not in normalize_for_match(e["text"]):
                    out.append(Check(BLOCK, f"{s['scene_id']}: a quote card doesn't match its verified quote."))
    need = sum(s.get("seconds", 0) for s in board["scenes"])
    if covered < need * 0.8:
        out.append(Check(WARN, f"The pictures cover about {covered / 60:.1f} of the {need / 60:.1f} minutes of "
                               "narration, so some will hold longer on screen. Turn shots back on or press Make "
                               "pictures with a script that hasn't changed to fill the gaps."))
    if not any(c.level == BLOCK for c in out):
        n = sum(1 for s in board["scenes"] for sh in s["shots"] if not sh.get("skip"))
        car = sum(1 for s in board["scenes"] for sh in s["shots"] if sh["kind"] == "caricature" and not sh.get("skip"))
        out.append(Check(OK, f"{n} shots across {len(board['scenes'])} scenes in the {style.name} style "
                             f"(about {covered / 60:.1f} minutes of pictures)"
                             + (f", {car} caricature shot(s)" if car else "") + "."))
    return out
