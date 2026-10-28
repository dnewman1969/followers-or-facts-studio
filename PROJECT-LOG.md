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

## 2026-10-23 — v0.4.4: unstuck AI, the script directs music and Owlbert

Dave was still on 0.4.2 (title bar) when the storyboard failed again. Two real problems in it:

- **The AI got stuck writing blank space** ("29 words written so far" for minutes, then out of room).
  Every answer is now streamed; 150 pieces in a row of only spaces/new lines stop it early and it tries
  again a little differently (warmer, more presence penalty, new seed). Shot planning halves its batch
  if a batch still fails.
- **"The script changed since these pictures were made"** was wrong: the board was only half made
  because the run stopped. It now says "Pictures are made for N of M scenes... press Make pictures to
  carry on".

Research ("ComfyUI music and Owlbert directing", project docs) then shaped:

- **script.md gets MUSIC and OWLBERT sections** per scene (mood/energy/change/drop before/sting at; moves
  tied to quoted narration words). The writer fills them; `script.tidy_directions` enforces the rules
  (mood by role never verdict, no playful over harm or careful topics, ≤6 stings, music out before the
  verdict line, quoted words must be in the narration).
- **Music per mood**: `stages/music.py` groups scenes into cues and makes each with ACE-Step in one of
  25 genres (`musicbook.py`, picker on the Production page) at one tempo and related keys; the outro
  theme is made once and reused; or tracks from the library matched by mood, with licence notes checked.
  The timeline lays cues with cross-fades, stings and drops; the render mixes several cues and effects.
- **Owlbert moves from the script** (`bits.plan_directed`): new glasses, think, hat tip, solemn, surprised,
  swoop and verdict stamp moves, a document prop (source title and date) for the hat trick; budgets from
  the research (1 big + 2 small a scene, no hat trick two scenes running, harm scenes respectful only).
- **Sound effects** made in code (`sfx.py`): whoosh, flutter, pop, sparkle, stings, stamp thud (A3 track).
- docs/MUSIC.md (public-domain rules for 2026: songs ≤1930, recordings ≤1925), MODELS.md ruled-out list.

88 tests pass.

## 2026-10-23 — v0.4.4 fix: the update was blocked by a stray database

v0.4.3 accidentally committed `F:/AI/fof-data/db/studio.sqlite` (an import check run here, outside the tests,
made a folder literally named "F:"). On Dave's PC git saw it as his real database and refused to update -
good, nothing was overwritten. Removed from git; .gitignore now blocks `F:/` and `*.sqlite`; every test now
uses a throwaway data folder even without the data fixture; Update Studio.cmd's error points at the message.

## 2026-10-24 — v0.5.0: one Owlbert, story types and writers, more motion, GPU log, add to database

- **Upload**: the Publish page shows what's ready (packages, client file, signed in); Upload signs in first
  if needed (browser) and writes it up if needed (autopublish), always private. The Google client file is
  found automatically in Downloads/Desktop/data folder (where Google's own uploader expected it). Still
  waiting for Dave's actual error message to confirm the root cause.
- **Only one Owlbert**: owl shots are painted as empty sets (Owlbert words scrubbed from the prompt);
  the render lays the live talking rig Owlbert on the set at 66% height; the corner presenter and moves
  stay out of owl shots (`production.away_from_owl_shots`, render subtracts ranges).
- **Add to database** (`newsubject.py`, Database → "+ Add new"): topic, conspiracy, person or group, each
  with a seed claim (unverified, no sources) ready for Research; careful flag adds courts_only.
- **GPU check** (`gpucheck.py`, Queue → "GPU check"): logs/gpu-report-*.txt (nvidia-smi, Ollama % on GPU,
  live writer test with tokens/s and GPU busy, ComfyUI device, encoder, per-step summary) and
  logs/gpu-usage.csv sampled every 5 s during every job.
- **Story types and writers** (`storytypes.py`, `data/writers.json`, research "Story types writer voices
  animation"): 13 beat-sheet story types and 15 writing styles, picked on the Stories page or "AI picks"
  three different ones; careful topics get sober types and no light writers; the script outline follows
  the beat sheet and every scene carries the writer's style block.
- **More motion**: Video page "Animation: Fast / Balanced / Full" (1 in 10 / 1 in 3 / every shot by Wan,
  with a GPU-hours estimate); every other picture is a 2.5D parallax move (Depth Anything V2 Small in
  ComfyUI if comfyui_controlnet_aux is installed, else estimated depth). Owl sets and careful-topic harm
  scenes are never Wan-animated.

92 tests pass.

## 2026-10-24 — v0.5.1: corner Owlbert only, research steps, genre + director + length scan

- Dave's screenshot (from 0.4.x): a big pasted Owlbert, an AI-drawn owl and the corner owl together. Now
  scenes have no Owlbert at all by default (`owl.in_scenes` False: the storyboard doesn't plan owl shots);
  only the corner presenter and his moves. Old painted owl shots are listed on the Storyboard page.
- Research page: phase strip (sources on file → quotes → web/courts/news → summaries → permanent copies →
  done) and a scrolling list of every step (jobs write logs/<stage>-steps.log). The top progress text no
  longer pushes the bar off the window (label size policy Ignored).
- Script page (research "Film genres directors and video length"): 16 genres (`data/genres.json`) and 18
  director styles (`data/directors.json`, trait-only prompts, shown as "X (inspired by Y)"), used by the
  script writer, the storyboard art director and picture prompts, shot length, and the music when it's
  "to suit the style". "Scan the story" (hidden stage `scan`, `stages/lengthscan.py`) estimates the honest
  length; then "Produce script". 96 tests pass.

## 2026-10-24 — v0.5.2: story size check and the book

- Stories now sizes the story up first (`stages/storysize.py`): the local AI judges complexity, timeline
  events, people and threads; the program works out Short / one video / series / book, with minutes and
  pages, shown above the three stories (`size.json`).
- Book (hidden stage `book`, `stages/book.py`, PDF by `bookpdf.py` with ReportLab, BSD): chapter plan in
  fixed parts (introduction, origin, players, spread, record, profit, damage, techniques, verdict), then
  chapter by chapter from that chapter's evidence and saved-source passages only. Text checks: every
  paragraph cites; numbers must be in the cited material; quotation marks must match the sources word for
  word; quotes are printed by the program; unknown names flagged. One rewrite, then failing paragraphs are
  removed and listed in `book/review.md`. DRAFT on every page until Approve the book. Resumes chapter by
  chapter. Stories page: Write the book / Finish / Write again / Open the PDF / What to check / Approve.
  102 tests pass.

## 2026-10-24 — v0.5.3: the script keeps its length and its four must-have parts

Dave's S01E02 (Patient Zero, Investigator, Animated Family Film, Archive Pan, 20 min) came out at 3.5
minutes with no record, benefit or harm scene. The AI planned only ~3 of the 16 scenes and nothing made
it plan more. Now (`stages/script.py`): the beat sheet is spread over the scenes (`scene_slots`, at least
one scene per beat, big beats get more, and the four must-have parts are added to any story type that
lacks them - "The Turn" had no benefit beat, "ABT" no benefit or harm); the outline schema asks for that
many scenes and the roles in order; a short or incomplete plan gets one more try, then the program fills
the empty slots from the beat sheet (`fill_outline`); word budgets come from the scenes actually planned.
Scan (`lengthscan.py`): the range always contains the recommendation (it said "46 to 25 minutes"), it
counts only the claims the chosen story uses, and a story longer than 20 minutes says how long and in how
many parts. Quotes in 'single quote marks' (3+ words) are now checked like double-quoted ones
(`scriptfmt.quotes_in`; the narration had an unchecked single-quoted quote), in scripts and the book.
107 tests pass.

## 2026-10-24 — v0.5.4: made-up quotes fixed while writing; caricatures box

- Dave's S01E03 script was blocked by four "quote doesn't match any verified quote" errors: words the writer
  put in quote marks that weren't verified quotes (a source summary with "..." in it, a denial, and made-up
  example lines like "Only 10 minutes left" in the tell scene), and a made-up boy named Sam. Now
  (`stages/script.py`): quotes may leave words out with "..." if every piece is word for word in order
  (`quote_matches`); after each scene is written, a quote that is a real verified quote gets its E-number
  listed, other quoted words go back to the writer once, and if still unverified their quote marks come off
  so they're said as a paraphrase (`fix_quotes`, logged). The writer and story writer are told: no invented
  people or characters, no quote marks around summaries, shortened quotes or example lines; technique
  examples reach the writer without quote marks. "Fix made-up IDs and quotes" on the Script page fixes an
  existing script (`repair`). The check itself is unchanged in strictness.
- Caricatures box (Stories): it was greyed out in every style but Political-cartoon satire, which looked
  broken. Now it's clickable; ticking it in another style offers to switch the video to that style.
- Research "iPhone alerts and control for Studio" (in progress / project docs).
111 tests pass.

## 2026-10-24 — v0.5.5: a model per job, answer-format check, quotes by sentence number

From the research "Best local AI models per job" (project docs):

- **Answer-format check** (`llm.py`): Ollama issue #14645 (schema ignored on /api/chat with thinking off,
  Qwen3 from 0.30.0) explains the 3-scene outlines. The first time each model is used with a format, a tiny
  test (ask for 2 colors while the format demands exactly 4 from red/green/blue) shows whether /api/chat or
  /api/generate enforces it; answers then go through the one that works (`_as_generate`). Results per
  model@version in `<data>/logs/ollama-format-check.json`; `[ollama] format_check`. Every JSON answer is
  checked in Python (`schema_problems`: required, types, enums, min/max, min/maxItems), code fences
  stripped, and sent back up to twice with the problems; `lenient=True` for callers that repair answers
  themselves (script outline and scenes, storyboard shots, book), else a StageError naming the model.
  Queue → GPU check now lists the result for every model the jobs use.
- **A model per job** (`llm.JOBS`, `model_for`, Settings → models): research_plan, research_quotes,
  research_summary, stories, script_plan, script_write, storyboard, book, checks. Empty = writer model, so
  nothing changes until Dave picks one. Suggestions in docs/MODELS.md.
- **Quotes by sentence number** (`research.numbered_sentences`, `copy_sentences`, `picks_schema`): the AI
  answers with sentence numbers (only real ones allowed); the program copies the exact words (up to 3
  sentences in a row in one paragraph; abbreviations like Dr., U.S., No. 5 don't split sentences).

## 2026-10-26 — v0.5.6: speed test, two short-video stories, the book as a movie, style on Script

- **Speed test** (`speedtest.py`, Queue → Speed test, hidden stage `speedtest`): times each job's AI model,
  a storyboard picture, optionally one Wan clip, a 2.5D move and Owlbert's voice; writes
  logs/speed-test-<date>.txt and logs/speed-test.json with an estimate for a 10-minute video. The Video page's
  GPU-hours estimate uses the measured Wan time once there is one. Steps that can't run say why.
- **Stories** (`stages/stories.py`): two stories (STORY_COUNT) instead of three, the second told to differ
  from the first; each has the AI's length estimate (`length_seconds`, 30-600, up to 180 = a YouTube Short)
  and choosing a story sets the video length.
- **The movie** (`make_movie_story`, `movie_minutes`): a book-sized subject's book becomes a long documentary
  story (30-120 minutes: ~40% of the book's words at 150 a minute, or the full-telling estimate), its beats
  the book's chapters plus any of claim/record/benefit/harm it lacks. The script follows those beats with up
  to 90 scenes (`_scene_count`), Script length up to 150 minutes. Stories page: "Make the book into a movie".
- **Video style and caricatures moved to the Script page** (`CreativePanel(show=...)`); Stories keeps story
  type, writer and humor; the story writer no longer gets the style.
- Research reports "Video quality 3D Owlbert and variety" and "Bestseller book craft for nonfiction"
  (project docs). `repeats.py` added (used in the next step).
119 tests pass.

## 2026-10-26 — v0.5.7: no broken record

From the research (repetition comes from writing scenes without memory; fix it in planning and code, not
Ollama's repeat settings):
- `repeats.py`: sentence similarity (2-word runs of content words) and shared 7-word runs, overused phrases
  across scenes, a bigger stock-phrase list, and an "already said" ledger of key sentences.
- Script (`stages/script.py`): **fact budget** (`budget_facts`: each verified quote in one scene only, every
  ticked quote and primary source used somewhere); every scene prompt gets the "already said" ledger; a scene
  that re-tells an earlier one goes back once with the sentences listed; checks warn about repeats, overused
  phrases, stock phrases, a quote used twice, and thin research for the length (`material_note`, ~1.5 ticked
  items a minute). **Fix repeats** (option `derepeat`) rewrites only the repeating sentences.
- **Channel memory** (`channelmemory.py`, <data>/channel-memory.json): each script records its opening, ending,
  hook, quotes and lead facts; stories and scripts for episodes sharing a claim or arc are told what earlier
  videos already did.
- Book: each chapter gets the earlier chapters' ledger; a paragraph that mostly re-tells earlier text is
  removed (listed in review notes), a stray repeated sentence is flagged.
122 tests pass.

## 2026-10-26 — v0.5.8: the book writer learns from bestsellers; writers can look things up

From the research "Bestseller book craft for nonfiction" (project docs):
- **Shape per story type** (`book.BOOK_SHAPES`): each of the 13 story types orders the nine parts its own way
  (Follow the Money leads with the money, The Trial with the players and the record...); `tidy_outline` no
  longer forces one fixed order. The book uses the story type and writer chosen on the Stories page (or the
  chosen story's; sober ones on careful topics, `book_type_and_writer`), and the writer's style block.
- **Plan**: an action line every chapter advances, a cast of at most four (names checked against the
  research), strongest dated moment in chapter 1, channel memory, and up to 8 **gap questions**.
- **Beats** (`plan_beats`): each chapter is written in parts of 300-700 words (opening scene, evidence or
  document beats, a fairness beat where people are named, a forward pull at the end), each with its own
  evidence, the chapter so far and the "already said" ledger; one targeted fix per part (only the failing
  paragraphs). New rules: no guessing at thoughts ("must have", "probably felt", starting with "Imagine"),
  documents as events, fair responses, legal words as the record has them, endings that pull forward from the
  record, grade 8-10 prose.
- **Look it up** (hidden stage `lookup`, `research.lookup`): the book's gap questions (Stories page) and the
  script planner's (`script-questions.json`, Script page "Look these up") go to the research agents; finds
  arrive on the Research page as NEW and unticked, never straight into a script or book.
125 tests pass.

## 2026-10-26 — v0.5.9: real pictures with proven licences, labelled re-creations

- `mediafinder.py`: searches Wikimedia Commons, then Openverse (commercial filter); accepts only public domain,
  CC0, CC BY, CC BY-SA; refuses NC/ND/unknown and news agencies; never victims or private people; nothing of
  people or the event on careful topics; public figures only in scenes whose claims link them as sellers
  (`public_ok`). Downloads keep a provenance JSON. Settings → media.
- Storyboard: new shot kind `real` (with `search` and `subject`); version 1 is the real picture if one is found
  (fitted into the frame, credit caption top-left), version 2 is always a drawn re-creation stamped
  RE-CREATION; if nothing usable is found both are re-creations and the reasons are kept (`why_not_real`).
  Check warns to look over each real picture. Real photos are never Wan-animated or text-to-video (2.5D only);
  animated re-creations carry the RE-CREATION overlay. The description gets an "Image credits" block and a
  re-creation note. EDITORIAL-RULES updated (Dave's request).
- Tests: archive searches are "offline" in tests (conftest), so storyboards use re-creations.
127 tests pass.

## 2026-10-26 — v0.5.10: a new project starts with clean pages

Dave: starting a new project from the Database should clear steps 2-8. Some pages only updated when the new
job had something to show, so the Publish page kept the old title, description, thumbnail words and
"Uploaded" link, and the Script page kept the old notes for the writer. Now `StagePage.set_episode` calls
`new_episode()` when the project changes (Publish, Script, Research clear their fields; cached signatures
reset). Regression test `test_a_new_project_starts_with_clean_pages` (fails on the old code). 128 tests pass.

## 2026-10-26 — v0.6.0: YouTube upload made easy (research "Easy YouTube upload like PowerDirector")

PowerDirector is easy because CyberLink ships its own Google-approved project inside the program; a personal
app can't borrow that (and copying another app's key breaks YouTube's rules). For one user, your own project
"In production" needs no Google review. The likely cause of Dave's failures: the app still in "Testing", where
Google signs you out 7 days after consent; and the refresh error was swallowed, so the real reason never showed.
- `youtube.py`: `explain()` turns Google's errors into plain words with the fix (invalid_grant → publish the
  app; access_denied; redirect_uri_mismatch; no channel; missing "Manage your YouTube videos" permission;
  quota; sign-in timeout/firewall). A failed refresh is recorded (youtube-expired.json) and shown; sign-in
  times out after 10 minutes instead of hanging; the granted permissions are checked.
- Settings → YouTube → **Set up YouTube, step by step** (`app/youtube_ui.SetupDialog`): one button per Google
  page (project, enable API, Branding, Audience → Publish app, Desktop client), "Find my client file",
  Sign in, with checks.
- Publish → **Upload in my browser (no setup)** (`publishkit.py`, `PublishKitDialog`): opens YouTube's upload
  page and the video's folder, copy buttons for title/description/tags, a checklist (not for kids, altered
  content yes, captions, thumbnail, private), then paste the link back to record the upload. Offered whenever
  the Google setup isn't done, and named in every upload error.
- docs/YOUTUBE.md: Publish app moved before the client download; tick "Manage your YouTube videos".
131 tests pass. Open question: whether YouTube still locks API uploads from unaudited projects as private
(Google's pages disagree in Oct 2026): one test upload settles it; the browser kit works either way.

## 2026-10-27 — v0.6.1: the script writer is a cinematic story architect

Dave said the script writer read like a report and gave the brief: find the characters, conflicts, mysteries,
goals, obstacles and stakes in the research; build the arc hook → setup → rising tension → discovery → climax →
resolution → future implications; tell it like a documentary in the director's style; never invent a fact.

- New first step, the **film treatment** (`stages/treatment.py`, planner model): film title, logline, opening
  scene, three acts (what happens, feeling, turning point), key characters (real only: names checked against the
  people and organisations in the ticked research, invented ones dropped and logged), major revelations (each
  must list ticked evidence, else dropped), emotional arc, open questions, closing thought. Saved as
  treatment.json / treatment.md; cleared at the start of each run so an old one never sits beside a new script.
- The scene plan follows the treatment. The program then gives every scene its place in the arc by position
  (hook first, implications last, in order) and puts each revelation in the scene that holds its proof.
- Every scene prompt now starts with the architect brief (Dave's 10 points, fact rules kept) and the scene's
  part of the film: the logline, its act and feeling, the characters, the revelation to land, the opening
  scene (scene 1), the open questions and closing thought (the end).
- Report language added to the stock-phrase list, so "according to the research", "in summary", "this report"
  etc. send a scene back for a rewrite.
- Script page: tabs "Final narrative (the script)" and "Film treatment: <title>". The script header names the film.
- If the planner can't make a usable treatment, the script is still written from the outline, and the log says so.
- Fixed a flaky book test (it assumed the default chapter order; the book follows the story type's shape).
Tested with the fake AI only (137 tests).

## 2026-10-28 — v0.6.2: the Virtual Director (quality gate before painting)

Dave's pipeline: Research → Story Writer → Storyboard → **Virtual Director (quality gate)** → Prompt Builder →
ComfyUI → Video → Editor → Final movie, with a long brief for the director (attached to the chat).

- `director.py`. The storyboard now plans every shot of every scene first, then the director reviews the whole
  list in order, then painting starts.
  - Each shot has a look: location, shot type (16), angle, camera move (13), pose, emotion, lighting (13), palette
    (10), intensity 0-10. The planner fills these in; anything missing is read from the idea's own words.
  - Similarity to shots N-1..N-5 and N-10 (weighted fields plus how alike the ideas are): 90%+ REJECT, 70-89%
    REPAIR, under 70 APPROVE. Rules: 3 close-ups, 4 medium, 4 same angle, 5 static, the same move 3 times;
    place, pose (4), light and colour (5) fatigue; pacing (5 high-intensity shots, or 6 at the same level).
  - Scores per shot: similarity, variety, location, camera, pose, colour, pacing (Dave's output format) in
    director-review.json / .md.
  - Repairs: up to 2 tries with the director AI (new job "director", Settings → models), at most 30 shots per run
    (Settings → director); continuity guard (no new place the scene doesn't mention, no day/night flip inside a
    scene, no real names); then the program reframes the shot itself (shot type, angle and move not used just
    before). Your own ideas (Remake with new words) are scored, never rewritten; remaking one shot only re-scores.
  - A shot still REJECTED blocks Storyboard approval; your own near-repeats only warn.
- Prompt Builder: each shot's framing, light, colour and mood go into the picture prompt. The Video plan uses
  the director's camera move (mapped to the render's moves, with words for Wan) instead of the AI's guess.
- Storyboard page: approved / repaired / rejected on every shot (hover for the scores and what changed) and a
  "Director's review" button.
- Not done from the brief: switching the picture style mid-video (one style per video keeps continuity; it's
  chosen on the Script page) and the brand-named modes (South Park, Hanna-Barbera, Muppet...): the existing
  directors are described by traits only, per the director policy.
Tested with the fake AI only (146 tests).

## 2026-10-28 — v0.7.0: styles database, style mixer, honest claims, no more repeats

From two research reports ("Art styles caricatures and hybrids", "AI writer repetition and claim checks") and
Dave's requests on 28 Oct.

**Styles and caricatures**
- `data/styles.json`: the 12 house styles plus 73 new looks (animation, film and TV history, puppets and stop
  motion, print and posters, fine art, storybook, international), each in Dave's format (visual DNA, character
  design, linework, palette, background, animation, lighting, best uses, prompt elements) with tier, difficulty,
  medium, careful/caricature flags, cultural/political notes and a human-only `inspired_by`. `styles.py` is now a
  loader; new looks are "(untested)" until kept. Built with a one-off script from the research notes.
- `data/hybrids.json` (Dave's 13 examples rewritten by traits + 25 recipes), `data/caricature_traditions.json`
  (18, tiered A/B/C/exclude), `data/visual_language.json` (metaphors, shape language, colour script, symbol and
  cultural rules), `data/watchlist.json` (brand, show, format and artist names).
- `styleengine.py`: mixes (BODY from one look, WORLD from another; key `mix:a+b`), clash rules (proportions,
  careful topics, politically coded looks, care looks need OK, dropped looks), fatigue score across the last 8
  videos (medium and palette double, 0.8 decay), "due" families, recommendations. Script page → Fresh looks...
- Storyboard → Test styles...: hidden stage `styletest` paints two fixed test pictures per look (plus an invented
  salesman for caricature looks), a contact sheet in `<data>/style-tests/`, Keep / Drop saved in
  `<data>/style-ratings.json`; dropped looks leave the pickers.
- Fix 1 (positive prompts): Z-Image runs at cfg 1, so "no X"/"Avoid: X" did nothing. Guards rewritten as things to
  draw, the "Avoid:" tail removed, `promptcheck.py` strips negations and watchlist names from every picture prompt;
  the medium now comes first. Publish blocks brand/artist names in the title or tags.
- Fix 2 (caricature designer): Cast → "Research looks from free photos": 3-6 PD/CC photos from Commons, the
  vision model (`qwen3-vl:8b`, new job "vision") answers multiple-choice face questions per photo, majority vote,
  a kind design pushing 1-3 features (no fields for skin, weight, race, religion), saved with its references
  (new caricature columns design_json, references_json). Photos never reach ComfyUI. Cast window also picks the
  caricature tradition. The name-recall `propose()` is no longer offered.
- Likeness rule (Dave): public figures may be caricatured; never a victim or a child in any form (cast NEVER words
  extended; shot planner told; "child" is a refused real-picture subject). Careful-topic lock unchanged.
- Stories page: "Let the AI pick (2 different)".

**Script writer**
- Each scene sees only its budgeted quotes (`_facts_for` leaked every quote of a shared source: the cause of one
  quote in six scenes); the empty-scene fallback no longer shares sources.
- Topic ledger (IDs, claim titles, numbers already given) instead of 45 earlier sentences.
- Length follows the material: per-scene caps (45 words per fact unit); "the video must fill N minutes" removed;
  "Honest length" in the header; the length check warns instead of blocking when the script matches it.
- Delete, don't rewrite: `dedupe_scenes` keeps each quote in its first scene and removes re-told sentences (also
  the first step of Fix repeats). `find_repeats` no longer exempts quotes in scenes.
- `claimcheck.py`: claims hold up by rule A (primary record) or B (two independent quoted sources; same site,
  publisher or near-copy quotes count once); unverified/contested verdicts don't. Weak claims are left out of
  stories/script/cast (logged, Research page banner) and get a Deep dive (hidden stage `deepdive`: planned
  questions → research.lookup; finds unticked). After writing, the checker model takes out fact sentences their
  scene's evidence doesn't back (subtractive only; claim-check.json). Settings → claims.check_sentences.
- Prose temperature 0.7 (Qwen's recommendation).
Tested with the fake AI only (170 tests).

## 2026-10-28 — v0.7.1: caricature looks from a normal image search

Dave's first run: Commons had only 1 free photo of Francis Boyle, and the vision model got stuck writing blank
space for Alex Jones. Dave: the photos are only for the AI to look at, not for the videos, so any photo will do.
- `cast.find_references` now does a normal web image search (the `ddgs` package the research agents already use:
  "<name> <role>" and "<name> portrait"), plus the Wikipedia lead image and Commons, any licence. Photos are
  shrunk to 768 px, looked at by the vision model, then the folder is deleted. Never used in a video or sent to
  ComfyUI; still at least 3 clear faces and a majority vote, so no single photo is copied.
- The vision call no longer forces an answer format (that made qwen3-vl write only blank space): plain text,
  read by `parse_vision` (JSON or "key: value" lines, matched to the allowed words). A missing model says
  "ollama pull qwen3-vl:8b".
- Editorial rule row updated. Couldn't test the live image search from the cloud workspace (blocked there).

## 2026-10-28 — v0.7.2: caricatures in Dave's five steps, with previews

Dave's second run: "0 of 0 photos" for Alex Jones, "0 of 1" for Francis Boyle. The photo sites refused the
Studio's downloader (it says it's a research program). Dave's brief: research → feature analysis → design
(exaggerate key features ~25-50%, respectful) → art direction → output (features, exaggerations, prompt,
artwork, 3 alternate styles).
- Photos: the image search's own thumbnail is fetched first (search-engine thumbnails load fine), then the photo
  with an image Accept header and the page as Referer; DuckDuckGo then Bing; 15 results for "<name> <role>" and
  "<name> face". Still only looked at, then deleted.
- Vision step also gives free notes: what you'd notice first, clothing, posture (kind words only: notes about
  skin, weight, age, race, religion or disability are dropped).
- Design: the writer AI picks the 1-3 recognisable features and exaggerates them 25-50%, in the chosen
  caricature tradition, with the agreed features, notes and vote counts; the name is never written (replaced
  if it slips in); falls back to the plain composed design.
- Output in the Cast window: key features, exaggerations with percentages, the design; "Paint previews" paints
  it in the chosen style and 3 alternate traditions with ComfyUI (<data>/caricature-previews/).
- One clear photo now works with a warning (the design is words, never a copy of a photo); none = a plain error
  saying how many were found and downloaded.

## 2026-10-28 — v0.7.3: a thinking model isn't a stuck one

Dave's third run: 16 of 16 photos downloaded for everyone, but "no clear face" in all of them. Cause: qwen3-vl
streams its reasoning in message.thinking with empty content; `_stream` counted 150 empty chunks as "stuck
writing blank space", retried, gave up, and the caricature research skipped the photo silently (so the message
blamed the photos). Fixes: thinking counts as progress; an answer left only in the thinking is used; the
research stops after 3 failed photos with the real error; every photo's raw answer or error goes to
<data>/logs/vision-log.json.

## 2026-10-28 — v0.7.4: the vision model that just answers

Research (notes "Local vision model face reading"): on Ollama `qwen3-vl:8b` IS `qwen3-vl:8b-thinking` (same
digest); it isn't a hybrid model, so "think": false is ignored and it can spend the whole answer reasoning
(Ollama issues #12837, #12906, #13353, #14798, #16945; maintainers won't change it). The answer-only model is
`qwen3-vl:8b-instruct` (6.2 GB, Ollama 0.12.7+). Default changed; `cast.vision_model()` swaps any bare or
-thinking Qwen3-VL tag in old settings for the -instruct one. Dave needs: ollama pull qwen3-vl:8b-instruct.

## Next

1. Dave: run Update Studio.cmd, then make an episode in a new style end to end (Stories → style); report.
2. Owlbert: technique props (cherry, mask...); Qwen-Image-Edit wing drawings.
2. Music: own recordings of public-domain pieces (MIDI + FluidSynth + MIT SoundFont); beat snapping (librosa).
2. ComfyUI: Kandinsky 5/6 Lite B-roll, SeedVR2 upscale, RIFE 16→24 fps, Depth Anything 3 (Apache sizes) parallax.
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
