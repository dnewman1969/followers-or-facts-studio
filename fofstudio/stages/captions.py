"""Stage 7 - Captions: word timings for every narrated scene.

With faster-whisper installed, words are timed from the audio itself and then
replaced by the script's own words (so names are spelled the way the script
spells them). Without it, the script's words are spread across the audio in
proportion to their length, which is close enough for a calm narrator.
The render stage turns these timings into the final .srt file.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from ..config import settings
from ..episode import Episode
from ..util import StageError, read_json, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context
from .script import load as load_script

_whisper = None


def _proportional(words: list[str], seconds: float) -> list[dict[str, Any]]:
    weights = [len(w) + 2 for w in words]
    total = sum(weights) or 1
    t, out = 0.0, []
    for w, wt in zip(words, weights):
        d = seconds * wt / total
        out.append({"word": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


def _whisper_words(path: str) -> list[dict[str, Any]]:
    global _whisper
    from faster_whisper import WhisperModel
    if _whisper is None:
        _whisper = WhisperModel(settings()["captions"]["whisper_model"], device="cpu",
                                compute_type="int8")
    segments, _ = _whisper.transcribe(path, word_timestamps=True, language="en")
    return [{"word": w.word.strip(), "start": w.start, "end": w.end}
            for seg in segments for w in (seg.words or [])]


def _align(script_words: list[str], heard: list[dict[str, Any]], seconds: float) -> list[dict[str, Any]]:
    """Give each script word the timing of the heard word it matches."""
    norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())  # noqa: E731
    a = [norm(w) for w in script_words]
    b = [norm(h["word"]) for h in heard]
    timed: list[dict[str, Any] | None] = [None] * len(script_words)
    for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            h = heard[block.b + k]
            timed[block.a + k] = {"word": script_words[block.a + k], "start": h["start"], "end": h["end"]}
    # fill gaps by spreading them between the matched neighbours
    i = 0
    while i < len(timed):
        if timed[i] is not None:
            i += 1
            continue
        j = i
        while j < len(timed) and timed[j] is None:
            j += 1
        start = timed[i - 1]["end"] if i > 0 else 0.0
        end = timed[j]["start"] if j < len(timed) else seconds
        span = _proportional(script_words[i:j], max(0.05, end - start))
        for k, w in enumerate(span):
            timed[i + k] = {"word": w["word"], "start": round(start + w["start"], 3),
                            "end": round(start + w["end"], 3)}
        i = j
    return [t for t in timed if t]


def run(ctx: Context) -> None:
    ep = ctx.episode
    manifest = read_json(ep.path("audio", "narration.json"), {}) or {}
    if not manifest:
        raise StageError("Approve Narration first.")
    engine = ctx.options.get("engine") or settings()["captions"]["engine"]
    use_whisper = False
    if engine in ("auto", "whisper"):
        try:
            import faster_whisper  # noqa: F401
            use_whisper = True
        except ImportError:
            if engine == "whisper":
                raise StageError("faster-whisper isn't installed (pip install faster-whisper).")
    timings: dict[str, Any] = {"method": "whisper" if use_whisper else "proportional",
                               "made_at": utc_now(), "scenes": {}}
    for sc in load_script(ep)["scenes"]:
        ctx.check_cancel()
        m = manifest.get(sc["scene_id"])
        if not m:
            continue
        words = sc["narration"].split()
        ctx.progress(f"Timing captions for {sc['scene_id']}")
        if use_whisper:
            try:
                words_timed = _align(words, _whisper_words(str(ep.abs(m["path"]))), m["seconds"])
            except Exception as exc:  # noqa: BLE001
                if engine == "whisper":
                    raise StageError(f"Whisper failed: {exc}")
                ctx.log(f"Whisper couldn't run ({exc}); timing captions by estimate instead.")
                use_whisper = False
                timings["method"] = "proportional"
                words_timed = _proportional(words, m["seconds"])
        else:
            words_timed = _proportional(words, m["seconds"])
        timings["scenes"][sc["scene_id"]] = {"text_sha": m["text_sha"], "words": words_timed}
    write_json(ep.path("captions", "words.json"), timings)
    ctx.log(f"Captions timed by {timings['method']}.")


def check(ep: Episode) -> list[Check]:
    timings = read_json(ep.path("captions", "words.json"))
    manifest = read_json(ep.path("audio", "narration.json"), {}) or {}
    if not timings:
        return [Check(BLOCK, "No caption timings yet. Run this stage.")]
    stale = [s for s, m in manifest.items()
             if timings["scenes"].get(s, {}).get("text_sha") != m["text_sha"]]
    if stale:
        return [Check(BLOCK, f"Narration changed for {', '.join(stale)}; run Captions again.")]
    out = [Check(OK, f"Captions timed for {len(timings['scenes'])} scenes ({timings['method']}).")]
    if timings["method"] == "proportional":
        out.append(Check(WARN, "Timed by estimate. Install faster-whisper for exact word timing."))
    return out


def build_srt(scene_starts: dict[str, float], timings: dict[str, Any], lead: float = 0.0) -> str:
    """Group timed words into readable caption lines and shift them onto the timeline."""
    cfg = settings()["captions"]
    max_chars, max_secs = int(cfg["max_chars"]), float(cfg["max_seconds"])
    cues: list[tuple[float, float, str]] = []
    for scene_id, start in scene_starts.items():
        words = (timings.get("scenes", {}).get(scene_id) or {}).get("words", [])
        line: list[dict[str, Any]] = []
        for w in words:
            text = " ".join(x["word"] for x in line + [w])
            too_long = line and (len(text) > max_chars or w["end"] - line[0]["start"] > max_secs)
            if too_long:
                cues.append((start + lead + line[0]["start"], start + lead + line[-1]["end"],
                             " ".join(x["word"] for x in line)))
                line = []
            line.append(w)
            if re.search(r"[.!?]$", w["word"]):
                cues.append((start + lead + line[0]["start"], start + lead + line[-1]["end"],
                             " ".join(x["word"] for x in line)))
                line = []
        if line:
            cues.append((start + lead + line[0]["start"], start + lead + line[-1]["end"],
                         " ".join(x["word"] for x in line)))

    def stamp(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    out = []
    for n, (a, b, text) in enumerate(cues, 1):
        b = max(b, a + 0.5)
        if n < len(cues):
            b = min(b, cues[n][0] - 0.01)
        out.append(f"{n}\n{stamp(a)} --> {stamp(b)}\n{text}\n")
    return "\n".join(out)
