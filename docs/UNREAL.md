# Unreal Engine guide pictures

Unreal Engine is free for this channel: Epic charges no royalty on linear content such as videos, YouTube ad
money included (paid seats only start at US$1M revenue a year). The script only uses Unreal's built-in shapes, so
there is nothing else to license. (Research "AI film director storyboard pipeline".)

## What it does for you

Unreal builds a rough 3D set for every place in the video (a radio studio, a main street, a courtroom...) from
plain blocks, photographs it from six angles (wide, medium, low, high, close, side), and the Studio paints each
storyboard picture in the video's style on top of that layout. The same place then looks the same from shot to
shot, and the camera angles really change. You don't build anything or move any cameras yourself.

## The three steps (2026-10-31, v0.9.2)

1. **In the Studio:** Storyboard page > **Unreal guides...** > **Make the Unreal job and open its folder**.
   (Press Make pictures once first, so the video has its list of places.)
2. **In Unreal Engine 5** (any project; a new empty "Blank" project is fine):
   - *First time only:* Edit > Plugins > search **Python** > tick **Python Editor Script Plugin** > restart.
   - Tools > **Execute Python Script...** > pick **fof_unreal_guides.py** in the folder step 1 opened
     (`F:\AI\fof-data\unreal\`).
   - A progress bar shows while it works (a minute or two per place). It removes everything it added and says
     **Done**. You don't need to save anything in Unreal.
3. **Back in the Studio:** press **Make pictures**. The guides come in by themselves (or press
   **Bring in what Unreal made** in the same window to check).

The guide pictures land in `F:\AI\fof-data\control-maps\<place>\` (`wide-depth.png`, `wide-lines.png`, ...).
They need the guide model in ComfyUI (`Z-Image-Turbo-Fun-Controlnet-Union`, see docs/MODELS.md). Without it the
Studio says so in the log and paints as before.

## If something goes wrong

- *"Execute Python Script" isn't in the Tools menu:* the Python plugin isn't on (step 2, first bullet).
- *Unreal shows a red error in the Output Log:* copy the lines and send them; the Studio isn't affected.
- *A place looks wrong (a courtroom built as an office):* the script picks the set from the place's name. Rename
  the place in the bible, or add `"kind": "hall"` to it (studio, hall, street, warehouse, kitchen, crowd,
  outdoors, office), and run steps 1-2 again.
- *You'd rather draw your own:* any picture dropped in `control-maps\<place>\` is used too, and pictures in
  `<episode>\control\<scene id>\` are used for that one scene first.
