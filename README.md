# Followers or Facts Studio

One program on your own PC that takes a story from the research database all the
way to a finished, uploaded YouTube video, stopping for your OK after every step.
No subscriptions: the AI runs on your PC (Ollama + ComfyUI + Kokoro), and the
only online service is the free YouTube upload.

```
1 Database ─► 2 Research ─► 3 Stories ─► 4 Script ─► 5 Storyboard ─► 6 Video ─► 7 Production ─► 8 Publish
 (choose a    (agents find   (3 ways to   (Owlbert's   (3 pictures   (scene        (editor: speech,  (write-up with
  story)       the proof)     tell it)     narration)   per scene)    instructions,  timeline, owl,    every proof link,
                                                                      then clips)    preview, render)  upload private)
```

**New here? Start with [docs/SETUP.md](docs/SETUP.md).**

## How it feels to use

- The bar along the top always shows what the computer is doing, how far along it is
  (a percentage when known), how long it's been going, and a Cancel button.
- Every button reacts when you click it, and a notice pops up when a job starts and when
  it finishes (the taskbar button flashes too).
- The steps down the left show ✔ approved, ● needs your OK, … running, ✖ failed.
- Nothing moves on without your OK. Approve and continue takes you to the next step.

## The steps

| Step | What happens | You do |
|------|--------------|--------|
| 1 Database | Pick a Story, a Conspiracy, a Person or an Organization from the research database. A breakdown shows every claim it will cover, who benefited, the harm, the people involved and how much proof is on file. **Researched ★** lists what you've already researched and the videos made from it. | Press **OK — research this**, or start another video from saved research |
| 2 Research | Research agents read the sources on file (or their Wayback Machine copies), search the web, court records (CourtListener), the Federal Register and the Library of Congress for more proof, keep only quotes found word for word in the saved page, and write a short summary of each source. Every link gets a permanent Wayback copy. Everything found is saved in the database. | Choose the research time, press Start; search the list, tick the evidence to use (nothing starts ticked), dig deeper on anything ticked; approve |
| 3 Stories | Three different story plans that tell the tale and take the lie apart: follow the money, then-and-now, and the people it hurt. | Pick one, or **Rewrite with notes** |
| 4 Script | Owlbert's narration, written from the chosen story, with the proof each scene relies on. | Edit, save, approve |
| 5 Storyboard | Three AI pictures per scene (Z-Image Turbo in ComfyUI), plus title and quote cards drawn as text. | Tick the pictures to use; remake any |
| 6 Video | The AI writes how each picture plays out and how it will be made; then Wan 2.2 animates the chosen ones and the rest get slow camera moves. | Edit instructions; watch and approve each clip |
| 7 Production | A video/audio editor: Owlbert reads the script into the speech track, then the timeline lines up the intro bumper, your clips, Owlbert in the corner, his voice, music and the outro. Preview player with Play/Pause/Stop. | Drag and trim, preview, **Render final video** |
| 8 Publish | Title, description with every proof link and its archived copy, chapters, Knowledge Fight credit, thumbnail with Owlbert. | Edit, approve, **Upload** (private) |

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
