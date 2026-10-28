"""Style test: paint the same two test pictures in every look you pick, so you can see which are worth keeping.

From the research "Art styles caricatures and hybrids": every look is an estimate until it's painted on your
own PC with your own image model. The test pictures are fixed (a street at dusk with people seen from behind,
and a desk with documents), so looks are compared fairly; caricature looks also get an invented cartoon
salesman (never a real person). Results go to <data>/style-tests/: one folder per look and a contact sheet.
You press Keep or Drop on Storyboard → Test styles; dropped looks leave the pickers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .. import styles
from ..config import data_dir
from ..util import StageError, read_json, utc_now, write_json
from .base import Context

SUBJECTS = [
    ("street", "a small-town main street at dusk, a radio shop window glowing, a few people seen from behind"),
    ("desk", "a wooden desk with a stack of documents, a jar of coins and a magnifying glass"),
]
CARICATURE_SUBJECT = ("salesman", "an invented cartoon salesman with a huge grin holding up a giant bottle of tonic")
THUMB = (448, 256)


def folder() -> Path:
    return data_dir() / "style-tests"


def results() -> dict[str, Any]:
    return read_json(folder() / "index.json", {}) or {}


def prompt_for(style: styles.Style, idea: str) -> str:
    from .. import promptcheck
    from .storyboard import GUARD
    parts = [style.look, idea, style.clean, GUARD]
    return promptcheck.strip_watch(". ".join(x.strip(" .") for x in parts if x))[0]


def run(ctx: Context) -> None:
    from .storyboard import _comfy_image
    keys = list(ctx.options.get("styles") or [])
    if not keys:
        raise StageError("Pick at least one look to test.")
    index = results()
    total = len(keys)
    for n, key in enumerate(keys):
        ctx.check_cancel()
        style = styles.get(key)
        subjects = SUBJECTS + ([CARICATURE_SUBJECT] if style.caricature else [])
        pics = []
        for j, (tag, idea) in enumerate(subjects):
            ctx.progress(f"Testing {style.name} ({n + 1} of {total}): {tag}",
                         100 * (n + j / len(subjects)) / total)
            raw, _, seed = _comfy_image(ctx.episode, f"styletest-{key.replace(':', '_')}-{tag}", prompt_for(style, idea))
            dest = folder() / key.replace(":", "_").replace("+", "_") / f"{tag}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            Image.open(raw).convert("RGB").save(dest)
            pics.append({"tag": tag, "path": str(dest), "seed": seed, "prompt": prompt_for(style, idea)})
        index[key] = {"name": style.name, "pictures": pics, "tested_at": utc_now()}
        write_json(folder() / "index.json", index)
    sheet = contact_sheet(keys, index)
    ctx.progress(f"Tested {total} look(s). Contact sheet: {sheet.name}. Press Keep or Drop on each.", 100)


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
