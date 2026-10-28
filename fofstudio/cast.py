"""The cast for caricature styles: public figures who SOLD a lie, drawn as clearly-cartoon caricatures.

Guardrails (from the research report "Creative styles and studio polish"; not legal advice):
- Only people linked to this video's ticked claims as the ones who said, amplified, platformed or
  profited from them. Never victims, targets, families, believers or private people.
- Never on careful topics (victims: courts and documents only).
- A fixed written design per person (hair, glasses, build, clothes, props) that YOU approve once.
  Prompts use the design, never the name, so the picture model draws a cartoon, not a photo likeness.
- Cartoon styles only (no photographic style), labelled on screen with "Caricature: <name>" and
  "AI illustration", and only in scenes that cite the documented act they're shown doing.
- No speech bubbles: the only words put in their mouths are verified quotes, shown as quote cards.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import db
from .episode import Episode
from .util import utc_now

SELLER_ROLES = ("said_it", "amplified", "benefited", "platformed")
NEVER = ("victim", "target", "family", "families", "attorney", "ex-wife", "wife", "husband", "child", "children",
         "minor", "teen", "kid", "boy", "girl", "baby", "student", "private", "parent", "survivor", "witness")
# Dave's rule (2026-10-28): public figures who sold the claim may be caricatured; a victim's or a child's
# likeness is never used, in any form (caricature, real photo or re-creation).
DESIGN_SCHEMA = {"type": "object", "properties": {"design": {"type": "string"}}, "required": ["design"]}


def _never(p: dict[str, Any]) -> bool:
    text = f"{p.get('role_types') or ''}".lower()
    return any(w in text for w in NEVER)


def eligible(ep: Episode, claim_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """People who may be caricatured in this episode, with their design if one exists."""
    from .stages.script import selected_packet
    if claim_ids is None:
        claim_ids = [c["claim_id"] for c in selected_packet(ep)["claims"]]
    if not claim_ids or ep.creative()["careful"]:
        return []
    marks = ",".join("?" * len(claim_ids))
    roles = ",".join("?" * len(SELLER_ROLES))
    rows = db.rows(f"""SELECT p.person_id, p.name, p.role_types, p.status, GROUP_CONCAT(DISTINCT ce.claim_id) AS claims,
                              GROUP_CONCAT(DISTINCT ce.link_role) AS roles
                       FROM claim_entity ce JOIN person p ON p.person_id = ce.entity_id
                       WHERE ce.entity_type='person' AND ce.claim_id IN ({marks}) AND ce.link_role IN ({roles})
                       GROUP BY p.person_id ORDER BY COUNT(*) DESC, p.name""",
                   (*claim_ids, *SELLER_ROLES))
    out = []
    for r in rows:
        if _never(r):
            continue
        d = db.one("SELECT design, approved FROM caricature WHERE person_id=?", (r["person_id"],)) or {}
        out.append({**r, "claims": (r["claims"] or "").split(","), "design": d.get("design") or "",
                    "approved": bool(d.get("approved")), "deceased": (r.get("status") or "") == "deceased"})
    return out


def approved(ep: Episode, claim_ids: list[str] | None = None) -> list[dict[str, Any]]:
    return [p for p in eligible(ep, claim_ids) if p["approved"] and p["design"]]


def save(person_id: str, design: str, ok: bool) -> None:
    db.execute("""INSERT INTO caricature(person_id, design, approved, approved_at) VALUES (?,?,?,?)
                  ON CONFLICT(person_id) DO UPDATE SET design=excluded.design, approved=excluded.approved,
                  approved_at=excluded.approved_at""",
               (person_id, design.strip(), int(ok), utc_now() if ok else None))


# ------------------------------------------------------------------ caricature traditions
DEFAULT_TRADITION = "urbane_magazine_editorial_illustration"


def traditions(include_excluded: bool = False) -> list[dict[str, Any]]:
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "data" / "caricature_traditions.json").read_text(encoding="utf-8"))
    return [t for t in data["traditions"] if include_excluded or t["tier"] != "exclude"]


def tradition(ep: Episode) -> dict[str, Any]:
    key = ep.creative().get("caricature_style") or DEFAULT_TRADITION
    ts = {t["key"]: t for t in traditions()}
    return ts.get(key) or ts[DEFAULT_TRADITION]


def caricature_look(ep: Episode, style) -> str:
    """The picture recipe for a caricature shot: in the satire style the chosen tradition IS the look; in any
    other cartoon style the style's own medium stays (one medium per video) with big-head proportions."""
    t = tradition(ep)
    if style.key == "satire":
        return ", ".join(t["prompt_elements"][:5]) + ", 16:9"
    return f"{style.look}, cartoon caricature with an exaggerated big head on a smaller body"


# ------------------------------------------------------------------ designing from free reference photos
# The professional method (research "Art styles caricatures and hybrids"): compare the face with an average
# face, find the one to three biggest differences (head shape, the eyes-and-nose "T"), push those and simplify
# the rest. Several photos, never one; only what most photos agree on. Kindness rules: never push skin,
# weight, disability, age or anything tied to race, ethnicity or religion (there are no fields for them);
# exaggerate the act and a signature prop, not the body. No face measurements or face-ID are ever made:
# a vision model answers plain multiple-choice questions, and no photo ever goes to the image model.
FACE_FIELDS: dict[str, list[str]] = {
    "head_shape": ["oval", "round", "long", "square", "rectangular", "heart-shaped", "pear-shaped", "egg-shaped"],
    "forehead": ["low", "average", "high"],
    "hair_volume": ["bald", "very short", "short", "medium", "long", "voluminous"],
    "hair_style": ["slicked back", "side part", "combed over", "swept up", "curly", "wavy", "straight", "crew cut",
                   "shaved", "ponytail", "receding"],
    "hair_colour": ["black", "dark brown", "brown", "light brown", "blond", "red", "grey", "white", "silver"],
    "brows": ["thin", "average", "thick", "bushy", "arched", "straight", "angled"],
    "eye_spacing": ["close-set", "average", "wide-set"],
    "eye_shape": ["round", "narrow", "hooded", "deep-set", "almond", "droopy"],
    "nose": ["small", "average", "long", "wide", "hooked", "upturned", "straight"],
    "mouth": ["small", "average", "wide"],
    "smile": ["closed-lip", "toothy grin", "lopsided", "rarely smiles"],
    "chin": ["small", "average", "pointed", "square", "cleft", "prominent"],
    "jaw": ["narrow", "average", "wide", "strong"],
    "ears": ["small", "average", "large", "prominent"],
    "glasses": ["none", "thin metal frames", "thick dark frames", "round frames", "rectangular frames",
                "rimless", "tinted"],
    "facial_hair": ["none", "stubble", "moustache", "goatee", "short beard", "full beard"],
    "expression": ["confident grin", "stern", "smug", "earnest", "intense", "cheerful", "serious", "animated"],
}
AVERAGE = {"average", "oval", "none"}
PUSHABLE = ("head_shape", "forehead", "hair_volume", "hair_style", "brows", "eye_spacing", "nose", "chin", "jaw",
            "smile")   # never body weight, skin or anything tied to race or religion: there are no fields for them
VISION_SCHEMA = {"type": "object", "properties": {
    "is_portrait": {"type": "boolean"},
    **{k: {"type": "string", "enum": v + ["can't tell"]} for k, v in FACE_FIELDS.items()}},
    "required": ["is_portrait", *FACE_FIELDS]}
MAX_LOOKS = 6     # photos the vision model looks at
MIN_LOOKS = 3     # never fewer: no single photo, so no one photographer's picture is copied


def find_references(person: dict[str, Any], limit: int = 12) -> list[dict[str, str]]:
    """Photos of a public figure to LOOK AT, from a normal web image search (like typing the name into an image
    search), plus their Wikipedia and Wikimedia Commons pictures. They're only looked at by the local vision
    model to describe the face in words; they're never used in a video, never sent to the picture maker, and
    deleted straight after."""
    name = person["name"]
    role = (person.get("role_types") or "").split("/")[0].strip()
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url: str, page: str, title: str, where: str) -> None:
        if url and url not in seen and not re.search(r"\.(svg|gif)(\?|$)", url, re.I):
            seen.add(url)
            out.append({"url": url, "page": page or url, "title": title or "", "from": where})

    try:   # the same free search package the research agents use (DuckDuckGo, Bing...)
        from ddgs import DDGS
        for query in (f"{name} {role}".strip(), f"{name} portrait"):
            for r in DDGS().images(query, max_results=12, safesearch="moderate"):
                add(r.get("image", ""), r.get("url", ""), r.get("title", ""), r.get("source") or "image search")
            if len(out) >= limit:
                break
    except Exception:  # noqa: BLE001 - search blocked or offline: the other finders still run
        pass
    try:
        from .agents import web
        data = web.get_json("https://en.wikipedia.org/w/api.php", {
            "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{name} {role}".strip(),
            "gsrlimit": 1, "prop": "pageimages", "piprop": "original"})
        for pg in (data.get("query") or {}).get("pages", {}).values():
            if name.split()[-1].lower() in pg.get("title", "").lower():
                add((pg.get("original") or {}).get("source", ""), "https://en.wikipedia.org/wiki/" +
                    pg["title"].replace(" ", "_"), pg["title"], "Wikipedia")
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import mediafinder
        for c in mediafinder.search_commons(name, limit=8):
            if name.split()[-1].lower() in c.title.lower():
                add(c.file_url, c.page_url, c.title, "Wikimedia Commons")
    except Exception:  # noqa: BLE001
        pass
    return out[:limit]


def _fetch_small(url: str, dest: Path) -> Path | None:
    """Download one photo and shrink it (the vision model only needs a face, and it's faster small)."""
    from io import BytesIO

    from PIL import Image

    from .agents import web
    try:
        r = web.session().get(url, timeout=20)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
    except Exception:  # noqa: BLE001 - a photo that won't load is skipped
        return None
    if min(img.size) < 160:
        return None
    img.thumbnail((768, 768))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=88)
    return dest


VISION_PROMPT = ("Look at the main person in this photo, as a cartoonist would. Answer with ONE JSON object and "
                 "nothing else. For each key pick one of the listed words, or \"can't tell\". Set is_portrait to "
                 "false if no single face is clearly visible. Describe what you see; don't guess who it is.\n"
                 + "\n".join(f"{k}: {' | '.join(v)}" for k, v in FACE_FIELDS.items())
                 + '\nExample: {"is_portrait": true, "head_shape": "oval", ...}')


def parse_vision(text: str) -> dict[str, Any]:
    """Read the vision model's answer (JSON if it gave JSON, else 'key: value' lines) into the allowed words."""
    raw: dict[str, Any] = {}
    m = re.search(r"\{.*\}", text or "", re.S)
    if m:
        try:
            raw = json.loads(m.group(0))
        except ValueError:
            raw = {}
    if not raw:
        for line in (text or "").splitlines():
            k, _, v = line.partition(":")
            raw[k.strip().strip('"').lower().replace(" ", "_")] = v.strip().strip('",')
    out: dict[str, Any] = {"is_portrait": str(raw.get("is_portrait", "true")).lower() not in ("false", "no", "0")}
    for field, allowed in FACE_FIELDS.items():
        v = str(raw.get(field, "")).strip().lower()
        hit = next((a for a in allowed if a == v), None) or next((a for a in allowed if a in v or v and v in a), None)
        out[field] = hit or "can't tell"
    return out


def vote(answers: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, dict[str, int]]]:
    """Majority of the photos for each field; a field without a clear majority stays empty for you to fill."""
    from collections import Counter
    votes: dict[str, dict[str, int]] = {}
    chosen: dict[str, str] = {}
    usable = [a for a in answers if a.get("is_portrait")]
    for f in FACE_FIELDS:
        c = Counter(a.get(f) for a in usable if a.get(f) and a.get(f) != "can't tell")
        votes[f] = dict(c)
        if c:
            value, n = c.most_common(1)[0]
            if n * 2 > len(usable):            # more than half the photos agree
                chosen[f] = value
    return chosen, votes


def compose_design(face: dict[str, str], cap: int = 3) -> tuple[str, list[str]]:
    """The cartoon design in words, from the agreed traits: push the 1-3 most unusual ones, keep it kind."""
    push = []
    for f in PUSHABLE:
        if face.get(f) and face[f] not in AVERAGE and not (f == "hair_style" and "hair_volume" in push):
            push.append(f)
    push = push[:3]
    big = "strongly exaggerated" if cap >= 4 else "exaggerated"
    bits = []
    hair = " ".join(x for x in (face.get("hair_colour"), face.get("hair_volume"), face.get("hair_style")) if x
                    and x != "bald")
    if face.get("hair_volume") == "bald":
        bits.append("bald head" + (" (exaggerated shine)" if "hair_volume" in push else ""))
    elif hair:
        bits.append(f"{hair} hair" + (f" ({big})" if {"hair_volume", "hair_style"} & set(push) else ""))
    if face.get("head_shape"):
        bits.append(f"{face['head_shape']} head" + (f" ({big})" if "head_shape" in push else ""))
    for f, label in (("forehead", "forehead"), ("brows", "eyebrows"), ("eye_spacing", "eyes"), ("nose", "nose"),
                     ("chin", "chin"), ("jaw", "jaw")):
        if face.get(f) and face[f] not in AVERAGE:
            bits.append(f"{face[f]} {label}" + (f" ({big})" if f in push else ""))
    if face.get("glasses") and face["glasses"] != "none":
        bits.append(f"{face['glasses']} glasses")
    if face.get("facial_hair") and face["facial_hair"] != "none":
        bits.append(face["facial_hair"])
    if face.get("smile"):
        bits.append(face["smile"] + (f" ({big})" if "smile" in push else ""))
    if face.get("expression"):
        bits.append(f"{face['expression']} expression")
    design = ("A clearly-cartoon caricature with a big head on a small body: " + ", ".join(bits) +
              ". Plain unbranded suit or everyday clothes, holding a prop tied to what they're documented doing "
              "(write it in).") if bits else ""
    return design, push


def research_design(person: dict[str, Any], on_progress=None) -> dict[str, Any]:
    """Look at 3-6 photos of the person with the local vision model and write a design for you to edit and
    approve. The photos are only looked at, then deleted."""
    import base64
    import shutil

    from .config import data_dir
    from .llm import Ollama, model_for
    from .util import StageError
    say = on_progress or (lambda *_: None)
    say(f"Searching for photos of {person['name']}")
    refs = find_references(person)
    if not refs:
        raise StageError(f"The image search found no photos of {person['name']} (it may be offline or busy). Try "
                         "again in a minute, or write the design yourself, using looks only.")
    folder = data_dir() / "caricature-refs" / person["person_id"]
    vision = model_for("vision")
    llm = Ollama(job="vision")
    answers, records = [], []
    try:
        for n, ref in enumerate(refs, 1):
            if sum(1 for a in answers if a.get("is_portrait")) >= MAX_LOOKS:
                break
            say(f"Looking at photo {n} of up to {len(refs)} (from {ref['from']})")
            path = _fetch_small(ref["url"], folder / f"look{n}.jpg")
            if not path:
                continue
            img = base64.b64encode(path.read_bytes()).decode()
            try:   # plain text, no answer format: some vision models get stuck on a forced format
                text = llm.chat([{"role": "user", "content": VISION_PROMPT, "images": [img]}], model=vision,
                                temperature=0.1)
            except StageError as exc:
                if "not found" in str(exc).lower() or "pull" in str(exc).lower():
                    raise StageError(f"The vision model {vision} isn't installed. In a command window run: "
                                     f"ollama pull {vision}") from exc
                continue
            a = parse_vision(text)
            answers.append(a)
            records.append({"page": ref["page"], "from": ref["from"], "title": ref["title"][:120],
                            "clear_face": a["is_portrait"]})
    finally:
        shutil.rmtree(folder, ignore_errors=True)   # only looked at: nothing is kept
    seen = sum(1 for a in answers if a.get("is_portrait"))
    if seen < MIN_LOOKS:
        raise StageError(f"The vision model saw a clear face in only {seen} of {len(answers)} photo(s) of "
                         f"{person['name']} ({MIN_LOOKS} are needed so the design isn't copied from one picture). "
                         "Try again, or write the design yourself, using looks only.")
    face, votes = vote(answers)
    design, push = compose_design(face)
    unsure = [f.replace("_", " ") for f in FACE_FIELDS if f not in face]
    return {"design": design, "face": face, "votes": votes, "push": push, "unsure": unsure,
            "references": records, "model": vision}


def save_research(person_id: str, result: dict[str, Any]) -> None:
    db.execute("""INSERT INTO caricature(person_id, design, approved, design_json, references_json)
                  VALUES (?,?,0,?,?) ON CONFLICT(person_id) DO UPDATE SET design_json=excluded.design_json,
                  references_json=excluded.references_json""",
               (person_id, result["design"], json.dumps({k: result[k] for k in ("face", "votes", "push", "unsure")}),
                json.dumps(result["references"])))


def propose(person: dict[str, Any]) -> str:
    """(Old way, kept only as a fallback the Cast window no longer offers: the AI recalls looks from a name.)"""
    from .llm import Ollama
    ans = Ollama(job="storyboard").chat_json([
        {"role": "system", "content": (
            "You design editorial-cartoon caricatures of public figures for a satire segment. Describe the "
            "cartoon in one or two sentences using only widely known, public visual traits: hair, facial hair, "
            "glasses, build, typical clothing, a signature prop or setting from their public work. Exaggerate "
            "for comedy (big head, small body). Never write the person's name, never describe a photograph, "
            "nothing sexual, nothing about race or ethnicity, nothing demeaning about the body beyond "
            "classic caricature exaggeration.")},
        {"role": "user", "content": f"Public figure: {person['name']} ({person.get('role_types') or ''}). "
                                    "Write the cartoon design."},
    ], DESIGN_SCHEMA, temperature=0.5)
    return (ans.get("design") or "").strip()


def names(ep: Episode) -> dict[str, str]:
    return {p["person_id"]: p["name"] for p in eligible(ep)}


def as_prompt(ep: Episode) -> str:
    return json.dumps([{"person_id": p["person_id"], "who": p.get("role_types"), "design": p["design"]}
                       for p in approved(ep)], ensure_ascii=False)
