# Unreal Engine guide pictures

Added 2026-10-31. Unreal Engine is free for this channel: Epic charges no royalty on linear content such as
videos, YouTube ad money included (paid seats only start at US$1M revenue a year). From UE 5.6, MetaHuman is
covered by the same licence. Mixamo characters and animations are royalty-free for films. (Research "AI film
director storyboard pipeline"; check MetaHuman's terms before ever training a LoRA on MetaHuman renders.)

## What it does

Block out a place once in Unreal (simple shapes, a mannequin, saved cameras), render guide passes, and the Studio
paints each storyboard picture in the video's style ON that layout. The same street, studio or courtroom then
keeps the same layout from shot to shot, and a figure holds a clean, readable pose that animates well.

## Steps

1. Open the video's `bible.json` (in the episode folder) and note the place ids, e.g. `radio_shop`.
2. In Unreal, build a rough version of the place. Put a mannequin where a person stands (a Mixamo pose is fine).
   Save several cameras (wide, medium, close, low angle...).
3. From each camera render 1344 x 768 pictures, any of:
   - **depth** (Movie Render Queue → a Scene Depth / World Depth pass, white near, black far),
   - **outlines** (a post-process outline material, or render normally and the outline is found from it),
   - **pose**: render the mannequin, then in ComfyUI run the DWPose preprocessor on that render.
4. Put them in `F:\AI\fof-data\control-maps\<place id>\` (e.g. `control-maps\radio_shop\cam1-depth.png`).
   For one scene only, use `<episode folder>\control\<scene id>\` instead; it wins over the place's folder.
5. Press Make pictures. Each picture of that place takes the next guide in turn (sorted by name), so your
   cameras become the shot angles. The shot's tooltip shows which guide it used.

## What it needs in ComfyUI

`models/model_patches/Z-Image-Turbo-Fun-Controlnet-Union.safetensors` (pose, depth, canny/lineart, HED, MLSD)
and the workflow `comfy_workflows/zimage_turbo_control.json`. If ComfyUI rejects that workflow, the picture is
painted from the words alone and the log says so. Settings → comfyui → control_strength (0.65): lower lets
the painter wander, higher follows the guide strictly.

## Not used

- **Owlbert** isn't human, so pose detectors don't see him; he's always placed from his real artwork.
- **Real people**: never posed from photos; caricatures come only from approved designs.
- **Our own IP-Adapter**: not realistic. The original took about 10 million images and 8 data-centre GPUs, for
  a smaller model. Guide pictures, edit models (Qwen-Image-Edit-2511, FLUX.2 klein 4B: Apache-2.0; never klein
  9B, which is non-commercial) and LoRAs do the same job for free.
