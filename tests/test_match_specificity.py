"""Run inside Blender: blender --background --python tests/test_match_specificity.py

What a side is allowed to match, and what it must refuse.

Matching used to be pure proximity: every committed vertex in the result mesh
went into one pool, and whatever fell within the tolerance of a side was taken
as that side's neighbour. Proximity cannot tell "the patch across this edge"
from "a patch that happens to run close by", so a face stacked a fraction above
another, a thin wall, or two sheets meeting at a shallow angle would hand a
side a run of vertices that traces a loop through its neighbourhood instead of
the edge it shares -- and the patch came out welded to the wrong thing.

The mesh says outright which face is across each boundary segment. This checks
the match is confined to it.

  A (id 1)  the face being retopped, z = 0
  B (id 2)  a strip sharing A's y = 0 edge -- a real neighbour
  C (id 3)  a separate sheet 2 cm above A's y = 3 edge, touching nothing
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
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


try:
    pr.unregister()
except Exception:
    pass
pr.register()

state = bpy.context.scene.plasticity_retop

# The stack-up: C sits 2 cm over A's top edge. The match margin is a share of
# the patch's longest side (4 units), so at the default 2% it reaches 0.08 --
# four times the gap. Proximity alone would take C every time.
GAP = 0.02

verts = [
    # A
    (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0),
    # B, sharing A's y = 0 edge
    (0.0, -1.0, 0.0), (4.0, -1.0, 0.0),
    # C, a separate sheet just above A's y = 3 edge
    (0.0, 3.0, GAP), (4.0, 3.0, GAP), (4.0, 4.0, GAP), (0.0, 4.0, GAP),
]
a0, a1, a2, a3, b0, b1, c0, c1, c2, c3 = range(10)
tris_a = [(a0, a1, a2), (a0, a2, a3)]
tris_b = [(b0, b1, a1), (b0, a1, a0)]
tris_c = [(c0, c1, c2), (c0, c2, c3)]

mesh = bpy.data.meshes.new("SpecificityMesh")
mesh.from_pydata(verts, [], tris_a + tris_b + tris_c)
mesh.update()
mesh["groups"] = [0, 6, 6, 6, 12, 6]
mesh["face_ids"] = [1, 2, 3]

obj = bpy.data.objects.new("SpecificityObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

pr.operators.enter_session_object(bpy.context, obj)
state.ngon_mode = False

# --- commit both of A's surroundings ---------------------------------------
for face_id in (2, 3):
    pr.operators.set_active_patch(bpy.context, obj, face_id)
    state.span_u = 3
    state.span_v = 3
    bpy.ops.retop.commit_patch()

check("both surrounding patches are committed",
      pr.mesh_build.committed_face_ids(obj) == {2, 3},
      str(pr.mesh_build.committed_face_ids(obj)))

grouped = pr.mesh_build.committed_boundary_map(obj)
check("and the result mesh is grouped by the patch that owns each vertex",
      set(grouped) == {2, 3}, sorted(grouped))

# --- what A's sides are allowed to see -------------------------------------
pr.operators.set_active_patch(bpy.context, obj, 1)
references = pr.sidematch.active_sides()
check("A is a quad with four sides", len(references) == 4, len(references))


def side_at(y):
    """A's side whose midpoint sits at this y (its polylines are world space)."""
    for reference in references:
        mid = sum(point.y for point in reference.points) / len(reference.points)
        if abs(mid - y) < 1e-6:
            return reference
    return None


shared = side_at(0.0)
stacked = side_at(3.0)
check("the shared side is found", shared is not None)
check("the stacked side is found", stacked is not None)

check("the shared side names B as its neighbour", shared.neighbours == [2],
      shared.neighbours)
check("and matches it", shared.available, shared.reason)

# The point of the whole thing: C is well inside the tolerance of A's top side,
# and is refused anyway, because nothing in the mesh says the two touch.
check("the stacked side has no neighbour at all -- nothing is across it",
      stacked.neighbours == [], stacked.neighbours)
check("so it matches nothing, however close C is",
      not stacked.available, stacked.reason)

within_reach = pr.mesh_build.side_match_tolerance(
    state, [p for p in stacked.points], margin=True, reference_length=4.0)
check("...and 'however close' means well inside the reach it would have had",
      within_reach > GAP, f"reach {within_reach:.3f} vs gap {GAP}")

# Proximity alone -- the old rule -- really would have taken it.
everything = pr.mesh_build.flatten_boundary_points(grouped, grouped, 1)
loose, _reason = pr.mesh_build.match_side_to_points(
    everything,
    [obj.matrix_world.inverted() @ point for point in stacked.points],
    within_reach)
check("proximity on its own would have matched the stacked sheet",
      loose is not None, "refused, so this test proves nothing")

# --- and the CAD edge is still on offer ------------------------------------
check("the stacked side can still be pinned to its own CAD edge",
      pr.operators.adopt_side_reference(
          bpy.context, stacked.index, pr.sidematch.PIN_SOURCE) is not None)

pr.operators.end_session(bpy.context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
