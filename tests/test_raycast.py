"""Run inside Blender: blender --background --python tests/test_raycast.py

Regression test for the hover flicker: the addon's own preview/result meshes
sit on top of (or slightly in front of) the surface being hovered, so the
picking raycast must look straight THROUGH them. Before the fix, the ray hit
"RetopPreview", concluded "no patch here", deleted the preview, then hit the
source mesh again on the next mouse move and rebuilt it -- flickering as long
as the cursor kept moving over a patch.
"""
import os
import sys
import importlib

# Make the test runnable from any checkout: the addon package is the parent
# directory of tests/, so put its parent on sys.path and import it by folder
# name (the hyphen means it can only be imported via import_module).
_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy
import mathutils

pr = importlib.import_module(os.path.basename(_ADDON_DIR))

FAILURES = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


try:
    pr.unregister()
except Exception:
    pass
pr.register()

# Start from an empty scene: the default startup Cube sits at the origin and
# would legitimately occlude the ray (a real occluder is *supposed* to block
# picking), which has nothing to do with what this test is checking.
for _obj in list(bpy.data.objects):
    bpy.data.objects.remove(_obj, do_unlink=True)


def make_plane(name, z, face_id=None):
    verts = [(-1, -1, z), (1, -1, z), (1, 1, z), (-1, 1, z)]
    tris = [(0, 1, 2), (0, 2, 3)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], tris)
    mesh.update()
    if face_id is not None:
        mesh["groups"] = [0, 6]
        mesh["face_ids"] = [face_id]
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


# Source CAD patch at z=0, and the addon's own preview sitting in front of it
# at z=0.5 (as Preview Offset would place it).
source = make_plane("PlasticitySource", 0.0, face_id=777)
preview = make_plane(pr.mesh_build.PREVIEW_OBJ_NAME, 0.5)
result = make_plane("PlasticitySource_Retop", 0.25)

bpy.context.view_layer.update()

ray_origin = mathutils.Vector((0.0, 0.0, 5.0))
ray_direction = mathutils.Vector((0.0, 0.0, -1.0))

# Sanity: a naive cast really does hit our own scaffolding first, i.e. this
# test would catch a regression rather than passing vacuously.
depsgraph = bpy.context.evaluated_depsgraph_get()
hit, _loc, _n, _i, naive_obj, _m = bpy.context.scene.ray_cast(depsgraph, ray_origin, ray_direction)
check("naive raycast hits the addon's own preview first (flicker precondition)",
      hit and naive_obj is not None and naive_obj.name == pr.mesh_build.PREVIEW_OBJ_NAME,
      f"got {naive_obj.name if naive_obj else 'nothing'}")

obj, face_id, hit_dist = pr.operators._raycast_patch_ray(bpy.context, ray_origin, ray_direction)
check("filtered raycast sees through preview/result to the source patch",
      obj is source, f"got {obj.name if obj else 'None'}")
check("filtered raycast returns the right face id", face_id == 777, f"got {face_id}")

# Hidden objects must still be skipped (Local View '/' fix must not regress).
source.hide_viewport = True
bpy.context.view_layer.update()
obj_hidden, face_hidden, _d = pr.operators._raycast_patch_ray(bpy.context, ray_origin, ray_direction)
check("hidden source is not pickable", obj_hidden is None, f"got {obj_hidden.name if obj_hidden else 'None'}")
source.hide_viewport = False
bpy.context.view_layer.update()

# Repeated casts over the same spot must be stable (no alternating result,
# which is what the flicker looked like frame to frame).
results = []
for _ in range(5):
    o, f, _dd = pr.operators._raycast_patch_ray(bpy.context, ray_origin, ray_direction)
    results.append((o.name if o else None, f))
check("repeated casts are stable (no flicker)", len(set(results)) == 1, f"got {set(results)}")

# --- Picker Settings: Pick Max Distance (0 = unlimited). The source patch is
# 5 units from the ray origin. ---
_state = bpy.context.scene.plasticity_retop
check("hit distance is reported", hit_dist is not None and abs(hit_dist - 5.0) < 1e-4, f"got {hit_dist}")

_state.pick_max_distance = 2.0
o_near, f_near, _dn = pr.operators._raycast_patch_ray(bpy.context, ray_origin, ray_direction)
check("pick_max_distance rejects hits beyond the limit", o_near is None,
      f"got {o_near.name if o_near else 'None'}")

_state.pick_max_distance = 10.0
o_far, f_far, _df = pr.operators._raycast_patch_ray(bpy.context, ray_origin, ray_direction)
check("pick_max_distance allows hits within the limit", o_far is source,
      f"got {o_far.name if o_far else 'None'}")

_state.pick_max_distance = 0.0  # back to unlimited for the rest of the test

# ---------------------------------------------------------------------------
# Overlapping Plasticity surfaces: two near-coincident patches. Whichever one
# scene.ray_cast happens to report can alternate with sub-epsilon ray changes,
# so the modal picker's hysteresis must keep the already-hovered patch instead
# of flip-flopping (which is what flickered).
# ---------------------------------------------------------------------------
overlap_a = make_plane("OverlapA", 1.000, face_id=111)
overlap_b = make_plane("OverlapB", 1.00002, face_id=222)  # 0.02mm apart
bpy.context.view_layer.update()

dist_a = pr.operators.patch_hit_distance(ray_origin, ray_direction, overlap_a, 111)
dist_b = pr.operators.patch_hit_distance(ray_origin, ray_direction, overlap_b, 222)
check("patch_hit_distance resolves each overlapping patch",
      dist_a is not None and dist_b is not None, f"a={dist_a}, b={dist_b}")
check("patch_hit_distance returns None for a face_id not on that object",
      pr.operators.patch_hit_distance(ray_origin, ray_direction, overlap_a, 999) is None)

# Simulate the modal's decision without a real event/viewport. bpy operator
# classes can't be instantiated directly, but _keeps_current_hover only
# touches _hover_obj/_hover_face_id on self, so call it unbound with a
# duck-typed stand-in.
_keeps_current_hover = pr.operators.RETOP_OT_session._keeps_current_hover


class _FakeSelf:
    _hover_obj = None
    _hover_face_id = None


class _FakeEvent:
    mouse_region_x = 0
    mouse_region_y = 0


fake = _FakeSelf()
fake._hover_obj = overlap_a
fake._hover_face_id = 111


# Patch ray_from_event, since there's no viewport region in background mode.
_real_ray_from_event = pr.operators.ray_from_event
pr.operators.ray_from_event = lambda ctx, ev: (ray_origin, ray_direction)
try:
    keeps = _keeps_current_hover(fake, bpy.context, _FakeEvent(), dist_b)
    check("hysteresis keeps the current patch when a coincident one is reported", keeps,
          f"dist_a={dist_a}, dist_b={dist_b}")

    # A patch clearly in front (well beyond tolerance) must still take over.
    fake._hover_obj = overlap_b
    fake._hover_face_id = 222
    in_front_distance = dist_b - 0.5
    keeps_far = _keeps_current_hover(fake, bpy.context, _FakeEvent(), in_front_distance)
    check("hysteresis yields to a patch clearly in front", not keeps_far,
          f"current={dist_b}, new={in_front_distance}")
finally:
    pr.operators.ray_from_event = _real_ray_from_event


# ===========================================================================
# The N-panel shares the 3D view's area
#
# The modal only knows the panel is under the cursor by this region test, and a
# regression here is not subtle: swallowing MOUSEMOVE over the panel leaves the
# whole panel unclickable, because Blender highlights buttons from mouse moves
# and never highlights the one the click then lands on. The click itself being
# passed through is not enough.
# ===========================================================================
class FakeRegion:
    def __init__(self, x, y, width, height):
        self.x = x
        self.y = y
        self.width = width
        self.height = height


_region = FakeRegion(x=100, y=50, width=800, height=600)
_in_region = pr.operators.point_in_region

check("a point in the middle of the viewport is inside",
      _in_region(_region, 500, 350))
check("its bottom-left corner is inside", _in_region(_region, 100, 50))
check("its top-right corner is inside", _in_region(_region, 900, 650))
check("a point left of it -- a left-docked toolbar -- is outside",
      not _in_region(_region, 99, 350))
check("a point right of it -- where the N-panel sits -- is outside",
      not _in_region(_region, 901, 350))
check("below is outside", not _in_region(_region, 500, 49))
check("above is outside", not _in_region(_region, 500, 651))
check("no region at all is outside, not a crash", not _in_region(None, 500, 350))

# --- Region Overlap: the N-panel floats *over* the WINDOW region ---
#
# Blender's default. The WINDOW region spans the whole area and the panels are
# drawn on top of it, so a point under the N-panel really is inside the WINDOW
# region -- testing that region alone reports "over the viewport" while the
# pointer is over the panel, and the modal then eats the panel's events. This
# is what made the panel dead during a session.
class FakeArea:
    def __init__(self, regions):
        self.regions = regions


_n_panel = FakeRegion(x=700, y=50, width=200, height=600)   # right edge, overlapping
_n_panel.type = 'UI'
_header = FakeRegion(x=100, y=624, width=800, height=26)
_header.type = 'HEADER'
_collapsed_toolbar = FakeRegion(x=100, y=50, width=1, height=600)
_collapsed_toolbar.type = 'TOOLS'
FakeRegion.type = 'WINDOW'
_window = FakeRegion(x=100, y=50, width=800, height=600)
_window.type = 'WINDOW'

_area = FakeArea([_window, _n_panel, _header, _collapsed_toolbar])
_in_viewport = pr.operators.point_in_viewport

check("open viewport space is over the viewport",
      _in_viewport(_area, _window, 400, 350))
check("a point under the N-panel is NOT, even though the WINDOW region "
      "extends beneath it",
      not _in_viewport(_area, _window, 800, 350))
check("nor is a point under the header",
      not _in_viewport(_area, _window, 400, 630))
check("a collapsed toolbar covers nothing and must not veto the viewport",
      _in_viewport(_area, _window, 100, 350))
check("outside the area entirely is still outside",
      not _in_viewport(_area, _window, 50, 350))
check("no area to inspect falls back to the region test",
      _in_viewport(None, _window, 400, 350))
check("the panel types that float over the view are all listed",
      {'UI', 'TOOLS', 'HEADER', 'TOOL_HEADER'} <= pr.operators.OVERLAY_REGION_TYPES)

check("mouse moves are in the set the modal must pass through",
      'MOUSEMOVE' in pr.operators.PANEL_EVENTS)
check("so are the clicks",
      {'LEFTMOUSE', 'RIGHTMOUSE'} <= pr.operators.PANEL_EVENTS)
check("and the wheel, which adjusts spans from the panel too",
      {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} <= pr.operators.PANEL_EVENTS)
# Keys too: a digit typed into a panel field must reach the field, not the
# span-entry handler, and Enter must confirm the field rather than commit.
check("and every session keybind, so none of them steals from a panel field",
      {'RET', 'ESC', 'TAB', 'BACK_SPACE', 'M', 'N', 'ZERO', 'NINE'}
      <= pr.operators.PANEL_EVENTS)

pr.unregister()

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
