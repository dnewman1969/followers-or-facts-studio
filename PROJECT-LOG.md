# Project log

Read this first in a new session, then add to it at the end.

## 2026-10-22 — v0.1: the merged program

Built Followers or Facts Studio from Dave's repos (truth-vlog, OwlBox, EchoForge,
Nimrod's Tower, ai-agent-studio, the VoxBox family) and the "Free AI Video Creator"
handoff. One Python 3.12 app, native Windows window (PySide6).

**Works and is tested** (21 automated tests, run on Linux with ffmpeg; GPU services faked):

- Research database imported into SQLite with the same IDs: 487 claims, 388 sources,
  54 arcs, 353 people, 1,145 KF episodes. Six shifted arc rows repaired, the duplicate
  Flynn merged, 16 duplicate links dropped. Validator: 0 errors.
- The full pipeline from research packet to packaged video, with every editorial gate.
- Render engine (stills with camera moves, video clips, transitions, narration, ducked
  music, subtitles) produces correct-length MP4s with sound.
- Kokoro voice tested for real: 54 voices, `bm_george` default, ~2x real time on a CPU.
- Job queue: one job at a time, heartbeats, pauses on failure.

**Written but not yet run against the real services** (needs Dave's PC):

- Ollama prompts for script, storyboard and quote finding (Qwen 3 14B).
- ComfyUI templates: Z-Image Turbo, Wan 2.2 I2V + Lightning, ACE-Step. Written from
  ComfyUI's examples; node names may need a tweak on first run.
- faster-whisper word timing (falls back to estimated timing if it can't run).
- YouTube upload.
- Render Mode suspend/resume on Windows; NVENC encoding.

## 2026-10-22 — one-click start

Dave ran setup but couldn't find how to start the program. Now the desktop icon
(made by `scripts/make-shortcut.ps1`, using Windows' real Desktop folder, which can be
inside OneDrive) opens a startup window that starts Ollama and ComfyUI if needed,
waits for both, then opens the Studio (`fofstudio/services.py`, `app/startup.py`).
ComfyUI is found automatically (git install with venv, portable build, run_nvidia_gpu.bat,
or the Desktop app on port 8000), or from Settings → services → comfyui_command.
Closing the Studio stops the ComfyUI it started unless the queue is busy.
`Update Studio.cmd` pulls updates and remakes the icon. 26 tests pass.

## 2026-10-22 — fix: data folder path

First launch on Dave's PC failed: Windows PowerShell 5's `Set-Content -Encoding UTF8`
puts a byte-order mark at the start of `config/data-dir.txt`, so the path became
`\ufeffF:\AI\fof-data`. config.py now reads it with utf-8-sig, setup.ps1 writes it
without the mark, and `Update Studio.cmd` re-runs `init` and `download-models`
(both safe to repeat) because the failed setup skipped them.

## 2026-10-22 — v0.2: rebuilt around Dave's flow

Dave couldn't tell whether clicks registered or jobs were running, and wanted the program to
follow his own order. Rebuilt the window and the pipeline:

- **Feedback everywhere** (`app/widgets.py`): activity bar on every page (job, live progress
  text, % bar or moving bar, elapsed time, Cancel), toasts when jobs start/finish, taskbar
  flash, buttons that grey out and say "Starting...", pressed styles, ✔ ● … ✖ marks on the steps.
  Jobs report progress as text + percent (`job.progress_pct`), written within a second.
- **Steps**: 1 Database (Stories/Conspiracies/People/Organizations + breakdown, `subjects.py`)
  → 2 Research (agents, `agents/` + `stages/research.py`) → 3 Stories (3 options, rewrite with
  notes) → 4 Script → 5 Storyboard (3 pictures per scene, pick) → 6 Video (written scene
  instructions, then Wan 2.2 or camera-move clips, approve each) → 7 Production (editor:
  speech/captions/music, 4-track timeline `app/timeline.py`, preview player, render) → 8 Publish.
- **Research agents**: plan searches per claim (qwen3), search with ddgs + CourtListener +
  Federal Register + Library of Congress (+ Google Fact Check with a key), read pages
  (trafilatura; Wayback Machine copy when a page is gone), keep quotes only if word for word,
  add finds to the database as `S-WEB-...` sources (`found_by='agent'`), archive every link
  with Save Page Now. Honest User-Agent, robots.txt, per-site delays, cache, CourtListener
  daily counter.
- **Owlbert** (`owl.py`): cut-out puppet from the profile art (beak shapes, blinks), timed by
  Rhubarb Lip Sync (downloaded by `download-models`) or loudness; corner presenter overlaid
  in the render from an ffconcat list of PNGs; intro/outro bumpers; voice = Kokoro blend
  `bm_george:0.7,bm_fable:0.3`, speed 0.93, +1 semitone.
- Description fits YouTube's 5,000 limit without ever dropping the credit lines; the full
  proof list is saved to `publish/proof-links.txt` for the pinned comment.
- Research report behind these choices: "Studio rebuild design research" (in the Truth Web page project).

34 tests pass (Linux, fake AI services, real ffmpeg). Screenshots of every page checked offscreen.
Not yet run on Dave's PC: real research agent searches, ComfyUI workflows, Rhubarb download,
preview playback with sound, YouTube upload.

## Next

1. Dave: run Update Studio.cmd, then make S01E01 (Y2K fear industry) end to end; report anything odd.
2. Fix whatever the first real run turns up in the ComfyUI templates and prompts.
3. Owlbert on model: turnaround sheet, LoRA, intro/outro shots.
4. Shorts: vertical clips from the render.
5. Research intake: Scout-style lead extraction from new transcripts into the database.
6. The followersorfacts.com static site from the sourced claims.

## Decisions

- Everything free for a monetized US channel: no MiniMax H3, XTTS, F5-TTS, FLUX dev.
- Python everywhere; OwlBox's Node engines rewritten in Python.
- Native Windows app (PySide6), not a browser UI.
- Code in git; media and models in `F:\AI\fof-data` (never committed).
- Voice cloning only for voices with a consent record (`voices/<name>/rights.json`).
