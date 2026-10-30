# How it's built

One Python 3.12 program. The window (PySide6) and a background worker share one
SQLite database. The worker runs one job at a time and talks to Ollama, ComfyUI,
Kokoro and ffmpeg.

```
                   ┌───────────── window (PySide6) ─────────────┐
                   │ Home · Research · Episode · Queue ·        │
                   │ Render Mode · Settings                     │
                   └───────────────┬────────────────────────────┘
                                   │ queue a stage / approve
                         ┌─────────▼─────────┐
                         │ studio.sqlite     │  research tables, projects,
                         │ (WAL mode)        │  stage history, job queue
                         └─────────▲─────────┘
                                   │ claim next job, heartbeat
                   ┌───────────────┴────────────────────────────┐
                   │ worker  (python -m fofstudio worker)       │
                   │  unloads Ollama before ComfyUI and back    │
                   └──┬──────────┬──────────┬──────────┬────────┘
                   Ollama     ComfyUI     Kokoro     ffmpeg
                   (Qwen)  (Z-Image, Wan,  (voice)   (render)
                            ACE-Step)
```

## Code map

| File | Job | Came from |
|------|-----|-----------|
| `fofstudio/db/schema.sql`, `importer.py`, `validate.py` | Research database in SQLite, import with fixes, checks | truth-vlog `research/` CSVs, `research_schema.py`, `validate_research.py` |
| `fofstudio/sources.py` | Save source copies, extract text, verify quotes word for word | Scout workflow's quote check (ai-agent-studio); Nimrod's Tower "prose is not evidence" rule |
| `fofstudio/stages/research.py` | Research packet | new |
| `fofstudio/scriptfmt.py`, `stages/script.py` | Script format and checks | truth-vlog v2 scene format |
| `fofstudio/stages/storyboard.py` | Shots and image prompts | truth-vlog `shot-list.csv` + `export_ai_prompts.py` guardrails; VoxBox-Video style presets |
| `fofstudio/comfy.py`, `comfy_workflows/` | ComfyUI client and templates | new (no ComfyUI code existed) |
| `fofstudio/engines/tts.py` | Swappable voices: Kokoro, Chatterbox | EchoForge `voice.py`/`tts.py` interface; OwlBox voice (Kokoro) |
| `fofstudio/stages/captions.py` | Word timings and SRT | new (OwlBox had one cue per scene) |
| `fofstudio/engines/render.py` | Camera moves, transitions, clips, narration, ducked music | OwlBox `engine/` rewritten in Python and extended |
| `fofstudio/cards.py` | Quote/title/credits cards, AI label, thumbnail | truth-vlog `render_episode.py` card idea + BRANDING-KIT colours |
| `fofstudio/stages/publish.py` | Description, chapters, thumbnail, search tags; upload is on YouTube's page in the browser (publishkit.py) | truth-vlog templates |
| `fofstudio/jobs.py` | Queue, worker, heartbeats, pause on failure | Nimrod's Tower `research_queue.py` / `overnight_runner.py` |
| `fofstudio/rendermode.py` | Suspend/resume other programs, VRAM readout | new (the handoff's Render Mode idea) |
| `fofstudio/pipeline.py` | What can run, approvals, what a redo invalidates | new |
| `fofstudio/app/` | The window | new; dark theme in channel colours |

## Episode folder (the contract between stages)

```
episode.json      id, title, arc, claims
research.json     the packet: claims, sources (with saved-copy paths), verified quotes, careful-topic rules
research.md       the same, readable
script.md         the script (you can edit it); parsed on every check
storyboard.json   shots: type, prompt, text, quote/source IDs, camera, weight, animate,
                  image {path, raw, seed, model, workflow}, clip {path, seed, model}
audio/narration.json, audio/narration/SCENE_###.wav
captions/words.json   word timings per scene
audio/music/music.json + bed file
render/<id>.mp4, <id>.srt, timeline.json (shot start times, chapters)
publish/metadata.json, description.txt, thumbnail.png, pinned-comment.txt, upload.json
receipts/<shot id>.png   real screenshots you supply for "receipt" shots
```

Every generated file records the model, seed and workflow that made it.

## What wasn't brought over

- VoxBox / VoxBox-Video / VoxBox-Studio runtime code: it depended on Gemini and faked results
  (stock photos on failure, a timer for "publish"). Only ideas were kept.
- n8n: orchestration is in Python now. n8n could still run small scheduled jobs on the laptop.
- Nimrod's Tower's sleep lab, prediction and 4D pages.
- Project-Nullspace, Vector-Drop-2, EchoesOfTheDeep: unrelated.
