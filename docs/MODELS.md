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
| Music (optional) | ACE-Step v1 3.5B | Apache-2.0 | `models/checkpoints` | ~7.7 GB | |
| Owlbert's mouth timing | Rhubarb Lip Sync 1.14 | MIT | `fof-data/models/rhubarb` | small | seconds per line, CPU |
| Web search for the research agents | ddgs (DuckDuckGo, Bing, Brave... no key) | MIT | pip package | | |
| Reading article text from pages | trafilatura | Apache-2.0 | pip package | | |

`scripts/get-comfy-models.ps1` downloads the Wan 2.2 and ACE-Step files.

## Ruled out

| Model | Why |
|-------|-----|
| MiniMax H3 | Free licence excludes the US, EU, UK and South Korea, outputs included. Commercial licence from $5,000/month. |
| XTTS v2 | Coqui Public Model Licence: non-commercial, for the model and its audio. Coqui shut down, so it can't be bought. |
| F5-TTS, MMAudio | Non-commercial. |
| FLUX.1 dev, FLUX.2 klein 9B | Non-commercial. (FLUX.2 klein 4B is Apache-2.0 and would be fine.) |

## Keeping the owl on model

Not built yet. The plan: make a turnaround sheet from `brand/owlbert-profile.png`,
generate 20–30 on-model images, train a Z-Image LoRA, then add Owlbert intro/outro
shots. Simple 2D beak shapes timed from the caption words can do the talking
without a heavy lip-sync model.

## One heavy model at a time

The worker unloads Ollama's model (`keep_alive: 0`) before a ComfyUI job and asks
ComfyUI to free its memory before an Ollama job, so the 12 GB card never holds both.
The 128 GB of system RAM is what lets the 14B Wan models run on a 12 GB card.
