# Models, and why each one

Everything here is free to use on a monetized YouTube channel in the US.
Check a model's licence before adding it, and add a line here when you do.

| Job | Model | Licence | Where it goes | Size | Speed on RTX 3060 12 GB |
|-----|-------|---------|---------------|------|------------------------|
| Script, storyboard, quote finding | Qwen 3 14B (`qwen3:14b`) in Ollama | Apache-2.0 | already installed | ~9 GB | ~30 tokens/s |
| Checks (a different model) | Qwen 3 8B (`qwen3:8b`) | Apache-2.0 | already installed | ~5 GB | |
| Pictures | Z-Image Turbo bf16 | Apache-2.0 | already in ComfyUI | | 8 steps |
| Animation | Wan 2.2 I2V 14B fp8 (high + low noise) + Lightning 4-step LoRAs | Apache-2.0 | `models/diffusion_models`, `models/loras` | ~2 × 14 GB + 2 × 1.2 GB | ~5–6 min per 5 s clip (reported by another 3060 owner) |
| ...its text encoder | umt5_xxl fp8 | Apache-2.0 | `models/text_encoders` | ~6.7 GB | |
| ...its VAE | wan_2.1_vae | Apache-2.0 | `models/vae` | ~0.3 GB | |
| Narration | Kokoro-82M v1.0 (ONNX) | Apache-2.0 | `fof-data/models/kokoro` | ~340 MB | ~2x real time on the CPU |
| Voice cloning (optional) | Chatterbox | MIT, adds an inaudible watermark | downloaded on first use | | needs ~6 GB VRAM |
| Captions | faster-whisper `small.en` | MIT | downloaded on first use | ~0.5 GB | CPU |
| Music (optional) | ACE-Step v1 3.5B (ACE-Step 1.5, MIT, is the upgrade: export its ComfyUI template in API format with the same placeholders) | Apache-2.0 | `models/checkpoints` | ~7.7 GB | one cue per mood change, 20–180 s each |
| Sound effects, Owlbert's moves | our own code (`sfx.py`, `rig.py`, `bits.py`) | ours | | | |
| B-roll from words (optional) | Wan 2.2 TI2V-5B (`wan2.2_ti2v_5B_fp16` + `wan2.2_vae`) | Apache-2.0 | `models/diffusion_models`, `models/vae` | ~10 GB + 1.4 GB | not measured yet; "under 9 min per 5 s 720p" on a consumer GPU per Wan; native 24 fps |
| Smooth camera moves | OpenCV (`opencv-python-headless`) | Apache-2.0 | pip package | | a 5 s 1080p move in a few seconds on the CPU |
| Owlbert's mouth timing | Rhubarb Lip Sync 1.14 | MIT | `fof-data/models/rhubarb` | small | seconds per line, CPU |
| Web search for the research agents | ddgs (DuckDuckGo, Bing, Brave... no key) | MIT | pip package | | |
| Reading article text from pages | trafilatura | Apache-2.0 | pip package | | |

`scripts/get-comfy-models.ps1` downloads the Wan 2.2 and ACE-Step files; add `-TextToVideo` for TI2V-5B.

Also checked and fine for a monetized US channel, not wired in yet: Qwen-Image and Qwen-Image-Edit-2511
(Apache-2.0; Edit keeps a character the same across edits), FLUX.2 klein 4B (Apache-2.0), HiDream-I1 (MIT),
RIFE frame interpolation (MIT), FILM (Apache-2.0), Wan 2.2 S2V and InfiniteTalk (Apache-2.0, lip sync,
probably too heavy for 12 GB). LTX-2.3 is free under $10M revenue but needs every video to say it's AI and
about 16 GB of VRAM. HunyuanVideo 1.5's licence excludes the EU, UK and South Korea.

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
