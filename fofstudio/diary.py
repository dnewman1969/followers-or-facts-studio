"""The production diary (Dave, 2026-11-02: "write up a step by step ... so I can send you the log file or files
so you can see what's going on while the video is being created from research to upload. This way we can see
where we're losing story cohesion").

After every step the Studio writes what went in, what came out and whether the story is still the one that was
chosen, in plain words, to <episode>/diary/diary.md (and diary.jsonl for programs). Every entry carries the
STORY THREAD check: the chosen story's own words (its logline, angle and beats) against each scene and each
picture, so a step where the story gets lost shows up as a drop.

bundle(ep) packs the diary with the small text files that explain a run (script, story, bible, storyboard plan,
crew log, reviews, logs - never pictures, clips or audio) into one zip to send to Claude.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

from .episode import Episode
from .util import read_json, utc_now

_STOP = set("""a an the and or but so of to in on at by for with from as is are was were be been it its this that these
those he she they them his her their we you i our your not no yes do did does done can could would should will
just also than then there here what who when where why how all any some more most very into over about after
before up down out off only own same such too s t""".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z'-]{2,}", (text or "").lower()) if w not in _STOP}


def thread_words(ep: Episode) -> set[str]:
    """The chosen story's own words: what the video is supposed to be about."""
    from .stages.stories import chosen
    st = chosen(ep) or {}
    text = " ".join(str(st.get(k, "")) for k in ("title", "logline", "angle", "opening_hook"))
    text += " " + " ".join(json.dumps(b, ensure_ascii=False) for b in st.get("beats") or [])
    return _words(text)


def thread_score(thread: set[str], text: str) -> int:
    """How much of a piece carries the story's words (0-100; 0 means it has drifted off the story)."""
    w = _words(text)
    if not thread or not w:
        return 0
    return min(100, round(100 * len(thread & w) / max(4, min(len(w), 25))))


def _section(ep: Episode, stage: str) -> dict[str, Any]:
    """What this step produced, summarized for a person."""
    out: dict[str, Any] = {}
    thread = thread_words(ep)
    if stage == "research":
        r = read_json(ep.path("research.json")) or {}
        claims = r.get("claims") or []
        out["claims"] = [f"{c.get('claim_id')}: {c.get('short_title', '')[:90]} ({c.get('falsity_status', '')})"
                         for c in claims[:12]]
        out["sources"] = sum(len(c.get("sources") or []) for c in claims)
        out["quotes"] = sum(len(c.get("excerpts") or []) for c in claims)
    elif stage == "stories":
        from .stages.stories import chosen
        st = chosen(ep) or {}
        out["chosen"] = {k: st.get(k) for k in ("title", "logline", "angle", "opening_hook")}
        out["beats"] = [b if isinstance(b, str) else (b.get("beat") or b.get("what") or json.dumps(b))[:140]
                        for b in (st.get("beats") or [])[:12]]
    elif stage == "script":
        from . import repeats
        from .speakable import unspeakable
        try:
            from .stages.script import load
            scenes = load(ep)["scenes"]
        except Exception:  # noqa: BLE001 - no script yet
            scenes = []
        rows = []
        for sc in scenes:
            nar = sc.get("narration", "")
            sents = repeats.sentences(nar)
            rows.append({"scene": sc["scene_id"], "role": sc.get("role", ""), "words": len(nar.split()),
                         "story_thread": thread_score(thread, nar), "opens": (sents[0] if sents else "")[:140],
                         "says_aloud_a_reference": unspeakable(nar)[:3]})
        out["scenes"] = rows
        texts = {sc["scene_id"]: sc.get("narration", "") for sc in scenes}
        out["phrases_used_3_or_more_times"] = [f"'{p}' in {', '.join(w)}" for p, w in
                                               repeats.overused_phrases(texts)[:10]]
        same = []
        for i, a in enumerate(scenes):
            for b in scenes[i + 1:]:
                sim = repeats.similarity(a.get("narration", ""), b.get("narration", ""))
                if sim >= 0.35:
                    same.append(f"{a['scene_id']} ~ {b['scene_id']} ({round(100 * sim)}% alike)")
        out["scenes_that_say_the_same_thing"] = same[:10]
    elif stage == "storyboard":
        board = ep.storyboard() or {}
        rows = []
        for s in board.get("scenes", []):
            for sh in s.get("shots", []):
                pic = sh.get("camera_sees") or sh.get("idea", "")
                rows.append({"shot": sh["shot_id"], "kind": sh.get("kind"), "shows": sh.get("shows", ""),
                             "covers": (sh.get("covers") or "")[:100], "painted": pic[:160],
                             "story_thread": thread_score(thread, pic + " " + (sh.get("covers") or "")),
                             "review": (sh.get("vision") or {}).get("problems", [])})
        out["shots"] = rows
        qr = read_json(ep.path("quality-review.json")) or {}
        out["quality_review"] = {k: v.get("why", "")[:200] for k, v in (qr.get("answers") or {}).items()
                                 if not v.get("ok")}
    elif stage in ("video_plan", "video"):
        plan = read_json(ep.path("video", "plan.json")) or {}
        shots = plan.get("shots") or []
        out["shots"] = [{"shot": s.get("shot_id"), "how": s.get("method") or s.get("mode") or s.get("motion", ""),
                         "motion": (s.get("motion_prompt") or s.get("prompt") or "")[:140],
                         "clip_check": (s.get("check") or {}).get("why", "")} for s in shots[:80]]
    elif stage == "production":
        prod = read_json(ep.path("production.json")) or {}
        out["seconds"] = prod.get("seconds") or prod.get("duration")
        out["timeline_items"] = len(prod.get("timeline") or prod.get("clips") or [])
    elif stage in ("package", "upload"):
        pub = read_json(ep.path("publish", "package.json")) or read_json(ep.path("publish", "metadata.json")) or {}
        out["title"] = pub.get("title")
        out["description_start"] = (pub.get("description") or "")[:300]
    return out


def _md(stage: str, status: str, section: dict[str, Any], checks: list[str], log_tail: list[str],
        error: str) -> str:
    lines = [f"## {utc_now()} · {stage} · {status}", ""]
    if error:
        lines += [f"**Stopped:** {error}", ""]
    for k, v in section.items():
        label = k.replace("_", " ")
        if isinstance(v, list):
            if not v:
                continue
            lines.append(f"**{label}:**")
            for item in v:
                if isinstance(item, dict):
                    lines.append("- " + " · ".join(f"{a}: {b}" for a, b in item.items() if b not in ("", [], None)))
                else:
                    lines.append(f"- {item}")
        elif isinstance(v, dict):
            if v:
                lines.append(f"**{label}:** " + " · ".join(f"{a}: {b}" for a, b in v.items() if b))
        elif v not in ("", None):
            lines.append(f"**{label}:** {v}")
    if checks:
        lines += ["", "**Checks:**"] + [f"- {c}" for c in checks[:30]]
    if log_tail:
        lines += ["", "**What it said while working (last lines):**"] + [f"- {x[:220]}" for x in log_tail[-25:]]
    return "\n".join(lines) + "\n\n"


def write(ep: Episode, stage: str, status: str, checks: list[str] | None = None, log_lines: list[str] | None = None,
          error: str = "") -> None:
    """One diary entry for a step. Never stops the Studio: a diary problem is only written down."""
    try:
        section = _section(ep, stage)
    except Exception as exc:  # noqa: BLE001 - the diary must never break a run
        section = {"diary_problem": f"{type(exc).__name__}: {exc}"}
    d = ep.path("diary")
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "diary.md", "a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write(f"# Production diary: {ep.project_id} {ep.title}\n\nEach step writes what it made and whether "
                    "the story is still the chosen one (story_thread: 0 = drifted off the story).\n\n")
        f.write(_md(stage, status, section, checks or [], log_lines or [], error))
    with open(d / "diary.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": utc_now(), "stage": stage, "status": status, "error": error,
                            "checks": checks or [], "section": section, "log": (log_lines or [])[-60:]},
                           ensure_ascii=False) + "\n")


def note(ep: Episode, text: str) -> None:
    """A one-line diary entry (approvals, hand edits)."""
    try:
        d = ep.path("diary")
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "diary.md", "a", encoding="utf-8") as f:
            f.write(f"- {utc_now()} · {text}\n\n")
        with open(d / "diary.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": utc_now(), "note": text}, ensure_ascii=False) + "\n")
    except OSError:
        pass


SMALL_FILES = ["script.md", "stories.json", "bible.json", "storyboard.json", "crew.json", "director-review.md",
               "quality-review.json", "claim-check.json", "video/plan.json", "production.json",
               "audio/narration.json", "publish/package.json", "publish/metadata.json", "creative.json",
               "status.json", "history.json"]


def bundle(ep: Episode) -> Path:
    """Everything that explains this video's run, in one small zip for Claude (no pictures, clips or audio)."""
    from .config import data_dir
    out_dir = data_dir() / "send-to-claude"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("-", "")[:15]
    path = out_dir / f"{ep.project_id}-{stamp}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ["diary/diary.md", "diary/diary.jsonl", *SMALL_FILES]:
            p = ep.path(*name.split("/"))
            if p.is_file() and p.stat().st_size < 20_000_000:
                z.write(p, f"episode/{name}")
        research = ep.path("research.json")
        if research.is_file():
            z.write(research, "episode/research.json")
        logs = data_dir() / "logs"
        if logs.is_dir():
            for p in sorted(logs.glob("*.log"), key=lambda x: x.stat().st_mtime)[-8:]:
                z.write(p, f"logs/{p.name}")
        for p in (data_dir() / "unreal" / "out" / "run-log.txt", data_dir() / "unreal" / "unreal-editor.log",
                  data_dir() / "unreal" / "last-import.json"):
            if p.is_file():
                z.write(p, f"unreal/{p.name}")
        z.writestr("README.txt", f"Followers or Facts Studio run for {ep.project_id} ({ep.title}), packed "
                                 f"{utc_now()}. Start with episode/diary/diary.md.\n")
    return path
