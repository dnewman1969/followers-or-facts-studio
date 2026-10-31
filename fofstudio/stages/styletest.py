"""Style test: paint each look the way it shows off best, plus the channel's everyday jobs, so you can see which
looks are worth keeping (Dave, 2026-10-30: "they need to be more of an example of what can be done in that style
and not so literal").

From the research "Style test showcase prompts":
  * five pictures per look:
      showcase 1 and 2  the scene the style is known for, with a channel story beat inside (its own subject,
                        on two fixed seeds); written for the house looks and the best-known ones in
                        data/style_showcase.json, drafted once by the local AI for the rest and saved in
                        <data>/style-showcase.json (edit it in Test styles; reruns use the saved words);
      crowd             the same for every look: townspeople seen from behind watching an invented salesman;
      evidence          the same for every look: blank paper, a red circle, a magnifying glass, one hard lamp
                        (shows whether the look invents fake writing);
      owlbert           the look's empty Owlbert set with the real Owlbert pasted in (he's never painted);
    plus the invented cartoon salesman for caricature looks. Shared pictures use the same seed for every look.
  * prompts in seven parts, about 80-180 words, medium first: medium and traits, one subject doing one thing,
    the setting, one camera phrase, one light phrase, the medium's texture again in other words, then a guard
    that names blank things (never "no text", never quoted words). "16:9" is left out (it does nothing).
  * Keep / Maybe / Drop, and "Start the test over" clears the pictures and every verdict.
Results go to <data>/style-tests/: one folder per look, index.json and a contact sheet.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .. import styles
from ..config import data_dir
from ..util import StageError, read_json, utc_now, write_json
from .base import Context

ROUND = 2       # the 2026-10-30 test design; results from the old two-picture test are round 1
SEEDS = {"showcase": 1129, "showcase2": 48611, "crowd": 2718, "evidence": 31415, "owlbert": 16180, "salesman": 7777}
SHARED = [
    ("crowd", "A crowd of townspeople seen from behind gathers in front of a small wooden stage at a country fair. "
              "On the stage an invented salesman with a huge grin holds a glowing glass bottle high over his head, "
              "mid-gesture, his other arm flung wide. Wide shot from the back of the crowd, the stage off-centre to "
              "the right, strings of plain solid-colour bunting overhead, late-afternoon sun from the left throwing "
              "long shadows across the grass"),
    ("evidence", "Close-up of a single sheet of plain blank paper on a worn wooden desk, a red pencil circle drawn on "
                 "its empty surface, a brass magnifying glass tilted over the circle so its lens bends the paper "
                 "grain, a torn scrap of blank newsprint beside it. One cold desk lamp from the upper right makes a "
                 "hard pool of light, and the rest of the room falls away into shadow"),
]
CARICATURE_SUBJECT = ("salesman", "An invented cartoon salesman with a huge grin and slicked hair holds up a giant "
                                  "bottle of tonic, leaning toward the viewer, one eyebrow raised")
OWL_SET = ("an empty quiet set with only furniture and props, open floor space on the left side, soft light, "
           "nobody in it")
GUARD = "plain unmarked surfaces, bare walls, unlabelled objects, figures seen from behind or far away"
# the medium's texture, said again at the end in other words (plastic-looking results lack texture words)
MEDIUM_TEXTURE = {
    "cut_paper": "layered paper edges with soft drop shadows, visible paper fibres and torn deckled edges",
    "paint": "visible brushstrokes, pigment pooling and soft paper or canvas texture",
    "cel": "flat cel colours, clean ink outlines, two-tone shadows over a softly painted background",
    "film": "natural film grain, soft halation around the lights, slightly faded colour",
    "puppet": "hand-made puppet materials, carved and stitched details, small practical lights, macro lens with "
              "shallow focus",
    "poster": "flat opaque colour in a few inks, crisp shape edges, slight misregistration and paper tooth",
    "print": "carved or etched lines that follow each form, uneven ink pressure, paper grain showing through",
    "drawing": "pencil and chalk marks, smudged shading, unfinished edges on toothy paper",
    "ink": "bold brush-ink lines with varied weight, halftone dots and flat printed colour",
    "miniature": "tiny hand-built set pieces, miniature props, small practical lights, macro lens with shallow focus",
    "collage": "cut and torn found-paper pieces, overlapping layers, glue edges and mixed paper textures",
    "graphic": "clean geometric shapes, flat colour fields and precise thin lines",
    "felt": "fuzzy felt fibres, visible stitches and soft fabric folds, macro lens with shallow focus",
    "stage": "painted flat scenery in layers, warm footlights, a proscenium frame and theatrical shadows",
    "object": "real hand-made objects with tool marks, arranged on a tabletop, soft practical light",
    "sand": "granular sand with tones made by its thickness, glowing light showing through the thin places",
    "glass": "paint smeared on glass with finger marks, light glowing through the colour",
    "latex": "soft latex puppet skin, sculpted exaggerated features, studio lights, macro lens",
    "clay": "visible fingerprints and tool marks in the clay, slightly lumpy hand-sculpted shapes, felt and "
            "cardboard props",
}
SHOWCASE_SCHEMA = {"type": "object", "properties": {"subject": {"type": "string"}}, "required": ["subject"]}
TEXTY = re.compile(r"\b(?:sign|signs|label|labels|logo|logos|headline|headlines|slogan|slogans|banner|banners|"
                   r"caption|captions|lettering|words?|text|title|poster text|screen text|monitors?)\b", re.I)
THUMB = (448, 252)


def folder() -> Path:
    return data_dir() / "style-tests"


def results() -> dict[str, Any]:
    return read_json(folder() / "index.json", {}) or {}


def showcase_file() -> Path:
    return data_dir() / "style-showcase.json"


def _builtin() -> dict[str, str]:
    path = Path(__file__).resolve().parent.parent / "data" / "style_showcase.json"
    return json.loads(path.read_text(encoding="utf-8"))["subjects"]


def showcase(key: str) -> str:
    """The style's own signature subject: yours (edited in Test styles), then the written one, else ""."""
    saved = (read_json(showcase_file(), {}) or {}).get(key)
    return saved or _builtin().get(key, "")


def save_showcase(key: str, text: str) -> None:
    data = read_json(showcase_file(), {}) or {}
    if text.strip():
        data[key] = " ".join(text.split())
    else:
        data.pop(key, None)
    write_json(showcase_file(), data)


def _fallback(style: styles.Style) -> str:
    raw = _raw(style.key)
    uses = (raw.get("best_uses") or style.blurb or "").split(",")[0].strip(' "')
    bits = [f"a scene about {uses}" if uses else "a small town where a rumour is spreading",
            raw.get("background_style") or ""]
    return ", ".join(b for b in bits if b)


def draft_showcase(style: styles.Style) -> str:
    """Have the local AI write this style's signature subject once (temperature 0) and save it, so every rerun
    paints the same words. If the AI isn't there, a plain one is made from the style's own notes."""
    raw = _raw(style.key)
    try:
        from ..llm import Ollama
        ans = Ollama(job="storyboard").chat_json([
            {"role": "system", "content": (
                "You are an art director writing the ONE showcase picture for a visual style, for a fact-check "
                "video channel. Write the scene this style is famous for (its classic composition, light and "
                "subject), with a channel story beat inside it: a rumour spreading, a plain envelope changing hands, "
                "a crowd seen from behind, a miracle product, a salesman, a radio, coins. One subject doing one "
                "thing, mid-action, then the setting, one camera phrase and one light phrase. 35-60 words, plain "
                "visible facts, no mood words. Never name artists, studios, brands, shows or real people. Never "
                "ask for signs, labels, headlines, banners, screens with writing or any words; never use quotation "
                "marks. Don't name the style itself.")},
            {"role": "user", "content": json.dumps({
                "style": style.name, "look": style.look, "what_it_looks_like": raw.get("visual_dna", ""),
                "background": raw.get("background_style", ""), "light": raw.get("lighting_style", ""),
                "camera": raw.get("camera_style", ""), "best_uses": raw.get("best_uses", "")}, ensure_ascii=False)}],
            SHOWCASE_SCHEMA, lenient=True, temperature=0)
        text = " ".join(str(ans.get("subject") or "").replace('"', "").split())
    except Exception:  # noqa: BLE001 - the plain one below is used, and saved so you can edit it
        text = ""
    from .. import promptcheck
    text, _ = promptcheck.strip_watch(text)
    if len(text.split()) < 8 or TEXTY.search(text):
        text = _fallback(style)
    save_showcase(style.key, text)
    return text


def _raw(key: str) -> dict[str, Any]:
    data = json.loads((Path(__file__).resolve().parent.parent / "data" / "styles.json").read_text(encoding="utf-8"))
    return next((s for s in data["styles"] if s["key"] == key), {})


def _first(text: str) -> str:
    """The first clause of a style note, without the research's '(inference ...)' remarks."""
    t = re.sub(r"\([^)]*\)", "", text or "").split(";")[0].strip(" ,.")
    if re.match(r"(?:varies|n/a|none|no |not |never |without )", t.lower()):
        return ""          # a "no ..." phrase hands the painter the very thing it should leave out
    return t


def look_words(style: styles.Style) -> str:
    return re.sub(r",?\s*16:9\b", "", style.look).strip(" ,.")


# what the look line says it's made of beats the 'medium' field (some house looks are filed under the wrong one)
MEDIUM_WORDS = [
    ("clay", r"clay|plasticine"), ("felt", r"\bfelt\b"), ("sand", r"\bsand\b"), ("glass", r"on glass|stained glass"),
    ("latex", r"latex"), ("puppet", r"puppet|marionette"), ("miniature", r"miniature|diorama|tabletop"),
    ("print", r"woodcut|relief print|linocut|etching|engraving|woodblock|block print"),
    ("poster", r"poster|screen ?print|silkscreen|risograph"), ("cut_paper", r"paper cut|cut-out|cut paper|layered paper"),
    ("collage", r"collage"), ("film", r"film|archival|photograph|television|\btv\b|videotape|kinescope|35mm"),
    ("drawing", r"pencil|charcoal|pastel|chalk|sketch"), ("ink", r"\bink\b|comic|halftone"),
    ("paint", r"watercolou?r|gouache|\boil\b|painted|painting|acrylic"), ("cel", r"cel\b|cartoon|vector|anime"),
]


def texture(style: styles.Style) -> str:
    look = style.look.lower()
    for medium, words in MEDIUM_WORDS:
        if re.search(words, look):
            if medium == "film" and "black and white" in look:
                return "natural film grain, deep inky blacks and silvery highlights"
            return MEDIUM_TEXTURE[medium]
    if style.medium == "cut_paper":       # filed as paper but the look doesn't say so: its own clean words
        return style.clean
    return MEDIUM_TEXTURE.get(style.medium or "", "") or style.clean


def prompt_for(style: styles.Style, subject: str, kind: str = "showcase") -> str:
    """Seven parts, medium first: look, subject (with its own setting, camera and light), the style's light,
    texture, guard."""
    from .. import promptcheck
    raw = _raw(style.key) if not style.key.startswith("mix:") else {}
    parts = [look_words(style), subject]
    if kind == "showcase":   # the style's own light (its camera notes are about motion, not framing)
        parts += [_first(raw.get("lighting_style", ""))]
    if kind == "owlbert":
        parts += [OWL_SET]
    parts += [texture(style), GUARD]
    text = ". ".join(p.strip(" .") for p in parts if p and p.strip(" ."))
    return promptcheck.strip_watch(text.replace('"', ""))[0]


def jobs_for(style: styles.Style) -> list[tuple[str, str, str]]:
    """(tag, kind, subject) for every test picture of this look."""
    sig = showcase(style.key) or draft_showcase(style)
    owl = re.sub(r"\b(?:professor\s+)?owlbert(?:'s)?\b|\bowls?\b", "", style.owl_look or "", flags=re.I)
    out = [("showcase", "showcase", sig), ("showcase2", "showcase", sig)]
    out += [(tag, "shared", text) for tag, text in SHARED]
    out += [("owlbert", "owlbert", " ".join(owl.split()).strip(" ,.") or "a cosy study with a desk and a lamp")]
    if style.caricature:
        out.append((CARICATURE_SUBJECT[0], "shared", CARICATURE_SUBJECT[1]))
    return out


def reset() -> int:
    """Start the test over: every test picture and every Keep / Maybe / Drop is cleared (your edited showcase
    subjects are kept). Returns how many verdicts were cleared."""
    import shutil
    n = len(styles.ratings())
    if folder().exists():
        shutil.rmtree(folder(), ignore_errors=True)
    styles.ratings_path().unlink(missing_ok=True)
    return n


def run(ctx: Context) -> None:
    from .storyboard import _comfy_image, _place_owlbert
    keys = list(ctx.options.get("styles") or [])
    if not keys:
        raise StageError("Pick at least one look to test.")
    index = results()
    total = len(keys)
    for n, key in enumerate(keys):
        ctx.check_cancel()
        style = styles.get(key)
        ctx.progress(f"Testing {style.name} ({n + 1} of {total}): its showcase subject", 100 * n / total)
        jobs = jobs_for(style)
        pics = []
        for j, (tag, kind, subject) in enumerate(jobs):
            ctx.check_cancel()
            ctx.progress(f"Testing {style.name} ({n + 1} of {total}): {tag}", 100 * (n + j / len(jobs)) / total)
            prompt = prompt_for(style, subject, kind if kind != "shared" else "shared")
            raw, _, seed = _comfy_image(ctx.episode, f"styletest-{key.replace(':', '_')}-{tag}", prompt,
                                        seed=SEEDS[tag])
            dest = folder() / key.replace(":", "_").replace("+", "_") / f"{tag}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if kind == "owlbert":
                _place_owlbert(raw, dest, side=0)       # the real Owlbert on the painted set, as in a video
            else:
                Image.open(raw).convert("RGB").save(dest)
            pics.append({"tag": tag, "path": str(dest), "seed": seed, "prompt": prompt})
        index[key] = {"name": style.name, "pictures": pics, "tested_at": utc_now(), "round": ROUND,
                      "showcase": showcase(key)}
        write_json(folder() / "index.json", index)
    sheet = contact_sheet(keys, index)
    ctx.progress(f"Tested {total} look(s). Contact sheet: {sheet.name}. Press Keep, Maybe or Drop on each.", 100)


def contact_sheet(keys: list[str], index: dict[str, Any]) -> Path:
    """One picture with every tested look, named, so you can compare them side by side."""
    rows = [k for k in keys if k in index]
    cols = max((len(index[k]["pictures"]) for k in rows), default=2)
    label_h = 28
    sheet = Image.new("RGB", (cols * THUMB[0], max(1, len(rows)) * (THUMB[1] + label_h)), (20, 22, 30))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for r, key in enumerate(rows):
        y = r * (THUMB[1] + label_h)
        draw.text((8, y + 4), index[key]["name"], fill=(240, 200, 90), font=font)
        for c, pic in enumerate(index[key]["pictures"]):
            try:
                im = Image.open(pic["path"]).convert("RGB")
                im.thumbnail(THUMB)
                sheet.paste(im, (c * THUMB[0], y + label_h))
            except OSError:
                continue
    out = folder() / f"contact-sheet-{utc_now()[:10]}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
