# Unreal Engine guide pictures

Unreal Engine is free for this channel: Epic charges no royalty on linear content such as videos, YouTube ad
money included (paid seats only start at US$1M revenue a year). The script only uses Unreal's built-in shapes, so
there is nothing else to license. (Research "AI film director storyboard pipeline".)

## What it does for you

Unreal builds a rough 3D set for every place in the video (a radio studio, a main street, a courtroom...) from
plain blocks, photographs it from six angles (wide, medium, low, high, close, side), and the Studio paints each
storyboard picture in the video's style on top of that layout. The same place then looks the same from shot to
shot, and the camera angles really change. You don't build anything or move any cameras yourself.

## How to use it (v0.9.3, 2026-11-01)

Everything happens from the Studio. You don't need to open Unreal, tick plugins or run anything in it.

1. **Once:** Storyboard page > **Unreal guides...** > **Download it** (the guide model, about 2 GB, into ComfyUI's
   `models\model_patches` folder). `Update Studio.cmd` also gets it. Then restart ComfyUI. If the window says
   ComfyUI is too old, update ComfyUI (portable: `update\update_comfyui.bat`; desktop app: Manage > Update).
2. **Each video:** press **Make pictures** once (so the video has its list of places), then **Unreal guides...** >
   **Make guides with Unreal**. Unreal opens by itself with a small project of the Studio's own
   (`F:\AI\fof-data\unreal\FoFGuides`), builds and photographs each place, and closes by itself. Leave it be.
   The first time takes 10-20 minutes while Unreal prepares its shaders; after that a few minutes. The window
   shows what it's doing.
3. Press **Make pictures** again. The guides are used by themselves.

If it fails, the window says why in plain words and shows the lines from Unreal's own log. Everything the
script did is in `F:\AI\fof-data\unreal\out\run-log.txt`, and Unreal's whole log in
`F:\AI\fof-data\unreal\unreal-editor.log`. Send those if the reason doesn't make sense.

## Why nothing happened the first time (2026-11-01)

Unreal was in Play mode (the green Play button had been pressed; the Outliner said "Untitled (Play In Editor)").
In Play mode Unreal hides a script's progress bar and won't add anything to the level, and the script's errors
only went to Unreal's Output Log. The script now checks for Play mode and says so, writes its own log, keeps
going when one camera fails, and the Studio runs Unreal itself so Play mode can't happen.

## If something goes wrong

- *"Couldn't find Unreal Engine 5":* Settings > paths > unreal_editor: paste Unreal's folder (for example
  `C:\Program Files\Epic Games\UE_5.6`).
- *"Couldn't find ComfyUI's models folder":* Settings > paths > comfyui_models: paste the folder that has
  checkpoints, vae, loras in it.
- *A place looks wrong (a courtroom built as an office):* the script picks the set from the place's name. Rename
  the place in the bible, or add `"kind": "hall"` to it (studio, hall, street, warehouse, kitchen, crowd,
  outdoors, office), and make the guides again.
- *By hand, if you ever want to:* the script is `F:\AI\fof-data\unreal\fof_unreal_guides.py`. In Unreal make
  sure the red Stop button isn't showing (not in Play mode), then Tools > Execute Python Script... > that file.
- *You'd rather draw your own:* any picture dropped in `control-maps\<place>\` is used too, and pictures in
  `<episode>\control\<scene id>\` are used for that one scene first.
