"""Followers or Facts Studio: guide pictures from Unreal Engine (made by the Studio; you don't need to edit this).

What it does, by itself:
  1. reads the job the Studio wrote (the places in your video: a radio studio, a main street, a courthouse...);
  2. for each place builds a rough set from Unreal's built-in shapes (walls, desks, buildings, benches, trees,
     a few stand-in figures) in the open level, with its own lights;
  3. puts six cameras around it (wide, medium, low angle, high angle, close, side) and captures a DEPTH picture and a
     plain grey LAYOUT picture from each;
  4. saves them for the Studio, then removes everything it added. Your level is left as it was.
The Studio turns them into the guide pictures the painter follows (so a place keeps the same layout in every shot).

Normally the Studio runs it for you (Storyboard > Unreal guides... > Make guides with Unreal): it opens Unreal,
runs this, and Unreal closes by itself. By hand: in any project, make sure the red Stop button isn't showing
(not in Play mode), then Tools > Execute Python Script... and pick this file. Everything it does is written to
run-log.txt next to the pictures.
"""

import json
import math
import os
import struct
import time
import traceback

import unreal

JOB = r"{{JOB_PATH}}"           # filled in by the Studio
WIDTH, HEIGHT = 672, 384         # half the painting size; the Studio scales them up

CUBE = "/Engine/BasicShapes/Cube.Cube"
SPHERE = "/Engine/BasicShapes/Sphere.Sphere"
CYLINDER = "/Engine/BasicShapes/Cylinder.Cylinder"
CONE = "/Engine/BasicShapes/Cone.Cone"
PLANE = "/Engine/BasicShapes/Plane.Plane"


# ---------------------------------------------------------------- Unreal helpers (UE 5.0 - 5.6)
def _actors():
    try:
        return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    except Exception:
        return None


def _world():
    try:
        return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    except Exception:
        return unreal.EditorLevelLibrary.get_editor_world()


def _spawn(cls, loc, rot=(0, 0, 0)):
    location = unreal.Vector(*loc)
    rotation = unreal.Rotator(roll=rot[0], pitch=rot[1], yaw=rot[2])
    sub = _actors()
    a = (sub.spawn_actor_from_class(cls, location, rotation) if sub
         else unreal.EditorLevelLibrary.spawn_actor_from_class(cls, location, rotation))
    if a is None:
        raise RuntimeError(f"Unreal refused to add a {cls.__name__} to the level (is the Play button on?)")
    return a


def _destroy(actor):
    sub = _actors()
    if sub:
        sub.destroy_actor(actor)
    else:
        unreal.EditorLevelLibrary.destroy_actor(actor)


MESHES = {}
LOG = []          # everything that happened, saved next to the pictures as run-log.txt for the Studio to show


def note(text):
    line = time.strftime("%H:%M:%S ") + str(text)
    LOG.append(line)
    try:
        unreal.log("Followers or Facts: " + str(text))
    except Exception:
        pass


def save_log(out_root):
    try:
        os.makedirs(out_root, exist_ok=True)
        with open(os.path.join(out_root, "run-log.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(LOG) + "\n")
    except Exception:
        pass


def _mesh(path):
    if path not in MESHES:
        m = unreal.load_asset(path)
        if m is None:
            try:
                m = unreal.EditorAssetLibrary.load_asset(path)
            except Exception:
                m = None
        if m is None:
            raise RuntimeError(f"Unreal couldn't load its built-in shape {path}")
        MESHES[path] = m
    return MESHES[path]


def playing():
    """True while the green Play button is on (Play In Editor): Unreal won't add anything to the level then."""
    for check in (lambda: unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor(),
                  lambda: bool(unreal.EditorLevelLibrary.get_pie_worlds(False)),
                  lambda: bool(unreal.EditorLevelLibrary.get_game_world())):
        try:
            return bool(check())
        except Exception:
            continue
    return False


class Set:
    """Everything spawned for one place, so it can all be removed afterwards."""

    def __init__(self):
        self.actors = []

    def shape(self, mesh, x, y, z, sx, sy, sz, yaw=0.0):
        """A built-in shape; sizes in metres (the basic shapes are 1 m across), position of its centre in metres."""
        a = _spawn(unreal.StaticMeshActor, (x * 100, y * 100, z * 100), (0, 0, yaw))
        a.static_mesh_component.set_static_mesh(_mesh(mesh))
        a.set_actor_scale3d(unreal.Vector(sx, sy, sz))
        self.actors.append(a)
        return a

    def box(self, x, y, z, sx, sy, sz, yaw=0.0):        # z = floor level of the box's base
        return self.shape(CUBE, x, y, z + sz / 2, sx, sy, sz, yaw)

    def figure(self, x, y, yaw=0.0, sitting=False):
        """A stand-in person: body, head and shoulders (seen from behind or far away in the paintings)."""
        h = 1.25 if sitting else 1.75
        self.shape(CYLINDER, x, y, h * 0.42, 0.42, 0.3, h * 0.84 / 1.0, yaw)
        self.shape(SPHERE, x, y, h * 0.92, 0.24, 0.24, 0.26)
        self.shape(CUBE, x, y, h * 0.76, 0.5, 0.22, 0.12, yaw)

    def lights(self, focus=(0, 0, 1.5)):
        """A sun and sky for outdoor places, and a lamp in front of the action so rooms with a ceiling are lit."""
        sun = _spawn(unreal.DirectionalLight, (0, 0, 800), (0, -45, 35))
        sky = _spawn(unreal.SkyLight, (0, 0, 600))
        lamp = _spawn(unreal.PointLight, (focus[0] * 100, (focus[1] - 1.5) * 100, 250))
        try:
            lamp.point_light_component.set_editor_property("attenuation_radius", 3000.0)
            lamp.point_light_component.set_editor_property("intensity", 20000.0)
        except Exception:
            pass
        try:
            sky.light_component.recapture_sky()
        except Exception:
            pass
        self.actors += [sun, sky, lamp]

    def clear(self):
        for a in self.actors:
            try:
                _destroy(a)
            except Exception:
                pass
        self.actors = []


# ---------------------------------------------------------------- the sets, by kind of place
def room(s, w=8, d=7, h=3.2, windows=True):
    s.box(0, 0, -0.1, w, d, 0.1)                                     # floor
    s.box(0, d / 2, 0, w, 0.15, h)                                   # back wall
    s.box(-w / 2, 0, 0, 0.15, d, h)                                  # left wall
    s.box(w / 2, 0, 0, 0.15, d, h)                                   # right wall
    if windows:
        s.box(-w / 2 + 0.1, 0.5, 1.0, 0.1, 1.6, 1.2)                 # a window recess
    s.box(0, 0, h, w, d, 0.1)                                        # ceiling


def studio(s):
    room(s, 7, 6, 3, windows=False)
    s.box(0, 1.2, 0, 2.4, 0.9, 0.75)                                 # desk
    s.shape(CYLINDER, -0.4, 1.0, 0.95, 0.06, 0.06, 0.4)              # microphone stand
    s.shape(SPHERE, -0.4, 1.0, 1.2, 0.14, 0.14, 0.2)                 # microphone
    s.box(2.3, 2.6, 0, 1.6, 0.4, 2.0)                                # shelves of equipment
    s.box(-2.4, 2.6, 0, 1.2, 0.5, 1.4)                               # rack
    s.figure(0, 1.9, 180, sitting=True)                              # the host, from behind
    s.box(0, 2.9, 1.2, 2.2, 0.05, 1.0)                               # a big blank panel on the wall


def office(s):
    room(s)
    s.box(0.5, 1.0, 0, 2.0, 1.0, 0.76)                               # table
    for x in (-0.2, 1.2):
        s.box(x, 0.2, 0, 0.5, 0.5, 0.45)                             # chairs
        s.box(x, -0.05, 0.45, 0.5, 0.06, 0.5)
    s.box(-3.3, 3.0, 0, 1.0, 0.45, 2.2)                              # shelves
    s.box(3.0, 3.0, 0, 1.4, 0.6, 1.0)                                # cabinet
    s.box(0.5, 1.0, 0.76, 0.6, 0.4, 0.05)                            # papers on the table
    s.figure(-2.0, -0.5, 30)


def street(s):
    s.box(0, 0, -0.1, 60, 60, 0.1)                                   # ground
    s.box(0, 0, -0.05, 8, 60, 0.06)                                  # road
    for side in (-1, 1):
        for i, (w, h) in enumerate([(6, 7), (5, 10), (7, 6), (6, 12), (5, 8), (6, 7)]):
            s.box(side * 9, -18 + i * 7, 0, 6, w, h)                 # shop fronts and buildings
            s.box(side * 5.9, -18 + i * 7, 2.6, 0.3, w * 0.8, 0.6)   # awnings
        for i in range(5):
            s.shape(CYLINDER, side * 4.6, -16 + i * 8, 2.0, 0.15, 0.15, 4.0)   # lamp posts
    for x, y in ((-1.5, 2), (1.0, 4), (2.5, -3)):
        s.figure(x, y, 90)


def hall(s):
    """A courtroom, hearing room or chamber."""
    room(s, 16, 14, 7, windows=False)
    s.box(0, 5.0, 0, 6, 1.6, 1.4)                                    # the raised bench
    s.box(0, 5.6, 1.4, 6, 0.6, 1.0)
    for i in range(4):
        for side in (-1, 1):
            s.box(side * 3.5, -1 - i * 1.6, 0, 4.5, 0.5, 0.9)        # rows of benches
    for x in (-7, -3.5, 3.5, 7):
        s.shape(CYLINDER, x, 6.5, 3.5, 0.8, 0.8, 7.0)                # columns
    for x in (-3, 3):
        s.box(x, 2.5, 0, 2.5, 1.0, 0.8)                              # tables
    s.figure(-3, 1.6, 180, sitting=True)
    s.figure(3.5, -2.6, 180, sitting=True)


def warehouse(s):
    s.box(0, 0, -0.1, 40, 40, 0.1)
    s.box(0, 15, 0, 40, 0.3, 9)
    for i in range(5):
        for j in range(3):
            h = 1.2 + ((i + j) % 3) * 1.1
            s.box(-10 + i * 5, -2 + j * 5, 0, 2.4, 2.4, h)           # stacks of crates
    s.figure(2, -8, 0)


def kitchen(s):
    room(s, 6, 5, 2.8)
    s.box(0, 2.1, 0, 4.5, 0.65, 0.9)                                 # counter
    s.box(0, 2.3, 1.5, 4.5, 0.35, 0.7)                               # cupboards
    s.box(0, 0, 0, 1.4, 1.0, 0.75)                                   # table
    s.box(0.2, 0.1, 0.75, 0.35, 0.2, 0.25)                           # a radio on the table
    s.figure(-0.9, -0.5, 30, sitting=True)


def outdoors(s):
    s.box(0, 0, -0.1, 120, 120, 0.1)
    for x, y, r in ((-30, 40, 18), (25, 55, 24), (60, 30, 14)):
        s.shape(SPHERE, x, y, -r * 0.2, r * 2, r * 2, r)             # hills, poking up
    for i in range(10):
        x, y = -20 + (i * 7) % 40, 8 + (i * 13) % 30
        s.shape(CYLINDER, x, y, 1.5, 0.35, 0.35, 3.0)                # trunks
        s.shape(SPHERE, x, y, 4.2, 3.0, 3.0, 3.4)                    # crowns
    s.box(0, 0, -0.05, 4, 120, 0.06)                                 # a road
    s.figure(1.0, 3.0, 90)


def crowd(s):
    """A rally, a fair or a meeting: a stage and people seen from behind."""
    s.box(0, 0, -0.1, 50, 50, 0.1)
    s.box(0, 9, 0, 8, 4, 1.1)                                        # stage
    s.box(0, 10.8, 1.1, 8, 0.2, 4)                                   # backdrop
    s.figure(0, 9, 180)                                              # the speaker
    for row in range(5):
        for k in range(7):
            s.figure(-6 + k * 2 + (row % 2) * 0.9, 4 - row * 1.6, 0)


KINDS = [
    ("studio", ("studio", "radio", "broadcast", "newsroom", "station", "booth", "podcast", "tv")),
    ("hall", ("court", "courthouse", "senate", "congress", "hearing", "chamber", "capitol", "hall", "church")),
    ("street", ("street", "town", "city", "downtown", "storefront", "shop front", "avenue", "main")),
    ("warehouse", ("warehouse", "factory", "plant", "depot", "storage", "bunker", "silo")),
    ("kitchen", ("kitchen", "home", "house", "living", "farmhouse", "cabin")),
    ("crowd", ("rally", "fair", "crowd", "stadium", "convention", "protest", "meeting", "stage")),
    ("outdoors", ("field", "farm", "road", "hill", "forest", "desert", "mountain", "park", "outdoor", "countryside")),
    ("office", ("office", "room", "shop", "store", "library", "study", "lab", "bank", "clinic")),
]
BUILD = {"studio": studio, "hall": hall, "street": street, "warehouse": warehouse, "kitchen": kitchen,
         "crowd": crowd, "outdoors": outdoors, "office": office}
# where the action is (metres) and how far the cameras stand back, per kind of place
FOCUS = {"studio": ((0, 1.4, 1.1), 3.2), "hall": ((0, 2.5, 1.4), 8.0), "street": ((0, 0, 1.6), 9.0),
         "warehouse": ((0, 2, 1.6), 11.0), "kitchen": ((0, 0.5, 1.0), 2.8), "crowd": ((0, 5, 1.6), 10.0),
         "outdoors": ((1, 3, 1.6), 12.0), "office": ((0.5, 1.0, 1.0), 3.4)}


def kind_of(place):
    text = " ".join(str(place.get(k, "")) for k in ("kind", "name", "architecture", "props", "id")).lower()
    if place.get("kind") in BUILD:
        return place["kind"]
    for kind, words in KINDS:
        if any(w in text for w in words):
            return kind
    return "office"


# ---------------------------------------------------------------- the cameras and the captures
# The sets are open at the front (toward -y, where rooms have no wall), so the cameras stand in front, spread
# left to right: 270 degrees is straight in front of the action.
CAMERAS = [   # name, angle around the focus (degrees), distance (x the place's distance), height (m), field of view
    ("wide", 255, 1.0, 1.7, 70), ("medium", 275, 0.55, 1.5, 55), ("low", 290, 0.6, 0.4, 60),
    ("high", 240, 0.9, 4.5, 60), ("close", 268, 0.3, 1.3, 40), ("side", 320, 0.7, 1.6, 55),
]


TARGETS = {}


def _target(fmt):
    """Two picture targets made once and reused for every camera (one for depth, one for colour)."""
    key = str(fmt)
    if key not in TARGETS:
        TARGETS[key] = unreal.RenderingLibrary.create_render_target2d(_world(), WIDTH, HEIGHT, fmt)
    return TARGETS[key]


HOW = {}          # which way of getting the pixels out worked, found on the first camera and then reused


def _as_pixels(result):
    """Unreal versions differ in what read_render_target_raw gives back: a list of colours, a (ok, list)
    pair, or nothing at all (5.8.4 gave None, Dave's run 2026-11-01). Returns the list, or None."""
    if result is None:
        return None
    if isinstance(result, tuple):
        for part in result:
            if isinstance(part, (list, tuple)) and len(part) == WIDTH * HEIGHT:
                return part
        return None
    try:
        return result if len(result) == WIDTH * HEIGHT else None
    except TypeError:
        return None


def _exported(out_dir, stem):
    for f in sorted(os.listdir(out_dir)):
        if f.startswith(stem + ".") and not f.endswith((".bin", ".json")) and \
                os.path.getsize(os.path.join(out_dir, f)) > 0:
            return f
    return None


def save_picture(rt, out_dir, stem, ext, raw, for_file=None):
    """Save a captured picture next to the others and return its file name. Two ways, the first that works:
    1. read the pixels into Python and write them raw (exact depth in centimetres);
    2. let Unreal write the file itself (export_render_target: .hdr for depth, .png for colour). It never adds
       the extension itself; `for_file` gives the picture in the format that file needs."""
    first = stem.split(".")[-1] not in HOW
    kind = stem.split(".")[-1]
    if raw and HOW.get(kind) in (None, "read"):     # colour goes straight to a .png (faster and just as exact)
        try:
            if raw:
                px = _as_pixels(unreal.RenderingLibrary.read_render_target_raw(_world(), rt, False))
            else:
                px = _as_pixels(unreal.RenderingLibrary.read_render_target(_world(), rt, True))
            if first:
                note(f"  ({kind}: reading pixels {'worked' if px else 'gave nothing'})")
            if px:
                path = os.path.join(out_dir, stem + ".bin")
                with open(path, "wb") as f:
                    if raw:
                        f.write(struct.pack(f"<{len(px)}f", *[p.r for p in px]))
                    else:
                        f.write(bytes(v for p in px for v in (p.r, p.g, p.b)))
                HOW[kind] = "read"
                return stem + ".bin"
        except Exception as exc:
            if first:
                note(f"  ({kind}: reading pixels failed: {exc})")
    try:
        if for_file:
            rt = for_file()
        unreal.RenderingLibrary.export_render_target(_world(), rt, out_dir, stem + ext)
    except Exception as exc:
        raise RuntimeError(f"Unreal couldn't save the {kind} picture ({exc})")
    got = _exported(out_dir, stem)
    if not got:
        raise RuntimeError(f"Unreal didn't save the {kind} picture (neither way worked)")
    if first or HOW.get(kind) != "export":
        note(f"  ({kind}: Unreal saved the picture itself as {got})")
    HOW[kind] = "export"
    return got


def capture(s, cam, focus, dist, out_dir):
    name, angle, far, height, fov = cam
    fx, fy, fz = focus
    a = math.radians(angle)
    cx, cy = fx + math.cos(a) * dist * far, fy + math.sin(a) * dist * far
    cz = max(0.3, height if name != "high" else height * (dist / 6.0))
    dx, dy, dz = fx - cx, fy - cy, fz - cz
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    cap = _spawn(unreal.SceneCapture2D, (cx * 100, cy * 100, cz * 100), (0, pitch, yaw))
    try:
        comp = cap.capture_component2d
        comp.set_editor_property("fov_angle", fov)
        comp.set_editor_property("capture_every_frame", False)
        comp.set_editor_property("capture_on_movement", False)
        try:   # only the set we built, never whatever else is in your level
            comp.set_editor_property("primitive_render_mode",
                                     unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
            comp.set_editor_property("show_only_actors", list(s.actors))
        except Exception:
            pass
        # depth: how far each point is, in centimetres
        # (RGBA32F, not R32F: Unreal only hands pixels back for RGBA8 / RGBA16F / RGBA32F, and for anything
        # else quietly returns nothing - Unreal 5.8.4 on Dave's PC, 2026-11-01)
        rt = _target(unreal.TextureRenderTargetFormat.RTF_RGBA32F)
        comp.set_editor_property("texture_target", rt)
        comp.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_SCENE_DEPTH)
        comp.capture_scene()
        comp.capture_scene()          # the second one is after any shaders the first needed have finished

        def half_float():             # for saving to a file, Unreal writes a .hdr only from an RGBA16F picture
            rt16 = _target(unreal.TextureRenderTargetFormat.RTF_RGBA16F)
            comp.set_editor_property("texture_target", rt16)
            comp.capture_scene()
            return rt16
        depth_file = save_picture(rt, out_dir, f"{name}.depth", ".hdr", raw=True, for_file=half_float)
        # layout: the plain grey set, lit, for the outlines
        layout_file = None
        try:   # optional: the outlines also come from the depth, so a dark colour capture doesn't matter
            rt2 = _target(unreal.TextureRenderTargetFormat.RTF_RGBA8)
            comp.set_editor_property("texture_target", rt2)
            comp.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            comp.capture_scene()
            comp.capture_scene()
            layout_file = save_picture(rt2, out_dir, f"{name}.layout", ".png", raw=False)
        except Exception as exc:
            note(f"  {name}: no layout picture ({exc}); the depth one is enough")
        with open(os.path.join(out_dir, f"{name}.json"), "w") as f:
            json.dump({"width": WIDTH, "height": HEIGHT, "camera": name, "fov": fov,
                       "depth_file": depth_file, "layout_file": layout_file,
                       "position_m": [cx, cy, cz], "yaw": yaw, "pitch": pitch}, f)
    finally:
        _destroy(cap)


def main():
    with open(JOB, encoding="utf-8") as f:
        job = json.load(f)
    out_root = job["out"]
    auto = bool(job.get("auto"))           # started by the Studio: no message boxes, Unreal closes when done
    places = job["places"]
    note(f"Started: {len(places)} place(s), Unreal {unreal.SystemLibrary.get_engine_version()}")
    save_log(out_root)
    if playing():
        msg = ("Unreal is in Play mode (the green Play button was pressed), and nothing can be added to the "
               "level while it plays. Press the red Stop button at the top, then run this script again.")
        note("STOPPED: " + msg)
        save_log(out_root)
        if not auto:
            unreal.EditorDialog.show_message("Followers or Facts", msg, unreal.AppMsgType.OK)
        return
    total = len(places) * len(CAMERAS)
    done_places, problems = [], []
    with unreal.ScopedSlowTask(total, "Followers or Facts: building sets and capturing guide pictures") as task:
        task.make_dialog(True, True)
        for place in places:
            name = place.get("name") or place["id"]
            kind = kind_of(place)
            out_dir = os.path.join(out_root, place["id"])
            os.makedirs(out_dir, exist_ok=True)
            note(f"{name}: building a {kind} set")
            s = Set()
            got = 0
            try:
                BUILD[kind](s)
                focus, dist = FOCUS[kind]
                s.lights(focus)
                for cam in CAMERAS:
                    if task.should_cancel():
                        raise KeyboardInterrupt
                    task.enter_progress_frame(1, f"{name}: {cam[0]} camera")
                    try:
                        capture(s, cam, focus, dist, out_dir)
                        got += 1
                        note(f"  {cam[0]} camera: saved")
                    except Exception as exc:
                        problems.append(f"{name} / {cam[0]}: {exc}")
                        note(f"  {cam[0]} camera FAILED: {exc}\n{traceback.format_exc()}")
                    save_log(out_root)
                with open(os.path.join(out_dir, "place.json"), "w") as f:
                    json.dump({**place, "built_as": kind}, f)
                if got:
                    done_places.append(f"{name} ({kind}, {got} angles)")
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                problems.append(f"{name}: {exc}")
                note(f"{name} FAILED: {exc}\n{traceback.format_exc()}")
            finally:
                s.clear()
                save_log(out_root)
    with open(os.path.join(out_root, "done.json"), "w") as f:
        json.dump({"places": done_places, "problems": problems, "cameras": [c[0] for c in CAMERAS]}, f)
    note(f"Finished: {len(done_places)} place(s) done, {len(problems)} problem(s)")
    save_log(out_root)
    if not auto:
        msg = ("Done! Guide pictures made for:\n- " + "\n- ".join(done_places or ["(none)"])
               + ("\n\nProblems:\n- " + "\n- ".join(problems[:8]) if problems else "")
               + "\n\nGo back to the Studio and press Make pictures (it brings them in by itself).")
        try:
            unreal.EditorDialog.show_message("Followers or Facts", msg, unreal.AppMsgType.OK)
        except Exception:
            pass


try:
    main()
except KeyboardInterrupt:
    note("Cancelled. Nothing was left in your level.")
except Exception as exc:
    note(f"ERROR: {exc}\n{traceback.format_exc()}")
    try:
        with open(JOB, encoding="utf-8") as f:
            _auto = bool(json.load(f).get("auto"))
    except Exception:
        _auto = False
    if not _auto:
        try:
            unreal.EditorDialog.show_message("Followers or Facts: something went wrong",
                                             f"{exc}\n\nThe details are in run-log.txt next to the pictures.",
                                             unreal.AppMsgType.OK)
        except Exception:
            pass
finally:
    try:
        with open(JOB, encoding="utf-8") as f:
            save_log(json.load(f)["out"])
    except Exception:
        pass
