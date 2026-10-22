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

1. Start **Ollama** (it usually starts with Windows).
2. Start **ComfyUI** (`F:\AI\ComfyUI`, the way you normally do).
3. Open **Followers or Facts Studio** from the desktop.

## 5. Your first episode

1. **Research** page → pick `A-Y2K-FEAR-INDUSTRY` (6 of 6 claims sourced) → **Make episode from arc**.
2. On the **Episode** page, select **Research** → **Run**. It saves the sources and finds quotes.
   Read what it found, then **Approve**.
3. **Script** → Run. Read `script.md` in the editor, change anything, **Save**, then **Approve**.
   If something's blocked (an invented source, an unverified quote), the reason is listed in red.
4. Keep going down the list. Each stage tells you what to check.
5. For a first episode, **Skip** Animation and Music to get a finished video fastest.
6. **Render** with "Quick 720p draft" ticked first, then the full version.
7. **Package**, read the description, then **Upload** (private).

Long jobs (Images, Animation) run in the background. You can close the window;
the **Queue** page shows progress when you come back.

## If something goes wrong

- **"Ollama is not running" / "ComfyUI is not running"** — start it, then Run again.
- **ComfyUI says a model is "not in list"** — the model file name in the workflow doesn't
  match yours. See `comfy_workflows\README.md`.
- **The queue is paused** — a job failed. The Queue page shows the error. Fix it, press Resume.
- **Settings** page → **Test Ollama** / **Test ComfyUI**, or run
  `.venv\Scripts\python -m fofstudio doctor` in PowerShell.
- Logs: `F:\AI\fof-data\logs\worker.log` and `app-errors.log`.
