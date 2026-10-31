# ComfyUI workflow templates

The Studio talks to ComfyUI through these files. Each is a ComfyUI workflow in
**API format** where the values the Studio fills in are written as placeholders.

| File | Used by | Placeholders |
|------|---------|--------------|
| `zimage_turbo_t2i.json` | Images stage | `{{PROMPT}}` `{{SEED}}` `{{WIDTH}}` `{{HEIGHT}}` `{{FILENAME_PREFIX}}` |
| `zimage_turbo_control.json` | Images stage, when a scene's place has Unreal guide pictures (docs/UNREAL.md) | `{{PROMPT}}` `{{SEED}}` `{{WIDTH}}` `{{HEIGHT}}` `{{IMAGE}}` `{{STRENGTH}}` `{{FILENAME_PREFIX}}` |
| `wan22_i2v_lightning.json` | Animation stage | `{{IMAGE}}` `{{PROMPT}}` `{{SEED}}` `{{WIDTH}}` `{{HEIGHT}}` `{{FRAMES}}` `{{FPS}}` `{{FILENAME_PREFIX}}` |
| `acestep_music.json` | Music stage | `{{TAGS}}` `{{LYRICS}}` `{{SECONDS}}` `{{SEED}}` `{{FILENAME_PREFIX}}` |

## First time: check each template loads

These were written by hand from ComfyUI's own example workflows. Node names do
change between ComfyUI versions, so test each one once:

1. Start ComfyUI.
2. `python -m fofstudio doctor` — it checks the files exist.
3. In the app, run the Images stage on a test episode. If ComfyUI rejects the
   workflow, the error names the node and the missing model or input.

## Using your own workflow instead

Any workflow you've built and like can replace a template:

1. In ComfyUI: **Settings → enable Dev mode**, then **Workflow → Export (API)**.
2. Open the exported JSON in a text editor.
3. Replace the values the Studio should control with placeholders, keeping the
   quotes: `"text": "a spacecraft over Europa"` becomes `"text": "{{PROMPT}}"`,
   `"seed": 12345` becomes `"seed": "{{SEED}}"`. Number placeholders are turned
   back into numbers automatically.
4. Save it in this folder and point Settings → comfyui → `image_workflow`
   (or `video_workflow`, `music_workflow`) at it.

## Why these models

All three are free for a monetized channel:

- **Z-Image Turbo** — Apache-2.0, already working on your PC, 8 steps.
- **Wan 2.2 I2V 14B + Lightning LoRA** — Apache-2.0, about 5–6 minutes per
  5-second clip on an RTX 3060 12 GB (measured by another 3060 owner; yours may differ).
- **ACE-Step** — Apache-2.0 (v1) / MIT (v1.5), instrumental beds in under 4 GB.

**Not used:** MiniMax H3 (its free licence excludes the US, outputs included),
XTTS and F5-TTS (non-commercial), FLUX.1-dev and FLUX.2 klein 9B (non-commercial).
