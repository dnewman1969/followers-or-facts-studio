"""Stage 8 (optional) - Music.

The script's MUSIC lines give each scene a mood, an energy and how the music changes (continue,
crossfade, sting, hard_cut, silence). Scenes that "continue" share one piece of music ("cue"); every
change starts a new one. Each cue is made with ACE-Step in ComfyUI (Apache-2.0/MIT, the music is ours)
in the video's genre - picked on the Production page or taken from the style - at one tempo and in
related keys, so the cross-fades sound like one score. The channel theme for the outro is made once and
reused in every video.

Or use a music library track: put it in <data>/music-library/ with a .txt (or .license.json) note
saying where it came from and its licence. Non-commercial or no-derivatives licences are refused.
"""

from __future__ import annotations

import json
import shutil
from typing import Any

from .. import musicbook, styles
from ..comfy import new_seed, run_template
from ..config import Paths, settings
from ..episode import Episode
from ..scriptfmt import parse
from ..util import StageError, read_json, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context

LONGEST_CUE = 180          # seconds made in one go; longer runs of scenes loop their cue
SCENE_PAD = 1.6            # breathing room around each scene's narration on the timeline
THEME_SEED = 1969          # the channel theme is the same every time


def plan_cues(scenes: list[dict[str, Any]], seconds: dict[str, float], careful: bool = False) -> list[dict[str, Any]]:
    """Group scenes into music cues from their MUSIC lines. A scene without one gets its role's mood."""
    from .script import tidy_directions
    cues: list[dict[str, Any]] = []
    before: list[dict[str, Any]] = []
    for sc in scenes:
        sc = dict(sc)
        if not sc.get("music"):
            tidy_directions(sc, {"careful": careful}, before)
        m = sc["music"]
        before.append(sc)
        length = seconds.get(sc["scene_id"], 20.0) + SCENE_PAD
        change = m.get("change", "crossfade")
        same = cues and change == "continue" and cues[-1]["mood"] == m["mood"] and not cues[-1]["silence"]
        if same:
            cues[-1]["scenes"].append(sc["scene_id"])
            cues[-1]["seconds"] += length
            cues[-1]["energy"] = max(cues[-1]["energy"], m["energy"])
        else:
            cues.append({"cue_id": f"M{len(cues) + 1:02d}", "scenes": [sc["scene_id"]], "mood": m["mood"],
                         "energy": m["energy"], "change": change if cues else "crossfade",
                         "silence": change == "silence", "seconds": length})
        cue = cues[-1]
        for key in ("drop_before", "sting_at"):
            if m.get(key):
                cue.setdefault("marks", []).append({"scene_id": sc["scene_id"], key: m[key]})
    for c in cues:
        c["seconds"] = round(c["seconds"] + 4.0, 1)     # spare music past the cut, for the cross-fade
    return cues


def _scene_seconds(ep: Episode) -> dict[str, float]:
    narration = read_json(ep.path("audio", "narration.json"), {}) or {}
    return {k: float(v.get("seconds", 20.0)) for k, v in narration.items()}


def _licence_note(src) -> str:
    for note in (src.with_suffix(".license.json"), src.with_suffix(".txt")):
        if note.exists():
            text = note.read_text(encoding="utf-8", errors="replace")
            low = text.lower()
            bad = [w for w in musicbook.BLOCKED_LICENCE_WORDS if w in low]
            if bad:
                raise StageError(f"{src.name}: its licence note says '{bad[0]}', which isn't allowed on a monetized "
                                 "channel. Pick another track.")
            return text[:800]
    raise StageError(f"Add {src.stem}.txt next to {src.name} saying where it came from and its licence, so the "
                     "episode has a record.")


AUDIO = (".wav", ".mp3", ".flac", ".ogg", ".m4a")


def library_tracks() -> list[dict[str, Any]]:
    """Every track in the music library that has a licence note (and isn't non-commercial)."""
    out = []
    lib = Paths().music_library
    for f in sorted(lib.rglob("*")) if lib.exists() else []:
        if f.suffix.lower() not in AUDIO:
            continue
        try:
            note = _licence_note(f)
        except StageError:
            continue
        out.append({"path": f, "note": note, "words": f"{f.stem} {f.parent.name} {note}".lower()})
    return out


def _pick_from_library(tracks: list[dict[str, Any]], cue: dict[str, Any], used: set) -> dict[str, Any] | None:
    """The library track whose name, folder or note mentions this cue's mood (one not used yet if possible)."""
    if not tracks:
        return None
    scored = sorted(tracks, key=lambda t: (cue["mood"] not in t["words"], str(t["path"]) in used))
    return scored[0]


def _make(ctx: Context, tags: str, seconds: int, seed: int, out_stem, label: str):
    ctx.progress(label)
    saved, wf = run_template("music_workflow", {
        "TAGS": tags, "LYRICS": "[instrumental]", "SECONDS": seconds, "SEED": seed,
        "FILENAME_PREFIX": f"fof/{ctx.episode.project_id}/music",
    }, out_stem, on_progress=ctx.progress, cancelled=ctx.cancelled)
    return saved[0], wf


def theme(ctx: Context, genre: musicbook.Genre):
    """The channel theme: made once per genre and kept in the data folder for every video."""
    folder = Paths().root / "music-theme"
    folder.mkdir(parents=True, exist_ok=True)
    found = sorted(folder.glob(f"theme-{genre.key}*"))
    if found and found[0].suffix != ".json":
        return found[0]
    tags = musicbook.cue_tags(genre, "theme", 4)
    path, _ = _make(ctx, tags, 40, THEME_SEED, folder / f"theme-{genre.key}", "Making the channel theme (once)")
    write_json(folder / f"theme-{genre.key}.json", {"tags": tags, "seed": THEME_SEED, "made_at": utc_now()})
    return path


def run(ctx: Context) -> None:
    ep = ctx.episode
    out_dir = ep.path("audio", "music")
    out_dir.mkdir(parents=True, exist_ok=True)
    choice = ctx.options.get("library_file")
    if choice:
        src = Paths().music_library / choice
        if not src.exists():
            raise StageError(f"{src} doesn't exist.")
        note = _licence_note(src)
        dest = out_dir / f"bed{src.suffix}"
        shutil.copy2(src, dest)
        write_json(out_dir / "music.json", {"path": ep.rel(dest), "model": "music library", "source": src.name,
                                            "licence_note": note, "made_at": utc_now(), "cues": []})
        return
    if not ep.path("script.md").exists():
        raise StageError("Approve the Script first: the music follows its scenes.")
    script = parse(ep.path("script.md").read_text(encoding="utf-8"))
    creative = ep.creative()
    style = styles.get(creative["style"])
    if "genre" in ctx.options:                     # chosen on the Production page ("" = to suit the style)
        genre_key = ctx.options["genre"] or ""
        ep.set_creative(music_genre=genre_key)
    else:
        genre_key = creative.get("music_genre") or ""
    genre = musicbook.genre_for(style.key, genre_key if genre_key != "library" else "")
    if not genre_key:   # "to suit the style": the film genre chosen for the script leads, if there is one
        from .. import filmstyles
        film, _ = filmstyles.chosen(creative)
        if film and film.music_tags:
            tags = ", ".join(t for t in (x.strip() for x in film.music_tags.split(","))
                             if t and "bpm" not in t.lower() and t.lower() != "instrumental")
            genre = musicbook.Genre(f"film-{film.key}", f"{film.name} score", tags, film.bpm)
    cues = plan_cues(script["scenes"], _scene_seconds(ep), bool(creative.get("careful")))
    if genre_key == "library":
        tracks = library_tracks()
        if not tracks:
            raise StageError(f"No usable tracks in {Paths().music_library}. Put music there with a .txt note of "
                             "where it came from and its licence (name the mood in the file or folder name, e.g. "
                             "'tense', 'playful', 'somber', to match scenes). See docs/MUSIC.md.")
        used: set[str] = set()
        for cue in cues:
            if cue["silence"]:
                continue
            t = _pick_from_library(tracks, cue, used)
            used.add(str(t["path"]))
            dest = out_dir / f"{cue['cue_id']}-{t['path'].name}"
            shutil.copy2(t["path"], dest)
            cue["path"], cue["source"], cue["licence_note"] = ep.rel(dest), t["path"].name, t["note"][:300]
        write_json(out_dir / "music.json", {"path": next((c["path"] for c in cues if c.get("path")), ""),
                                            "model": "music library", "genre": "library",
                                            "genre_name": "your music library", "cues": cues, "made_at": utc_now()})
        ctx.progress(f"{len(cues)} music cues picked from your library by mood.", 100)
        return
    old = {(c.get("tags"), c.get("seconds_made")): c for c in (read_json(out_dir / "music.json") or {}).get("cues", [])}
    base_seed = new_seed()
    made = 0
    for k, cue in enumerate(cues):
        ctx.check_cancel()
        if cue["silence"]:
            continue
        if cue["mood"] == "theme":
            cue["path"] = str(theme(ctx, genre))
            cue["tags"] = musicbook.cue_tags(genre, "theme", 4)
            continue
        cue["tags"] = musicbook.cue_tags(genre, cue["mood"], cue["energy"])
        cue["seconds_made"] = int(min(LONGEST_CUE, max(20, round(cue["seconds"]))))
        prev = old.get((cue["tags"], cue["seconds_made"]))
        if prev and ep.abs(prev["path"]).exists():   # unchanged: keep it
            cue["path"], cue["seed"] = prev["path"], prev.get("seed")
            continue
        cue["seed"] = base_seed + k
        path, _ = _make(ctx, cue["tags"], cue["seconds_made"], cue["seed"], out_dir / f"{cue['cue_id']}-{cue['seed']}",
                        f"Making music cue {k + 1} of {len(cues)}: {cue['mood']} ({genre.name}), "
                        f"{cue['seconds_made']} s")
        cue["path"] = ep.rel(path)
        made += 1
    for cue in cues:
        if cue.get("path") and not str(cue["path"]).startswith("audio"):
            try:
                cue["path"] = ep.rel(cue["path"])
            except ValueError:
                pass                          # the shared channel theme lives outside the episode
    first = next((c for c in cues if c.get("path")), None)
    write_json(out_dir / "music.json", {
        "path": first["path"] if first else "", "model": settings()["comfyui"]["music_model_name"],
        "genre": genre.key, "genre_name": genre.name, "cues": cues, "made_at": utc_now(),
        "licence": "ACE-Step (Apache-2.0/MIT): the music is ours"})
    ctx.progress(f"{len(cues)} music cues ({made} new) in the {genre.name} style. Listen on the Production page.", 100)


def check(ep: Episode) -> list[Check]:
    meta = read_json(ep.path("audio", "music", "music.json"))
    if not meta:
        return [Check(BLOCK, "No music yet. Run this stage, or Skip it for a voice-only video.")]
    paths = [c["path"] for c in meta.get("cues", []) if c.get("path")] or ([meta["path"]] if meta.get("path") else [])
    missing = [p for p in paths if not ep.abs(p).exists()]
    if missing:
        return [Check(BLOCK, f"{len(missing)} music file(s) are missing. Run Make music again.")]
    if meta.get("cues"):
        moods = " → ".join(c["mood"] if not c["silence"] else "silence" for c in meta["cues"])
        out = [Check(OK, f"{len(meta['cues'])} music cues ({meta.get('genre_name', '')}): {moods}. Listen before "
                         "approving.")]
    else:
        out = [Check(OK, f"Music bed: {meta['model']}. Listen before approving.")]
    if meta.get("model") == "music library":
        out.append(Check(WARN, "Library track: make sure the licence allows monetized YouTube use."))
    return out


def describe(meta: dict[str, Any]) -> str:
    return json.dumps({k: meta.get(k) for k in ("genre", "cues")}, ensure_ascii=False)[:2000]
