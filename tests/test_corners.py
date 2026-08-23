"""Run inside Blender: blender --background --python tests/test_corners.py

Topological corner detection: splitting a patch boundary where the
*neighbouring* Plasticity face changes, rather than where the polyline turns
sharply enough.

The mesh below is the case that motivated it. Patch A's bottom boundary runs
against patch B, then against patch C, and the two meet at a shallow kink --
a chamfer. The angle test cannot see it (it turns far less than
corner_angle_threshold), so the vertex lands in the middle of a side and every
generator paves straight across it. The neighbour changes there, so the
topological test puts a corner exactly on it.
"""
import os
import sys
import importlib
import math

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

patch_data = pr.patch_data
sides_mod = pr.sides

# ---------------------------------------------------------------------------
#   v4(0,3) ------------------------- v3(4,3)
#      |                                 |          patch A (id 1)
#      |                                 |
#   v0(0,0) --- v1(2,0) ---___        v2(4,0.6)
#      |   B (id 2)  |    C (id 3) ---___|
#   b0(0,-1) --- b1(2,-1) ---------- c1(4,-0.4)
#
# The kink at v1 turns ~17 degrees: nowhere near a detected corner, but it is
# where B stops and C starts.
# ---------------------------------------------------------------------------
V0, V1, V2, V3, V4 = (0.0, 0.0), (2.0, 0.0), (4.0, 0.6), (4.0, 3.0), (0.0, 3.0)
B0, B1 = (0.0, -1.0), (2.0, -1.0)
C0, C1 = (2.0, -1.0), (4.0, -0.4)  # C0 is coincident with B1, as a soup export would be

coords = [V0, V1, V2, V3, V4, B0, B1, C0, C1]
verts = [(x, y, 0.0) for x, y in coords]
v0, v1, v2, v3, v4, b0, b1, c0, c1 = range(9)

# Wound CCW so each patch's half-edges oppose its neighbour's.
tris_a = [(v4, v0, v1), (v4, v1, v2), (v4, v2, v3)]
tris_b = [(b0, b1, v1), (b0, v1, v0)]
tris_c = [(c0, c1, v2), (c0, v2, v1)]

mesh = bpy.data.meshes.new("ChamferMesh")
mesh.from_pydata(verts, [], tris_a + tris_b + tris_c)
mesh.update()
mesh["groups"] = [
    0, len(tris_a) * 3,
    len(tris_a) * 3, len(tris_b) * 3,
    (len(tris_a) + len(tris_b)) * 3, len(tris_c) * 3,
]
mesh["face_ids"] = [1, 2, 3]

obj = bpy.data.objects.new("ChamferObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

patches = patch_data.get_patches_with_boundaries(mesh)
patch_a = patches.get(1)
check("patch A was found", patch_a is not None)
check("with a single boundary loop", len(patch_a.boundary_loops) == 1,
      len(patch_a.boundary_loops))
check("and a neighbour list per loop",
      len(patch_a.boundary_neighbours) == len(patch_a.boundary_loops))

loop = patch_a.boundary_loops[0]
neighbours = patch_a.boundary_neighbours[0]
check("one neighbour entry per boundary segment",
      len(neighbours) == len(loop), f"{len(neighbours)} vs {len(loop)}")

positions = {v.index: v.co.copy() for v in mesh.vertices}
weld = patch_data.build_weld_map(mesh)


def loop_index_of(raw_vertex):
    """Where a raw vertex sits in the boundary loop (loops are in welded ids)."""
    welded = weld[raw_vertex]
    return loop.index(welded) if welded in loop else -1


i_v1 = loop_index_of(v1)
check("the chamfer vertex is on the boundary", i_v1 != -1, i_v1)

# The neighbour across the segment arriving at v1 is B, across the one leaving
# it is C. That difference is the whole signal.
before = neighbours[(i_v1 - 1) % len(loop)]
after = neighbours[i_v1]
check("the neighbour changes at the chamfer vertex", before != after,
      f"{before} -> {after}")
check("and names the two real patches", {before, after} == {2, 3},
      f"{before}, {after}")
check("a free border reports no neighbour",
      patch_data.NO_NEIGHBOUR in neighbours, neighbours)

# --- the angle test genuinely cannot see it ---
turn = sides_mod._angle_at(positions[weld[v0]], positions[weld[v1]], positions[weld[v2]])
check("the chamfer is far gentler than the corner threshold",
      turn > 135.0, f"interior angle {turn:.1f} deg vs threshold 135")

angle_corners = sides_mod.resolve_corners(loop, positions, 135.0, neighbours, 'ANGLE')
topo_corners = sides_mod.resolve_corners(loop, positions, 135.0, neighbours, 'TOPOLOGY')
both_corners = sides_mod.resolve_corners(loop, positions, 135.0, neighbours, 'BOTH')

check("ANGLE misses the chamfer -- the bug this fixes", i_v1 not in angle_corners,
      angle_corners)
check("TOPOLOGY finds it", i_v1 in topo_corners, topo_corners)
check("BOTH finds it", i_v1 in both_corners, both_corners)
check("BOTH is the union of the two",
      set(both_corners) == set(angle_corners) | set(topo_corners))
check("BOTH never loses a corner ANGLE had",
      set(angle_corners) <= set(both_corners))

# --- the fallback: a boundary with no junction at all ---
one_neighbour = [2] * len(loop)
check("a boundary against a single neighbour has no junction",
      sides_mod.detect_topological_corners(loop, one_neighbour) == [])
fallback = sides_mod.resolve_corners(loop, positions, 135.0, one_neighbour, 'TOPOLOGY')
check("TOPOLOGY falls back to the angle test rather than yield a 1-sided patch",
      fallback == angle_corners, fallback)
check("no neighbour data at all is handled the same way",
      sides_mod.resolve_corners(loop, positions, 135.0, None, 'TOPOLOGY') == angle_corners)
check("mismatched neighbour data is ignored, not indexed into",
      sides_mod.detect_topological_corners(loop, [2, 3]) == [])

# --- and it reaches the sides ---
sides_angle = sides_mod.split_into_sides(loop, positions, corner_indices=angle_corners)
sides_both = sides_mod.split_into_sides(loop, positions, corner_indices=both_corners)
check("the extra corner adds a side", len(sides_both) == len(sides_angle) + 1,
      f"{len(sides_angle)} -> {len(sides_both)}")
check("and the chamfer vertex now starts one of them",
      any(side[0] == loop[i_v1] for side in sides_both))
check("which it did not before",
      not any(side[0] == loop[i_v1] for side in sides_angle))

# --- end to end, through the session's own preparation ---
state = bpy.context.scene.plasticity_retop
# Two settings, because the modes want opposite things from a corner: a grid's
# side count picks the generator, so extra corners turn a bevel's quad into an
# N-Side fan; an n-gon just follows the boundary, where they cost nothing.
check("grids default to ANGLE, so a bevel keeps its four sides",
      state.corner_method_spans == 'ANGLE', state.corner_method_spans)
check("N-gon defaults to BOTH, so a chamfer survives",
      state.corner_method_ngon == 'BOTH', state.corner_method_ngon)

prepared_both = pr.patchprep.prepare_patch(mesh, 1, 135.0, 0.0, 'BOTH')
prepared_angle = pr.patchprep.prepare_patch(mesh, 1, 135.0, 0.0, 'ANGLE')
check("_prepare_patch honours the method",
      len(prepared_both.sides) == len(prepared_angle.sides) + 1,
      f"{len(prepared_angle.sides)} vs {len(prepared_both.sides)}")
check("the chamfer vertex is a patch corner in BOTH",
      weld[v1] in prepared_both.corner_source_ids, prepared_both.corner_source_ids)
check("and is not one in ANGLE",
      weld[v1] not in prepared_angle.corner_source_ids,
      prepared_angle.corner_source_ids)

# A corner is an exact source vertex, so it welds by identity across patches --
# which is what makes the neighbouring patch agree on the same point.
check("corners stay real source vertices",
      all(cid in positions for cid in prepared_both.corner_source_ids))

# --- the whole point: an n-gon now reproduces the chamfer ---
pr.operators.enter_session_object(bpy.context, obj)
state.ngon_mode = True
pr.operators.set_active_patch(bpy.context, obj, 1)
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
kink = positions[weld[v1]]
check("the n-gon keeps a vertex on the chamfer",
      any((v.co - kink).length < 1e-6 for v in preview.data.vertices),
      [tuple(round(c, 2) for c in v.co) for v in preview.data.vertices])
pr.operators.end_session(bpy.context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
