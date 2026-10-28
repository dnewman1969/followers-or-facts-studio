# Models, and why each one

Everything here is free to use on a monetized YouTube channel in the US.
Check a model's licence before adding it, and add a line here when you do.

| Job | Model | Licence | Where it goes | Size | Speed on RTX 3060 12 GB |
|-----|-------|---------|---------------|------|------------------------|
| Script, storyboard, quote finding | Qwen 3 14B (`qwen3:14b`) in Ollama | Apache-2.0 | already installed | ~9 GB | ~30 tokens/s |
| Checks (a different model) | Qwen 3 8B (`qwen3:8b`) | Apache-2.0 | already installed | ~5 GB | |
| Caricature references (sees pictures) | Qwen3-VL 8B (`qwen3-vl:8b`) | Apache-2.0 (confirm on the Ollama/HF card before first use) | `ollama pull qwen3-vl:8b` | ~6 GB | only for Cast → Research looks |
| Clay looks (optional LoRA) | ClayAnimation-Redmond-ZIMAGE | Apache-2.0 | `models/loras` (not wired in yet) | | |
| Pictures | Z-Image Turbo bf16 | Apache-2.0 | already in ComfyUI | | 8 steps |
| Animation | Wan 2.2 I2V 14B fp8 (high + low noise) + Lightning 4-step LoRAs | Apache-2.0 | `models/diffusion_models`, `models/loras` | ~2 × 14 GB + 2 × 1.2 GB | ~5–6 min per 5 s clip (reported by another 3060 owner) |
| ...its text encoder | umt5_xxl fp8 | Apache-2.0 | `models/text_encoders` | ~6.7 GB | |
| ...its VAE | wan_2.1_vae | Apache-2.0 | `models/vae` | ~0.3 GB | |
| Narration | Kokoro-82M v1.0 (ONNX) | Apache-2.0 | `fof-data/models/kokoro` | ~340 MB | ~2x real time on the CPU |
| Voice cloning (optional) | Chatterbox | MIT, adds an inaudible watermark | downloaded on first use | | needs ~6 GB VRAM |
| Captions | faster-whisper `small.en` | MIT | downloaded on first use | ~0.5 GB | CPU |
| Music (optional) | ACE-Step v1 3.5B (ACE-Step 1.5, MIT, is the upgrade: export its ComfyUI template in API format with the same placeholders) | Apache-2.0 | `models/checkpoints` | ~7.7 GB | one cue per mood change, 20–180 s each |
| Sound effects, Owlbert's moves | our own code (`sfx.py`, `rig.py`, `bits.py`) | ours | | | |
| Depth for 2.5D moves (optional) | Depth Anything V2 **Small** (`depth_anything_v2_vits.pth`) via the comfyui_controlnet_aux nodes | Apache-2.0 (Small only; Base/Large/Giant are non-commercial) | downloaded by the node on first use | ~100 MB | about a second a picture; without it the program estimates depth itself |
| B-roll from words (optional) | Wan 2.2 TI2V-5B (`wan2.2_ti2v_5B_fp16` + `wan2.2_vae`) | Apache-2.0 | `models/diffusion_models`, `models/vae` | ~10 GB + 1.4 GB | not measured yet; "under 9 min per 5 s 720p" on a consumer GPU per Wan; native 24 fps |
| Smooth camera moves | OpenCV (`opencv-python-headless`) | Apache-2.0 | pip package | | a 5 s 1080p move in a few seconds on the CPU |
| Owlbert's mouth timing | Rhubarb Lip Sync 1.14 | MIT | `fof-data/models/rhubarb` | small | seconds per line, CPU |
| Web search for the research agents | ddgs (DuckDuckGo, Bing, Brave... no key) | MIT | pip package | | |
| Reading article text from pages | trafilatura | Apache-2.0 | pip package | | |
| Book PDFs | ReportLab (`reportlab`), with the PDF's built-in Times and Helvetica fonts (nothing embedded) | BSD | pip package | | seconds |

`scripts/get-comfy-models.ps1` downloads the Wan 2.2 and ACE-Step files; add `-TextToVideo` for TI2V-5B.

Also checked and fine for a monetized US channel, not wired in yet: Qwen-Image and Qwen-Image-Edit-2511
(Apache-2.0; Edit keeps a character the same across edits), FLUX.2 klein 4B (Apache-2.0), HiDream-I1 (MIT),
RIFE frame interpolation (MIT), FILM (Apache-2.0), Wan 2.2 S2V and InfiniteTalk (Apache-2.0, lip sync,
probably too heavy for 12 GB). LTX-2.3 is free under $10M revenue but needs every video to say it's AI and
about 16 GB of VRAM. HunyuanVideo 1.5's licence excludes the EU, UK and South Korea.

## A model for each job (Settings → models)

Each AI job can use its own Ollama model; empty means the writer model (`qwen3:14b`). Install a model with
`ollama pull <name>` before choosing it. From the research "Best local AI models per job" (Oct 2026):

| Job (setting) | Suggested | Why |
|---------------|-----------|-----|
| research_quotes, research_summary, checks | keep `qwen3:14b` / `qwen3:8b` | the most faithful that fit 12 GB (Vectara: 5.4% / 4.8% made-up content; the newer Qwen 3.5 models are 10.5-12.1%) |
| research_plan, script_plan | try `qwen3.5:9b` (Apache-2.0, ~50 tokens/s on a 3060) | stronger reasoning for planning searches and scenes |
| script_write, stories | try `gemma4:12b` (Apache-2.0, fits fully at 16K context) | recommended for prose; no published writing scores yet, so compare it with qwen3:14b on one episode first |

Ollama settings that help on 12 GB: `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` (Windows
environment variables, then restart Ollama).

**Answer format check.** Some Ollama versions ignore the JSON answer format the Studio sends (Ollama issue
#14645: with thinking off, /api/chat ignored it for Qwen3 from 0.30.0, and for Qwen3.5/3.6 and Gemma 4;
reported fixed in 0.31.2). That is the likely reason the script planner once returned 3 scenes for 16. Now
the first time a model is used, the Studio tests whether Ollama obeys the format; if only /api/generate
does, it uses that; and every answer is checked in Python and sent back (up to twice) with the problems
listed. Results: `<data>/logs/ollama-format-check.json`, and in Queue → GPU check.

**Quotes by sentence number.** Research quotes are picked by sentence number: the AI never writes the
quote, the program copies the exact sentences (up to 3 in a row, one paragraph), so they always match the
saved source.

## Ruled out

| Model | Why |
|-------|-----|
| MiniMax H3 | Free licence excludes the US, EU, UK and South Korea, outputs included. Commercial licence from $5,000/month. |
| XTTS v2 | Coqui Public Model Licence: non-commercial, for the model and its audio. Coqui shut down, so it can't be bought. |
| F5-TTS, MMAudio | Non-commercial. |
| MusicGen, SongBloom | Non-commercial weights (CC-BY-NC). |
| GIMM-VFI (frame interpolation) | S-Lab licence, non-commercial. Use RIFE or FILM (Apache-2.0). |
| Depth Anything 3 LARGE v1.0 / GIANT / NESTED, Video Depth Anything Base/Large | Non-commercial. The SMALL/BASE/MONO-LARGE/METRIC-LARGE/LARGE-1.1 and Video-Small checkpoints are Apache-2.0. |
| madmom (beat tracking) models; aubio | Non-commercial models; GPL. Use librosa (ISC). |
| FLUX.1 dev, FLUX.1 Kontext dev, FLUX.2 klein 9B, FLUX.2 dev | Non-commercial licences. (FLUX.2 klein 4B is Apache-2.0 and would be fine.) |

## Keeping the owl on model

Now: Owlbert's storyboard shots are his real artwork placed into a set the AI paints in the video's style,
so he's identical in every shot, and animation starts from that picture. The talking corner presenter and
the bumpers use the same art. Next step (not built): 8–12 on-model images → a Z-Image Turbo LoRA trained
with ai-toolkit on 12 GB (768 px, ~2,000 steps, 1–2 hours), or Qwen-Image-Edit-2511 to re-pose him.

## One heavy model at a time

The worker unloads Ollama's model (`keep_alive: 0`) before a ComfyUI job and asks
ComfyUI to free its memory before an Ollama job, so the 12 GB card never holds both.
The 128 GB of system RAM is what lets the 14B Wan models run on a 12 GB card.

## Not allowed on this channel (licences checked 2026-10-28)

- InsightFace pretrained models (antelopev2, buffalo): "non-commercial research purposes only". So InstantID,
  PuLID, PhotoMaker and IP-Adapter-FaceID are out. The caricature designer never uses face ID or face
  measurements; a vision model answers plain multiple-choice questions and no photo reaches ComfyUI.
- Qwen-Image 2.1 (20 Sept 2026) moved to a non-commercial research licence: stay on Qwen-Image / Qwen-Image-Edit
  up to 2511 if they're ever added.
- FLUX.1-dev and LoRAs built on it (most felt / sock-puppet / claymation LoRAs): the licence excludes
  revenue-generating use of the model.
- Bespoke-MiniCheck-7B (fact checking): CC BY-NC 4.0.
- Any LoRA whose trigger word is a show, studio or brand name (it puts a trademark into saved metadata).

