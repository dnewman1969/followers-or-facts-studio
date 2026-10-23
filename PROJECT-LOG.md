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

## 2026-10-23 — v0.4.1: jobs that never started, Clear buttons, code check

Dave: jobs stayed "queued" and never moved; old work on earlier pages blocked later ones.

- **Queue** (`jobs.py`): (1) a killed worker's lock file survived, and after a restart Windows reused its
  process number for another program, so the app thought the worker was running and never started one
  (same for "running" jobs never marked interrupted). Now the process must really be
  `python -m fofstudio worker` (psutil cmdline), the worker refreshes its lock every 10 s, and a lock
  that isn't ours is removed. (2) A worker that crashed on start-up vanished silently: its output now
  goes to `logs/worker-console.log`, the top bar and Queue page show its last message, and after two
  failed starts jobs run on a thread inside the Studio (`start_thread_worker`; closing warns). (3) A
  paused queue (after any failure or an interrupted job) held everything: pressing a Run button now
  resumes it, and the top bar has a Resume button. Start attempts are throttled. Queue page: "Test the
  worker" queues the hidden `selftest` stage; "Run jobs inside the Studio".
- **Clear and start over** on Stories, Script, Storyboard, Video and Production (`pipeline.clear`):
  deletes that step's files and every later step's, resets them to not started (recorded as `reset`
  with a "cleared" note, shown as not started), cancels their queued jobs; refuses while one of them
  runs; keeps research, ticks, style, earlier steps and `publish/upload.json`.
- **Code check**: ruff (no undefined names; unused imports removed); a whole-window test that visits
  every page and presses the main controls and fails on any error dialog or handler exception;
  worker tests with a real background process, a leftover lock, a dead "running" job and a worker that
  dies on start. Fixes found: an edited timeline is rebuilt automatically when its clips or speech
  changed (it used to keep pointing at deleted files); Length on the Script page saves at once (so you
  can accept a shorter script instead of being stuck); Length stays in sync between Stories and Script;
  pictures are cached and the Storyboard/Video pages redraw at most every 3 s while working; ComfyUI
  slow answers are retried; progress keeps the shot name during long animations; mixer start-up guard;
  storyboard pick index guard.

64 tests pass.

## 2026-10-23 — v0.4.2: the writer can't invent IDs any more

Dave's S01E02 (cartoon style): SCENE_006 cited claim C-10 and sources S-5, S-7, none of which exist.
The scene writer was free to type any ID. Now the outline and scene answers are JSON-schema constrained
to the real ticked IDs (`script.with_known_ids`, enum lists), unknown IDs are dropped in code
(`drop_unknown`), a fact scene left without evidence gets its claim's ticked sources, and the Script
page shows **Remove made-up IDs** (`script.repair`) to fix an existing script without rewriting it.
66 tests pass.

## 2026-10-23 — v0.4.3: room to think, automatic private upload, Owlbert flies

Three things from Dave's latest test:

- **"The local AI ran out of room."** `llm.chat()` now grows when it needs to: if an answer is cut
  off, it retries with double the answer room (up to `ollama.max_predict`, 16,384) and a bigger
  context (up to `max_ctx`, 32,768), plus a little more presence penalty in case it was repeating
  itself; after four tries it says so plainly. Shot planning asks for 6 shots at a time, telling the
  AI what's already planned, instead of one giant answer.
- **Google's uploader** (`fof_youtube_uploader.py`) was merged into our own YouTube code rather than
  added beside it: tag clean-up to YouTube's 500-character rule (`youtube.sanitize_tags`), the
  YouTube Studio link (`youtube.studio_url`), and a hidden `autopublish` job queued after every final
  render: write-up → checks → upload **private** → open YouTube Studio for review. Its separate
  sign-in, token file and print-outs weren't needed (Settings → YouTube already signs in).
- **Owlbert's moves** (`rig.py`, `bits.py`, V3 Moves track): he's cut into body, folded wings, cap and
  tassel, with drawn spread wings, head top, cap inside and props. Moves: fly in, point at the
  evidence, hat trick (trick card or light bulb out of his cap), wing flourish, fly off. Planned from
  scene roles with a budget; careful topics get no playful moves; never mirrored. Drawn as full-size
  transparent frames and laid over the picture; the corner presenter hides while a move plays and no
  longer blinks out between scenes. Research report: "Owlbert mascot animation methods" (project docs).

79 tests pass.

## Next

1. Dave: run Update Studio.cmd, then make an episode in a new style end to end (Stories → style); report.
2. Owlbert: technique props (cherry, mask...), thinking pose, verdict stamp; Qwen-Image-Edit wing drawings.
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
