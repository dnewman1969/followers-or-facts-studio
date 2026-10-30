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
    rows = db.rows(f"""SELECT p.person_id, p.name, p.role_types, p.status, p.orgs_text, p.aka, p.wiki_or_bio_url,
                              GROUP_CONCAT(DISTINCT ce.claim_id) AS claims,
                              GROUP_CONCAT(DISTINCT ce.link_role) AS roles
                       FROM claim_entity ce JOIN person p ON p.person_id = ce.entity_id
                       WHERE ce.entity_type='person' AND ce.claim_id IN ({marks}) AND ce.link_role IN ({roles})
                       GROUP BY p.person_id ORDER BY COUNT(*) DESC, p.name""",
                   (*claim_ids, *SELLER_ROLES))
    out = []
    for r in rows:
        if _never(r):
            continue
        d = record(r["person_id"])
        r["search_hint"] = d.get("search_hint") or default_hint(r)
        out.append({**r, "claims": (r["claims"] or "").split(","), "design": d.get("design") or "",
                    "approved": bool(d.get("approved")), "deceased": (r.get("status") or "") == "deceased",
                    **{k: d.get(k) for k in ("approved_at", "approved_in", "approved_in_title", "tradition",
                                             "picture", "used_in")}})
    return out


def approved(ep: Episode, claim_ids: list[str] | None = None) -> list[dict[str, Any]]:
    return [p for p in eligible(ep, claim_ids) if p["approved"] and p["design"]]


# ------------------------------------------------------------------ the caricature library (Dave, 2026-10-29)
# An approved caricature belongs to the PERSON, not the video: it's kept with their database record (design,
# the style it was approved in, the approved picture and where it was approved), so any later video about
# them starts with it already approved and draws them the same way. Previews are scratch; the approved
# picture is copied to <data>/caricatures/<person_id>/approved.png and only changes when you approve again.
def library_dir(person_id: str) -> Path:
    from .config import data_dir
    return data_dir() / "caricatures" / re.sub(r"[^A-Za-z0-9_-]", "_", person_id)


def record(person_id: str) -> dict[str, Any]:
    """Everything saved about how this person is drawn (empty if nothing yet)."""
    from .config import data_dir
    d = dict(db.one("SELECT * FROM caricature WHERE person_id=?", (person_id,)) or {})
    if not d:
        return {}
    pic = d.get("picture")
    d["picture"] = str(data_dir() / pic) if pic and (data_dir() / pic).exists() else ""
    try:
        d["used_in"] = json.loads(d.get("used_in") or "[]")
    except ValueError:
        d["used_in"] = []
    d["approved_in_title"] = ""
    if d.get("approved_in"):
        row = db.one("SELECT title FROM project WHERE project_id=?", (d["approved_in"],)) or {}
        d["approved_in_title"] = row.get("title") or d["approved_in"]
    return d


def library() -> list[dict[str, Any]]:
    """Every approved caricature, across all videos."""
    rows = db.rows("""SELECT c.person_id, p.name, p.role_types FROM caricature c JOIN person p
                      ON p.person_id = c.person_id WHERE c.approved=1 ORDER BY p.name""")
    return [{**record(r["person_id"]), "name": r["name"], "role_types": r["role_types"]} for r in rows]


def save(person_id: str, design: str, ok: bool, tradition: str | None = None, ep: Episode | None = None,
         picture: str | Path | None = None) -> None:
    """Save the design. Approving it keeps it with the person for every later video: the style, the video it
    was approved in and (if you painted previews) the picture you picked. Saving an already-approved design
    unchanged keeps its original approval."""
    import shutil
    old = record(person_id)
    design = design.strip()
    same = bool(old.get("approved")) and ok and (old.get("design") or "").strip() == design
    fields = {"design": design, "approved": int(ok),
              "approved_at": (old.get("approved_at") if same else utc_now()) if ok else None,
              # the person's style only changes when you approve a new design or pick a new picture
              "tradition": ((old.get("tradition") if same and not picture else tradition) or old.get("tradition"))
                           if ok else old.get("tradition"),
              "approved_in": (old.get("approved_in") if same and old.get("approved_in")
                              else (ep.project_id if ep else old.get("approved_in"))) if ok else old.get("approved_in"),
              "picture": None}
    rel = None
    if ok and picture and Path(picture).exists():
        from .config import data_dir
        dest = library_dir(person_id) / "approved.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if Path(picture).resolve() != dest.resolve():
            shutil.copyfile(picture, dest)
        rel = dest.relative_to(data_dir()).as_posix()
    elif ok and same and old.get("picture"):
        from .config import data_dir
        rel = Path(old["picture"]).relative_to(data_dir()).as_posix()
    elif not ok and old.get("picture"):
        from .config import data_dir
        rel = Path(old["picture"]).relative_to(data_dir()).as_posix()   # kept on file; not used until approved
    fields["picture"] = rel
    db.execute("""INSERT INTO caricature(person_id, design, approved, approved_at, tradition, approved_in, picture)
                  VALUES (:person_id,:design,:approved,:approved_at,:tradition,:approved_in,:picture)
                  ON CONFLICT(person_id) DO UPDATE SET design=excluded.design, approved=excluded.approved,
                  approved_at=excluded.approved_at, tradition=excluded.tradition,
                  approved_in=excluded.approved_in, picture=excluded.picture""",
               {"person_id": person_id, **fields})


def mark_used(ep: Episode, person_ids) -> None:
    """Note which videos drew each person (shown in the Cast window)."""
    for pid in {p for p in person_ids if p}:
        used = record(pid).get("used_in") or []
        if ep.project_id not in used:
            db.execute("UPDATE caricature SET used_in=? WHERE person_id=?", (json.dumps(used + [ep.project_id]), pid))


# ------------------------------------------------------------------ caricature traditions
DEFAULT_TRADITION = "urbane_magazine_editorial_illustration"


def traditions(include_excluded: bool = False) -> list[dict[str, Any]]:
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "data" / "caricature_traditions.json").read_text(encoding="utf-8"))
    return [t for t in data["traditions"] if include_excluded or t["tier"] != "exclude"]


def tradition(ep: Episode) -> dict[str, Any]:
    """The video's caricature style; if you haven't picked one, the style the cast was approved in (so a
    person approved in an earlier video is drawn the same way), else the house default."""
    ts = {t["key"]: t for t in traditions()}
    key = ep.creative().get("caricature_style")
    if not key:
        from collections import Counter

        from .util import StageError
        try:
            used = Counter(p["tradition"] for p in approved(ep) if p.get("tradition") in ts)
        except StageError:
            used = Counter()
        key = used.most_common(1)[0][0] if used else DEFAULT_TRADITION
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
MIN_LOOKS = 3     # fewer clear photos still works, with a warning to check the design


GENERIC = {"host", "guest", "amplifier", "seller", "video", "researcher", "academic", "the", "and", "of", "a",
           "an", "for", "on", "in", "said", "it", "show", "report"}


def default_hint(person: dict[str, Any]) -> str:
    """Who this is, for the photo search: their organisations and roles from the research database
    (e.g. "InfoWars; Host / amplifier"). You can change it in the Cast window."""
    parts = [x.strip() for x in ((person.get("orgs_text") or ""), (person.get("role_types") or "")) if x and x.strip()]
    return re.sub(r"\s+", " ", "; ".join(parts))[:160]


def hint_words(hint: str) -> list[str]:
    """The words in the description that pick out THIS person (e.g. "infowars", "conspiracy", "radio")."""
    words = re.findall(r"[a-z0-9][a-z0-9'-]{2,}", (hint or "").lower())
    return list(dict.fromkeys(w for w in words if w not in GENERIC))


def save_hint(person_id: str, hint: str) -> None:
    db.execute("""INSERT INTO caricature(person_id, design, approved, search_hint) VALUES (?, '', 0, ?)
                  ON CONFLICT(person_id) DO UPDATE SET search_hint=excluded.search_hint""", (person_id, hint.strip()))


def matches_hint(text: str, words: list[str]) -> int:
    low = (text or "").lower()
    return sum(1 for w in words if w in low)


def find_references(person: dict[str, Any], limit: int = 16) -> list[dict[str, str]]:
    """Photos of a public figure to LOOK AT, from a normal web image search (like typing the name into an image
    search), plus their Wikipedia and Wikimedia Commons pictures. They're only looked at by the local vision
    model to describe the face in words; they're never used in a video, never sent to the picture maker, and
    deleted straight after."""
    name = person["name"]
    hint = person.get("search_hint") or default_hint(person)
    words = hint_words(hint)
    key = " ".join(words[:4])          # e.g. "infowars conspiracy radio"
    out: list[dict[str, str]] = []
    unsure: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url: str, page: str, title: str, where: str, thumb: str = "") -> None:
        if url and url not in seen and not re.search(r"\.(svg|gif)(\?|$)", url, re.I):
            seen.add(url)
            out.append({"url": url, "thumb": thumb, "page": page or url, "title": title or "", "from": where})

    try:   # the same free search package the research agents use (DuckDuckGo, Bing...)
        from ddgs import DDGS
    except ImportError:
        DDGS = None
    for query in (f'"{name}" {key}'.strip(), f"{name} {hint}".strip()[:120]):
        for backend in ("auto", "bing", "duckduckgo"):   # one engine busy or refusing: try the next
            if DDGS is None:
                break
            try:
                hits = DDGS().images(query, max_results=15, safesearch="moderate", backend=backend)
            except Exception:  # noqa: BLE001
                continue
            for r in hits:
                about = f"{r.get('title', '')} {r.get('url', '')} {r.get('image', '')}"
                if words and matches_hint(about, words) == 0:
                    # a page that says nothing about who we mean may be someone else of that name: last resort only
                    unsure.append({"url": r.get("image", ""), "thumb": r.get("thumbnail", ""),
                                   "page": r.get("url", ""), "title": r.get("title", ""),
                                   "from": "image search (not confirmed)"})
                    continue
                add(r.get("image", ""), r.get("url", ""), r.get("title", ""), r.get("source") or "image search",
                    r.get("thumbnail", ""))
            if hits:
                break
        if len(out) >= limit:
            break
    try:
        from .agents import web
        bio = person.get("wiki_or_bio_url") or ""
        title = bio.rsplit("/wiki/", 1)[1] if "wikipedia.org/wiki/" in bio else ""
        params = ({"titles": title.replace("_", " ")} if title else
                  {"generator": "search", "gsrsearch": f"{name} {key}".strip(), "gsrlimit": 1})
        data = web.get_json("https://en.wikipedia.org/w/api.php", {
            "action": "query", "format": "json", "prop": "pageimages|extracts", "piprop": "original",
            "exintro": 1, "explaintext": 1, "exchars": 600, **params})
        for pg in (data.get("query") or {}).get("pages", {}).values():
            right = title or (not words or matches_hint(pg.get("extract", ""), words) > 0)
            if right and name.split()[-1].lower() in pg.get("title", "").lower():
                add((pg.get("original") or {}).get("source", ""), "https://en.wikipedia.org/wiki/" +
                    pg["title"].replace(" ", "_"), pg["title"], "Wikipedia")
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import mediafinder
        for c in mediafinder.search_commons(f"{name} {key}".strip(), limit=8):
            about = f"{c.title} {' '.join(c.notes)}"
            if name.split()[-1].lower() in c.title.lower() and (not words or matches_hint(about, words) > 0):
                add(c.file_url, c.page_url, c.title, "Wikimedia Commons")
    except Exception:  # noqa: BLE001
        pass
    if len(out) < MIN_LOOKS:   # too few pages named who we mean: use the search's own best guesses, marked
        for u in unsure:
            if u["url"] and u["url"] not in seen and len(out) < MIN_LOOKS * 2:
                seen.add(u["url"])
                out.append(u)
    return out[:limit]


def _fetch_small(ref: dict[str, str] | str, dest: Path) -> Path | None:
    """Download one photo, small (the vision model only needs the face). The image search's own thumbnail comes
    first: many photo sites refuse programs, but the search engine's thumbnail copy loads fine."""
    from io import BytesIO

    from PIL import Image

    from .agents import web
    if isinstance(ref, str):
        ref = {"url": ref}
    s = web.session()
    small = None
    for url, extra in ((ref.get("thumb"), {}),
                       (ref.get("url"), {"Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                                         "Referer": ref.get("page") or ""})):
        if not url:
            continue
        try:
            r = s.get(url, timeout=20, headers={k: v for k, v in extra.items() if v})
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")
        except Exception:  # noqa: BLE001 - try the next copy
            continue
        if min(img.size) < 120:
            continue
        if min(img.size) < 300 and small is None:   # a tiny thumbnail: the full photo shows the face better
            small = img
            continue
        small = img
        break
    if small is None:
        return None
    small.thumbnail((768, 768))
    dest.parent.mkdir(parents=True, exist_ok=True)
    small.save(dest, "JPEG", quality=88)
    return dest


VISION_PROMPT = ("Look at the main person in this photo, as a cartoonist would. Answer with ONE JSON object and "
                 "nothing else. For each key pick one of the listed words, or \"can't tell\". Set is_portrait to "
                 "false if no single face is clearly visible. Describe what you see; don't guess who it is.\n"
                 + "\n".join(f"{k}: {' | '.join(v)}" for k, v in FACE_FIELDS.items())
                 + "\nAlso these, in a few plain words each (looks only, nothing about skin, weight, race or "
                   "religion): distinctive (the one thing you'd notice first), clothing (what they're wearing), "
                   "posture (how they hold themselves)."
                 + '\nExample: {"is_portrait": true, "head_shape": "oval", ..., "distinctive": "...", '
                   '"clothing": "...", "posture": "..."}')
NOTE_FIELDS = ("distinctive", "clothing", "posture")
NEVER_WORDS = re.compile(r"\b(skin|complexion|weight|fat|obese|overweight|chubby|thin|skinny|race|racial|ethnic\w*|"
                         r"religio\w*|disab\w*|wrinkl\w*|old|elderly|ugly)\b", re.I)


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
    said_no = str(raw.get("is_portrait", "true")).lower() in ("false", "no", "0")
    out: dict[str, Any] = {}
    for field, allowed in FACE_FIELDS.items():
        v = str(raw.get(field, "")).strip().lower()
        hit = next((a for a in allowed if a == v), None) or next((a for a in allowed if a in v or v and v in a), None)
        out[field] = hit or "can't tell"
    # a clear face only if the answer really described one: garbled text or half-finished reasoning that
    # matched next to nothing doesn't count (so a backup model gets its turn)
    out["is_portrait"] = not said_no and sum(1 for f in FACE_FIELDS if out[f] != "can't tell") >= 5
    for field in NOTE_FIELDS:   # free notes, kind ones only
        v = re.sub(r"\s+", " ", str(raw.get(field, "") or "")).strip(" .")[:80]
        out[field] = "" if (not v or NEVER_WORDS.search(v) or "can't tell" in v.lower()) else v
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


DESIGN_JSON = {"type": "object", "properties": {
    "key_features": {"type": "array", "minItems": 2, "maxItems": 6, "items": {"type": "string"}},
    "exaggerations": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "object", "properties": {
        "feature": {"type": "string"}, "how": {"type": "string"},
        "percent": {"type": "integer", "minimum": 25, "maximum": 50}},
        "required": ["feature", "how", "percent"]}},
    "design": {"type": "string"}},
    "required": ["key_features", "exaggerations", "design"]}


def _no_name(text: str, name: str) -> str:
    for part in [name] + [w for w in name.split() if len(w) > 2]:
        text = re.sub(rf"\b{re.escape(part)}(?:'s)?\b", "the figure", text, flags=re.I)
    return text


def vision_model() -> str:
    """The model that looks at the photos. A bare Qwen3-VL size tag ("qwen3-vl:8b") is the THINKING version:
    it ignores "think: false" and can spend its whole answer reasoning (Ollama issues #12837, #13353, #14798),
    so the instruct version of the same size is used instead."""
    from .llm import model_for
    m = model_for("vision")
    if re.fullmatch(r"qwen3-vl:\d+b(-thinking)?", m or ""):
        m = re.sub(r"(-thinking)?$", "-instruct", m, count=1)
    return m


def vision_models() -> list[str]:
    """The main vision model, then the backups (Settings → models → vision_backups), skipping ones not installed
    when Ollama can say which are. From the research "Local vision model face reading": Gemma 4 (a different
    maker, so different mistakes), then Qwen2.5-VL 7B; never Llama 3.2 Vision (worst at faces)."""
    from .config import settings
    backups = list((settings().get("models") or {}).get("vision_backups") or [])
    chain = list(dict.fromkeys([vision_model()] + backups))
    try:
        import requests
        with requests.Session() as sess:
            sess.trust_env = False
            r = sess.get(settings()["ollama"]["url"].rstrip("/") + "/api/tags", timeout=4)
            have = {m["name"] for m in r.json().get("models", [])}
    except Exception:  # noqa: BLE001 - can't list them: try each in turn
        have = set()
    if have:
        installed = [m for m in chain if m in have or f"{m}:latest" in have]
        return installed or chain[:1]
    return chain


def research_design(person: dict[str, Any], tradition_key: str | None = None, on_progress=None) -> dict[str, Any]:
    """Dave's five steps (2026-10-28):
    1 research: a normal image search for the person, several photos (only looked at, then deleted);
    2 feature analysis: the local vision model describes each photo (face shape, hair, eyes, nose, mouth, jaw,
      chin, glasses, expression, plus what stands out, clothing and posture); what most photos agree on is kept;
    3 caricature design: the writer AI picks the 1-3 features that make the person recognisable and exaggerates
      them by about 25-50%, kindly (never skin, weight, race, religion, disability or age);
    4 art direction: in the chosen caricature tradition, with the person's usual expression, clothing and pose;
    5 output: the key features, the exaggerations and why, the picture prompt, and 3 alternate styles
      (paint them with Paint previews). Nothing is drawn in a video until you approve the design."""
    import base64
    import shutil

    from .config import data_dir
    from .llm import Ollama, model_for
    from .util import StageError
    say = on_progress or (lambda *_: None)
    name = person["name"]
    say(f"Step 1: searching for photos of {name}")
    refs = find_references(person)
    if not refs:
        raise StageError(f"The image search found no photos of {name} (the search may be offline or busy). Try "
                         "again in a minute, or write the design yourself, using looks only.")
    folder = data_dir() / "caricature-refs" / person["person_id"]
    chain = vision_models()
    from .config import settings
    llm = Ollama({**settings()["ollama"], "num_ctx": 8192, "num_predict": 800, "max_predict": 1600,
                  "max_ctx": 8192, "presence_penalty": 0.0}, job="vision")   # a short answer, not an essay
    answers, records, failed, errors, log, vision = [], [], 0, [], [], chain[0]
    try:
        photos = []                      # download once; every model in the chain looks at the same photos
        for n, ref in enumerate(refs, 1):
            if len(photos) >= MAX_LOOKS * 2:
                break
            say(f"Step 1: getting photo {n} of up to {len(refs)} (from {ref['from']})")
            path = _fetch_small(ref, folder / f"look{n}.jpg")
            if path:
                photos.append((ref, base64.b64encode(path.read_bytes()).decode()))
            else:
                failed += 1
        missing = []
        for vision in chain:             # the main vision model, then the backups you have installed
            answers, records, errors = [], [], []
            for n, (ref, img) in enumerate(photos, 1):
                if sum(1 for a in answers if a.get("is_portrait")) >= MAX_LOOKS:
                    break
                if len(errors) >= 3 and not answers:   # this model isn't answering: try the next one
                    break
                say(f"Step 2: {vision} is looking at photo {n} of {len(photos)}")
                try:   # plain text, no answer format: some vision models get stuck on a forced format
                    text = llm.chat([{"role": "user", "content": VISION_PROMPT, "images": [img]}], model=vision,
                                    temperature=0.1)
                except StageError as exc:
                    if "not found" in str(exc).lower() or "pull" in str(exc).lower():
                        missing.append(vision)
                        errors.append(f"{vision} isn't installed")
                        break
                    errors.append(str(exc))
                    log.append({"model": vision, "photo": ref["page"], "error": str(exc)})
                    continue
                a = parse_vision(text)
                log.append({"model": vision, "photo": ref["page"], "answer": text[:1500], "read_as": a})
                answers.append(a)
                records.append({"page": ref["page"], "from": ref["from"], "title": ref["title"][:120],
                                "clear_face": a["is_portrait"]})
            if any(a.get("is_portrait") for a in answers):
                break
        if missing and not answers:
            raise StageError(f"No vision model is installed ({', '.join(missing)}). In a command window run: "
                             f"ollama pull {chain[0]}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)   # only looked at: nothing is kept
        from .util import write_json
        write_json(data_dir() / "logs" / "vision-log.json", {"person": name, "models": chain, "at": utc_now(),
                                                             "photos": log})
    clear = [a for a in answers if a.get("is_portrait")]
    if not clear:
        if errors and not answers:
            raise StageError(f"The vision model {vision} didn't answer for any photo of {name}: {errors[0]} "
                             "(details in the logs folder, vision-log.json). Check Settings → models → vision.")
        raise StageError(f"Found {len(refs)} photos of {name}; the vision model answered for {len(answers)} and "
                         "said none shows a clear face (its answers are in the logs folder, vision-log.json).")
    face, votes = vote(answers)
    if not face and clear:                    # one photo: its answers are the best we have
        face = {f: clear[0][f] for f in FACE_FIELDS if clear[0].get(f) not in ("", "can't tell")}
    from collections import Counter
    notes = {f: [v for v, _ in Counter(a[f] for a in clear if a.get(f)).most_common(3)] for f in NOTE_FIELDS}
    warnings = [] if len(clear) >= MIN_LOOKS else [
        f"only {len(clear)} clear photo(s): check the design against what you know of {name}"]
    if any("not confirmed" in r["from"] for r in records):
        warnings.append("some photos came from pages that didn't mention who this is; if the design looks like "
                        "someone else, make the 'Who is this' description more specific and research again")

    # 3-4: design with art direction
    say("Step 3: designing the caricature")
    trad = {t["key"]: t for t in traditions()}.get(tradition_key or DEFAULT_TRADITION) or \
        {t["key"]: t for t in traditions()}[DEFAULT_TRADITION]
    fallback, push = compose_design(face)
    result = {"key_features": [f"{v} {k.replace('_', ' ')}" for k, v in face.items() if v not in AVERAGE][:6],
              "exaggerations": [{"feature": f.replace("_", " "), "how": f"pushed ({face[f]})", "percent": 35}
                                for f in push], "design": fallback}
    try:
        ans = Ollama(job="storyboard").chat_json([
            {"role": "system", "content": (
                "You are a professional caricature artist designing an editorial cartoon of a public figure for a "
                "fact-check video. From the agreed features below, pick the 1-3 that make this person instantly "
                "recognisable and exaggerate ONLY those, by about 25-50%; simplify the rest. Keep the likeness, "
                "keep it respectful and kind: exaggerate hair, head shape, brows, glasses, jaw, chin, smile, "
                "expression, posture, clothing and a signature prop, never skin, weight, body size, age, race, "
                "ethnicity, religion or disability. Never write the person's name. Write 'design' as 2-4 sentences "
                "an illustrator can draw from: the head and face (with the exaggerations), the expression, the "
                "clothing and the pose, with a big head on a smaller body.")},
            {"role": "user", "content": json.dumps({
                "public_role": person.get("role_types") or "", "what_they_did": person.get("roles") or "",
                "agreed_features": face, "how_many_photos_agreed": {k: v for k, v in votes.items() if v},
                "noticed_first": notes["distinctive"], "usual_clothing": notes["clothing"],
                "posture": notes["posture"], "caricature_style": trad["name"],
                "style_rules": trad.get("face_body", "")}, ensure_ascii=False)}],
            DESIGN_JSON, lenient=True, temperature=0.5)
        design = _no_name((ans.get("design") or "").strip(), name)
        if design and not NEVER_WORDS.search(design):
            result = {"key_features": [_no_name(k, name) for k in ans.get("key_features") or []][:6],
                      "exaggerations": ans.get("exaggerations") or result["exaggerations"], "design": design}
    except Exception:  # noqa: BLE001 - the plain design from the agreed features is used instead
        warnings.append("the writer AI couldn't write the design, so it was put together from the agreed features")

    # 5: the picture prompt and three alternate styles
    others = [t for t in traditions() if t["tier"] in ("A", "B") and t["key"] != trad["key"]][:3]
    look = lambda t: ", ".join(t["prompt_elements"][:4])  # noqa: E731
    result.update(
        image_prompt=f"{look(trad)}, cartoon caricature. {result['design']}",
        variations=[{"style": t["name"], "key": t["key"], "prompt": f"{look(t)}, cartoon caricature. {result['design']}"}
                    for t in others],
        tradition=trad["name"], tradition_key=trad["key"], face=face, votes=votes, push=push, notes=notes, warnings=warnings,
        unsure=[f.replace("_", " ") for f in FACE_FIELDS if f not in face], references=records, model=vision)
    return result


def paint_previews(ep, person_id: str, result: dict[str, Any]) -> list[dict[str, str]]:
    """Paint the design in the chosen style and the 3 alternates, so you can see it before approving."""
    from . import promptcheck
    from .config import data_dir
    from .stages.storyboard import CARICATURE_GUARD, _comfy_image
    out = []
    jobs = ([{"style": result.get("tradition", ""), "key": result.get("tradition_key", ""),
              "prompt": result["image_prompt"]}] + list(result.get("variations") or []))
    dest = data_dir() / "caricature-previews" / person_id
    dest.mkdir(parents=True, exist_ok=True)
    for n, job in enumerate(jobs):
        prompt, _ = promptcheck.clean_prompt(f"{job['prompt']}. {CARICATURE_GUARD}")
        raw, _, _ = _comfy_image(ep, f"caricature-{person_id}-{n}", prompt)
        path = dest / f"preview{n}.png"
        from PIL import Image
        Image.open(raw).convert("RGB").save(path)
        out.append({"style": job["style"], "key": job.get("key", ""), "path": str(path), "prompt": prompt})
    return out


def save_research(person_id: str, result: dict[str, Any]) -> None:
    db.execute("""INSERT INTO caricature(person_id, design, approved, design_json, references_json)
                  VALUES (?,?,0,?,?) ON CONFLICT(person_id) DO UPDATE SET design_json=excluded.design_json,
                  references_json=excluded.references_json""",
               (person_id, result["design"], json.dumps({k: result.get(k) for k in (
                   "face", "votes", "push", "unsure", "key_features", "exaggerations", "image_prompt", "variations",
                   "notes", "tradition", "tradition_key")}),
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
