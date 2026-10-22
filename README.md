# Followers or Facts Studio

One program on your own PC that takes a story from the research database all the
way to a finished, uploaded YouTube video, stopping for your OK after every step.
No subscriptions: the AI runs on your PC (Ollama + ComfyUI + Kokoro), and the
only online service is the free YouTube upload.

```
Research ─► Script ─► Storyboard ─► Narration ─► Images ─► Animation ─► Captions ─► Music ─► Render ─► Package ─► Upload
  (DB)      (Qwen)      (Qwen)       (Kokoro)   (Z-Image)   (Wan 2.2)   (Whisper)  (ACE-Step) (ffmpeg)  (sources,   (YouTube,
                                                                                                         thumbnail)   private)
```

**New here? Start with [docs/SETUP.md](docs/SETUP.md).** It's about 20 minutes plus downloads.

## What it does

| Stage | What happens | You check |
|-------|--------------|-----------|
| Research | Pulls the arc's claims and sources from the database, saves copies of the source web pages and PDFs, and finds quotes in them. A quote is kept only if it appears **word for word** in the saved copy. | Every claim has a primary source |
| Script | Qwen 3 14B drafts the script from the research only, with claim and source IDs on every scene. You can edit `script.md`. | No invented sources, quotes are verified, 6th-grade reading level, the four questions are answered |
| Storyboard | Each scene becomes shots: AI pictures, quote cards, title cards, real document screenshots. | No real person in a picture prompt |
| Narration | Kokoro reads each scene (default voice: `bm_george`, British male). | Listen through |
| Images | ComfyUI makes the AI pictures with Z-Image Turbo and the program stamps "AI illustration" on them. Cards are drawn locally, so quotes are always exact. | Look through, remake any |
| Animation | Optional. Wan 2.2 animates one shot per scene (~5–6 min each on the 3060). Skip it for stills with camera moves. | Watch the clips |
| Captions | Word-by-word timing for subtitles. | |
| Music | Optional. ACE-Step makes a quiet instrumental bed, or you pick a track you own. | Listen |
| Render | Everything assembled: camera moves, cross-fades, narration, music ducked under the voice, subtitles. NVENC on the RTX 3060. | Watch the whole thing |
| Package | Title, description with every source and the Knowledge Fight credit, chapters, thumbnail with Owlbert, pinned comment. | Read it |
| Upload | Uploads as **private**, marked as containing AI content. You make it public. | |

Approving a stage unlocks the next. Redoing a stage sends the stages after it back
for another look, so nothing stale gets published.

## Where things live

```
F:\AI\
├─ ComfyUI\                    your existing install (images, animation, music)
├─ followers-or-facts-studio\  this program (code only, in git)
└─ fof-data\                   everything it makes (not in git)
   ├─ db\studio.sqlite         research database + episodes + job queue
   ├─ episodes\S01E01-...\     one folder per video: script.md, images\, audio\, render\, publish\
   ├─ source-copies\           saved copies of every source page, with the date we looked
   ├─ models\kokoro\           the narration voice
   ├─ music-library\           tracks you own (with a .txt note of where each came from)
   └─ settings.toml
```

## Where the parts came from

This program merges your earlier projects; see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
The research database is truth-vlog's (imported with the same IDs), the render
engine and voice are OwlBox's (rewritten in Python), the job queue is Nimrod's
Tower's, the quote checks are from the ai-agent-studio Scout workflow, and the
swappable voice interface is EchoForge's.

## Command line

Everything in the window can also be done from PowerShell, for example:

```
.venv\Scripts\python -m fofstudio arcs                 # best-sourced story arcs
.venv\Scripts\python -m fofstudio new S01E01 "Y2K: the fear machine" --arc A-Y2K-FEAR-INDUSTRY
.venv\Scripts\python -m fofstudio queue S01E01 research
.venv\Scripts\python -m fofstudio status S01E01
.venv\Scripts\python -m fofstudio approve S01E01 research
```

Run the tests with `.venv\Scripts\python -m pytest`.
