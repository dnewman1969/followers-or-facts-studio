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

## 2026-10-22 — v0.3: research you choose, keep and reuse

Dave's first real run (S01E02) stopped at Script: "SCENE_003: source E14 doesn't exist in the
database" for most scenes. Cause: Research labels quotes E1, E2...; the stories cite those labels;
the script writer copied them into the sources list, and the check only knew database source IDs.
Fixed in `stages/script.py`: the writer gets each story beat's real source IDs and quote numbers,
`fix_refs` turns E-numbers into the quote plus its source (and fills claims from sources, or the
ticked sources for a claim with none, with a note), and the check reads E-numbers the same way.

Dave also asked for:

- **Research doesn't start by itself.** The page lists what's on file straight away (no internet,
  `research.prepare`), you choose the research time (new: "only the sources already on file"), then press Start.
- **Nothing starts ticked**; a search box and a Show filter (ticked / new / quotes / court and
  government); Tick/Untick all shown; NEW marks on the last run's finds.
- **A summary of each source** (`source.summary`, written by the AI from the saved page) shown in the
  list and the detail pane.
- **Dig deeper on ticked**: the agents search around the ticked items (`options.focus`, optional notes).
- **Only ticked evidence** reaches Stories, Script and the description (`research.selected`).
  Research blocks if nothing is ticked or a claim's ticked evidence has no primary source.
- **Researched ★ tab** on the Database page (`researched.py`): subjects researched, the videos made
  from each, Open, New video with different evidence, New video with another of its stories
  (`stories.set_id`, `stories.used_by` marks stories already made).
- Research was already saved in the database (sources, quotes, links to claims); now summaries too,
  and any new video on the same subject starts with everything found so far.

42 tests pass.

## 2026-10-22 — v0.3.1: the script points at evidence to tick; progress while the AI writes

S01E02's story (written before ticks existed) leaned on the Senate final report, which wasn't
ticked, so the script check blocked it. Now `script.wanted_unticked` finds evidence the script
uses that isn't ticked; the Script page shows a gold box with **Tick what the script needs** and
**Show me on Research**, and the Research page highlights those rows in gold (tag SCRIPT, filter
"Only what the script wants", **Tick them for me**).

Progress while the local AI writes: `Ollama.chat(on_text=...)` streams the answer and
`Context.writing()` reports "N words written so far" with a rough percent (script, 3 stories,
rewrites). Every step page now has its own progress line (`widgets.PageProgress`) while one of
its jobs runs. Also fixed see-through colours (Qt reads #rrggbbaa as #aarrggbb, which made gold
chips and boxes red): `common.tint()`.

44 tests pass.

## 2026-10-23 — v0.4: creative styles, smooth video, sound, YouTube sign-in

Dave's first full test: scripts read like a dry documentary; the video jittered; pictures repeated to
fill time; the video came out shorter than the length set; Owlbert's hat looked washed out; no sound in
the preview; he wanted volume controls, timeline zoom, the folder opened after a render, YouTube sign-in
in Settings, and the AI to suggest 4 thumbnail words per story. Research report: "Creative styles and
studio polish" (in the Truth Web page project).

- **Styles** (`styles.py`): 12 presets, each with tone, pace (wpm), shot length, picture recipe, motion
  recipe, Owlbert staging, a sample passage, default humor, and whether caricatures are allowed.
  Per-episode `creative` settings (style, minutes, humor 0-3, caricatures) in episode.json; careful topics
  force humor 0 and no caricatures (`Episode.creative`). Panel on the Stories page (`app/creative.py`).
- **Critical thinking** (`techniques.py`): 12 "Tell" cards (FLICC + Roozenbeek's five + follow the money).
  Stories name 1-2; the script has `tell` and `toolkit` roles; the storyboard draws Owlbert's Tell card.
- **Writer** (`stages/script.py`): outline pass, then one call per scene with Owlbert's voice bible, the
  style's tone and sample, only that scene's facts and the end of the previous scene; one fix-up for
  short or stock-phrase scenes; per-scene word budgets from the target length. Script blocks below 80%
  of the length; `expand` option = **Make it longer**. Streamed word counts. Qwen 3 sampling settings.
- **Storyboard v2** (`stages/storyboard.py`): shots per scene = narration seconds / style shot length;
  shot kinds broll / owl (painted set + Owlbert's real art composited, so he's always on model) /
  caricature; 2 versions per shot (setting), pick, skip, remake, replan. Old boards are blocked with a
  message to remake.
- **Caricatures** (`cast.py`, Cast window): only people linked to the ticked claims as said_it /
  amplified / benefited / platformed, never targets/victims/families/private; written design approved by
  Dave, never the name in prompts; caption + AI label; only in sourced scenes; description note.
  Editorial rule changed on purpose (was "never draw real people").
- **Video**: new `text_to_video` method (Wan 2.2 TI2V-5B workflow `wan22_ti2v5b_t2v.json`, untested on the
  PC; `get-comfy-models.ps1 -TextToVideo`); characters are animated first.
- **Jitter fixed**: camera moves are drawn per frame with OpenCV at exact fractional positions (zoompan
  rounded to whole pixels; measured shake 0.145 → 0.013 px/frame). AI clips: no more `-stream_loop`
  repeats; slow-motion capped at 1.35x with minterpolate in-betweens; hold the last frame if still short.
  Camera-move shots are redrawn at their exact timeline length. Production shares each scene's time:
  clips keep their length, camera moves and cards fill the rest. BT.709 tags; preview 854x480 at 24 fps.
- **Owlbert's hat**: the cut-out's background tolerance was 60 and his cap is only ~20 away from the
  backdrop, so the cap was cut away. Now 11, with a soft edge and a cream rim. Thumbnails, bumpers and the
  Tell card use a teal backdrop instead of navy. Name plate "PROF. OWLBERT · CRITICAL THINKING".
- **Sound** (`app/sound.py`): the player only connected to speakers if Windows had listed them at startup;
  now always (chosen speaker or default, follows plug/unplug), mute + volume on the player, Settings →
  Sound (speaker, test chime, Owlbert test voice, listening volume, default mix, loudness, playback
  engine). Mix per video on Production (speech/music/master dB) → render (`volume`, loudnorm to -14 LUFS,
  384k AAC 48 kHz stereo). PySide6 ≥ 6.9.
- **Timeline zoom**: slider, +/−, Fit, Ctrl + wheel at the mouse, view stays anchored.
- **Folder opens** after the final render (`util.reveal`, Explorer /select).
- **YouTube** (`youtube.py`, Settings → YouTube): choose client file (checked: must be Desktop app),
  sign in (browser, consent, in a thread), shows the channel, sign out. Uploads never open a browser
  mid-job; retries 5xx; notifySubscribers false. docs/YOUTUBE.md rewritten (In production to stop the
  7-day expiry; private-lock test; 2026 quota).
- **Thumbnail words**: each story's `thumbnail_words` (max 4) pre-fill Publish.

56+ tests pass. Not yet run on Dave's PC: the new writer prompts with qwen3:14b, the TI2V-5B workflow,
minterpolate speed on his CPU, real speaker selection, YouTube sign-in.

## Next

1. Dave: run Update Studio.cmd, then make an episode in a new style end to end (Stories → style); report.
2. Owlbert LoRA or Qwen-Image-Edit poses, so his painted scenes can show other poses.
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
