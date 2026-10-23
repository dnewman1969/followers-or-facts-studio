# Setup on your PC

You already have: Windows 11, RTX 3060 12 GB, Git, Ollama with Qwen models,
ComfyUI with Z-Image Turbo working. This adds the Studio on top.

## 1. Make room (optional)

The MiniMax H3 test files (~42 GB in `F:\AI\ComfyUI\models`) aren't used by the
Studio: H3's free licence doesn't cover the US. Delete them if you need the space:
`minimax_h3_*` and `qwen3vl_32b_minimax_h3*` in `diffusion_models`, `text_encoders` and `vae`.

## 2. Get the code

```powershell
cd F:\AI
git clone https://github.com/dnewman1969/followers-or-facts-studio
cd followers-or-facts-studio
```

## 3. Run setup

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -YouTube -ComfyModels
```

This:

- installs Python 3.12 if needed and makes a private `.venv` (ComfyUI's Python is untouched)
- installs ffmpeg if needed
- creates `F:\AI\fof-data`, the settings file and the database
- imports your research from `C:\Projects\truth-vlog\research` (or the copy bundled in `seed\`)
- downloads the Kokoro voice (~340 MB)
- with `-ComfyModels`: downloads Wan 2.2 animation and ACE-Step music models into ComfyUI (~45 GB)
- with `-YouTube`: installs the upload packages
- puts **Followers or Facts Studio** on your desktop
- runs `doctor`, which lists anything still missing

Leave off `-ComfyModels` if you want stills-only episodes for now; you can run
`scripts\get-comfy-models.ps1` later.

## 4. Each time you make videos

Double-click **Followers or Facts Studio** on your desktop (it's also in the Start menu).
A small window starts Ollama and ComfyUI if they aren't already running, waits until
both answer (the first ComfyUI start can take a minute or two), then opens the Studio.
When you close the Studio, the ComfyUI it started is closed too, unless jobs are still
running in the queue.

If the icon is missing, open `F:\AI\followers-or-facts-studio` and double-click
**Update Studio.cmd**. It gets the newest version and makes the icon.

If ComfyUI won't start from the icon, go to Settings → services → `comfyui_command`
and type how you normally start it, for example
`F:/AI/ComfyUI/run_nvidia_gpu.bat`. "Show ComfyUI messages" on the startup window
shows what went wrong.

## 5. Your first episode

1. **1 Database**: the Stories tab is open. Click **Y2K: a real bug sold as the end of the world**
   (6 of 6 claims have proof on file), read the breakdown, press **OK — research this**.
2. **2 Research** opens and lists the evidence already on file (nothing starts by itself).
   Choose the **Research time** (Normal takes about 15–30 minutes), press **Start research**, and
   watch the progress line. When it finishes, click each row to read what it is and what it shows,
   type a word in the search box to narrow the list, and **tick** the evidence this video will use
   (nothing starts ticked). Want more on something? Tick it and press **Dig deeper on ticked**.
   Then **Approve and continue**.
3. **3 Stories**: press **Create 3 stories**, read them, press **Use this story** on one (or
   **Rewrite with notes**), then approve.
4. **4 Script**: press **Write the script**, read and edit, **Save my changes**, approve.
5. **5 Storyboard**: press **Make pictures** (ComfyUI paints 3 per scene), tick the ones you like, approve.
6. **6 Video**: **1. Write scene instructions**, read them, change any to **Camera move** if you
   want it quicker, **2. Make the clips** (animations take ~6 minutes each; good overnight),
   watch them, **Approve all clips**, approve.
7. **7 Production**: **1. Make speech track**, **No music** (or **2. Make music**),
   **3. Assemble timeline**, **Make preview** and watch it, adjust, **4. Render final video**, approve.
8. **8 Publish**: **Write it up**, read the description, **Upload to YouTube (private)**.

## Making more videos from the same research

Everything the research agents find is saved in the database. **1 Database → Researched ★**
lists every subject you've researched and the videos made from it:

- **Open this video** picks up where you left off.
- **New video: pick different evidence** starts a new episode with the same research and nothing
  ticked, so you can tick other evidence (and dig deeper on it) for a different story.
- **New video: use another of its stories** starts a new episode with the same ticks and the same
  three stories, so you can make the ones you didn't pick. Stories already made say so.

## Optional free keys that unlock more sources

Put these in **Settings → research**. Everything works without them.

| Setting | What it adds | Where to get it (free) |
|---------|--------------|------------------------|
| `courtlistener_token` | Court opinions and filings (about 125 searches a day) | Make an account at courtlistener.com, then your profile → API token |
| `factcheck_key` | Existing fact-checks from Snopes, PolitiFact, AP and others | Google Cloud console → enable "Fact Check Tools API" → create an API key |
| `archive_access_key`, `archive_secret_key` | Faster, more reliable Wayback Machine saves (30,000 a day instead of 200) | archive.org account → https://archive.org/account/s3.php |

## If something goes wrong

- **"Ollama is not running" / "ComfyUI is not running"** — start it, then Run again.
- **ComfyUI says a model is "not in list"** — the model file name in the workflow doesn't
  match yours. See `comfy_workflows\README.md`.
- **The queue is paused** — a job failed. The Queue page shows the error. Fix it, press Resume.
- **Settings** page → **Test Ollama** / **Test ComfyUI**, or run
  `.venv\Scripts\python -m fofstudio doctor` in PowerShell.
- Logs: `F:\AI\fof-data\logs\worker.log` and `app-errors.log`.
