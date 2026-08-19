"""Run inside Blender: blender --background --python tests/test_ring.py

Patches bounded by two loops -- a face with a hole in it, and the guard for
faces with more holes than the band generator can handle.

The synthetic mesh is a flat square annulus carrying the same custom properties
the Plasticity bridge writes: a 4x4 square with a square hole in the middle,
triangulated, all of it one "face id" (one CAD face).
"""
import os
import sys
import importlib

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy

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

# ---------------------------------------------------------------------------
# A flat square annulus: a 4x4 grid of points at x/y in {0, 1.5, 2.5, 4}, every
# cell triangulated except the middle one -- which leaves a square hole.
# ---------------------------------------------------------------------------
COORDS = [0.0, 1.5, 2.5, 4.0]
grid_index = {}
verts = []
for j, y in enumerate(COORDS):
    for i, x in enumerate(COORDS):
        grid_index[(i, j)] = len(verts)
        verts.append((x, y, 0.0))

tris = []
for j in range(3):
    for i in range(3):
        if (i, j) == (1, 1):
            continue  # the hole
        v00 = grid_index[(i, j)]
        v10 = grid_index[(i + 1, j)]
        v11 = grid_index[(i + 1, j + 1)]
        v01 = grid_index[(i, j + 1)]
        tris.append((v00, v10, v11))
        tris.append((v00, v11, v01))

mesh = bpy.data.meshes.new("HolePlateMesh")
mesh.from_pydata(verts, [], tris)
mesh.update()
mesh["groups"] = [0, len(tris) * 3]
mesh["face_ids"] = [777]

obj = bpy.data.objects.new("HolePlate", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

# ---------------------------------------------------------------------------
# Boundary loops: the face has two, and the outer one must come first whatever
# order they were walked in (that ordering is hash-dependent otherwise).
# ---------------------------------------------------------------------------
patches = pr.patch_data.get_patches_with_boundaries(mesh)
patch = patches[777]
check("a holed face yields two boundary loops", len(patch.boundary_loops) == 2,
      str([len(loop) for loop in patch.boundary_loops]))

positions = {v.index: v.co.copy() for v in mesh.vertices}
ordered = pr.patch_data.sort_loops_outer_first(patch.boundary_loops, positions)
check("the outer loop is sorted first", len(ordered[0]) == 12 and len(ordered[1]) == 4,
      f"{len(ordered[0])} then {len(ordered[1])}")
check("sorting the loops is stable when they arrive reversed",
      pr.patch_data.sort_loops_outer_first(list(reversed(patch.boundary_loops)), positions)[0]
      == ordered[0])

# ---------------------------------------------------------------------------
# Span allocation: "around" is spread over the sides by length, never below one
# segment per side, and always sums to exactly the requested total.
# ---------------------------------------------------------------------------
ring_mod = pr.generators.ring
alloc = ring_mod.allocate_segments([4.0, 1.0, 4.0, 1.0], 10)
check("allocation sums to the requested total", sum(alloc) == 10, str(alloc))
check("allocation follows side length", alloc[0] > alloc[1] and alloc[2] > alloc[3], str(alloc))
alloc_min = ring_mod.allocate_segments([10.0, 0.01, 0.01], 2)
check("allocation never starves a side", min(alloc_min) >= 1, str(alloc_min))
check("allocation raises a too-small total to one per side", sum(alloc_min) == 3, str(alloc_min))

# ---------------------------------------------------------------------------
# Generation through the real pick path.
# ---------------------------------------------------------------------------
gen_name, num_sides, _prop = pr.operators.set_active_patch(bpy.context, obj, 777)
state = bpy.context.scene.plasticity_retop
check("a holed face resolves to the Ring generator", gen_name == "Ring", str(gen_name))
check("the ring records both loops", state.num_loops == 2, str(state.num_loops))
check("the ring reports every corner of both loops", num_sides == 8, str(num_sides))

state.span_u = 12   # around
state.span_v = 3    # across
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("the preview exists", preview is not None)
check("the ring is around x across quads",
      preview is not None and len(preview.data.polygons) == 12 * 3,
      f"expected {12 * 3}, got {len(preview.data.polygons) if preview else 'N/A'}")
check("the ring is all quads",
      preview is not None and all(len(p.vertices) == 4 for p in preview.data.polygons))
check("the ring has no interior fan vertex",
      preview is not None and len(preview.data.vertices) == 12 * (3 + 1),
      f"expected {12 * 4}, got {len(preview.data.vertices) if preview else 'N/A'}")

# The hole must stay a hole: no vertex may land inside it, and the innermost
# ring has to sit on the hole's boundary rather than across it.
hole_lo, hole_hi = 1.5, 2.5
inside = [tuple(v.co) for v in preview.data.vertices
          if hole_lo + 1e-4 < v.co.x < hole_hi - 1e-4
          and hole_lo + 1e-4 < v.co.y < hole_hi - 1e-4]
check("no geometry is generated inside the hole", not inside, str(inside[:3]))

on_hole = [v for v in preview.data.vertices
           if abs(v.co.x - hole_lo) < 1e-4 or abs(v.co.x - hole_hi) < 1e-4
           or abs(v.co.y - hole_lo) < 1e-4 or abs(v.co.y - hole_hi) < 1e-4]
check("the inner ring lies on the hole's boundary", len(on_hole) >= 12, str(len(on_hole)))

# Every vertex of a closed band is used by faces; a twisted or mis-aligned ring
# shows up as faces that fold back on themselves, i.e. duplicate face centres.
centres = {tuple(round(c, 5) for c in p.center) for p in preview.data.polygons}
check("no two ring faces land on the same spot (band isn't twisted)",
      len(centres) == len(preview.data.polygons),
      f"{len(centres)} distinct of {len(preview.data.polygons)}")

# ---------------------------------------------------------------------------
# Commit: the band bakes like any other patch, and stays re-editable.
# ---------------------------------------------------------------------------
res = bpy.ops.retop.commit_patch()
check("committing a ring FINISHED", res == {'FINISHED'}, str(res))
result_obj = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
check("the ring lands in the result mesh",
      result_obj is not None and len(result_obj.data.polygons) == 12 * 3,
      f"got {len(result_obj.data.polygons) if result_obj else 'N/A'}")
check("the ring is tracked as a committed patch",
      pr.mesh_build.committed_face_ids(obj) == {777},
      str(pr.mesh_build.committed_face_ids(obj)))

stored = pr.mesh_build.lookup_patch_settings(obj, 777)
check("the ring's spans are stored for a re-edit",
      stored is not None and stored["span_u"] == 12 and stored["span_v"] == 3, str(stored))

pr.operators.set_active_patch(bpy.context, obj, 777)
check("re-selecting a ring restores its spans",
      state.span_u == 12 and state.span_v == 3, f"{state.span_u}/{state.span_v}")
check("re-selecting a ring is flagged as a re-edit", state.editing_committed)
check("re-selecting a ring removes its old faces",
      state.reedit_removed_faces == 12 * 3, str(state.reedit_removed_faces))

state.span_u = 8
state.span_v = 2
bpy.ops.retop.commit_patch()
check("re-committing a ring replaces it",
      len(result_obj.data.polygons) == 8 * 2,
      f"expected {8 * 2}, got {len(result_obj.data.polygons)}")

pr.operators.end_session(bpy.context)

# ---------------------------------------------------------------------------
# Two holes: the band generator only spans two loops, so the outer boundary is
# used alone -- and the patch says so instead of pretending it worked.
# ---------------------------------------------------------------------------
# 6x6 points = 5x5 cells, so two holes can sit fully inside without touching
# each other or the outer boundary.
verts_two = []
grid_two = {}
for j in range(6):
    for i in range(6):
        grid_two[(i, j)] = len(verts_two)
        verts_two.append((float(i), float(j), 0.0))

tris_two = []
for j in range(5):
    for i in range(5):
        if (i, j) in ((1, 1), (3, 3)):
            continue  # two holes
        v00 = grid_two[(i, j)]
        v10 = grid_two[(i + 1, j)]
        v11 = grid_two[(i + 1, j + 1)]
        v01 = grid_two[(i, j + 1)]
        tris_two.append((v00, v10, v11))
        tris_two.append((v00, v11, v01))

mesh2 = bpy.data.meshes.new("TwoHolesMesh")
mesh2.from_pydata(verts_two, [], tris_two)
mesh2.update()
mesh2["groups"] = [0, len(tris_two) * 3]
mesh2["face_ids"] = [888]
obj2 = bpy.data.objects.new("TwoHoles", mesh2)
bpy.context.collection.objects.link(obj2)

gen_name2, _n2, _p2 = pr.operators.set_active_patch(bpy.context, obj2, 888)
check("a face with two holes still generates something", gen_name2 is not None, str(gen_name2))
check("a face with two holes is not treated as a ring", gen_name2 != "Ring", str(gen_name2))
check("the extra loops are reported for the panel to warn about",
      state.num_loops == 3, str(state.num_loops))

pr.operators.end_session(bpy.context)
pr.unregister()

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
