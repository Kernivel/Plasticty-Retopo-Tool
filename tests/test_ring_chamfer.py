"""Run inside Blender: blender --background --python tests/test_ring_chamfer.py

A chamfer running all the way round a circle: a conical band between two
concentric rims, neither of which has a corner on it.

This is the shape that broke when cornerless boundaries started getting four
synthesised corners. A ring never goes through `find_generator` -- it is picked
by having two loops -- so it never needed them, and getting them is worse than
useless: `ring_from_sides` allocates points per side, so two loops whose
invented corners don't face each other have their points paired across a shear
rather than straight across the band.
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

state = bpy.context.scene.plasticity_retop

# ---------------------------------------------------------------------------
# The band. The two rims are sampled *differently* on purpose -- a mesher has
# no reason to put the same number of vertices on both, and that is precisely
# when paired-by-index corners go wrong.
# ---------------------------------------------------------------------------
OUTER_N, INNER_N = 64, 48
OUTER_R, INNER_R, DROP = 1.0, 0.75, -0.2

verts = []
for i in range(OUTER_N):
    a = 2 * math.pi * i / OUTER_N
    verts.append((OUTER_R * math.cos(a), OUTER_R * math.sin(a), 0.0))
for i in range(INNER_N):
    a = 2 * math.pi * i / INNER_N
    verts.append((INNER_R * math.cos(a), INNER_R * math.sin(a), DROP))


def outer(i):
    return i % OUTER_N


def inner(i):
    return OUTER_N + i % INNER_N


# Triangulate the band by walking both rims together by angle.
tris = []
oi = ii = 0
while oi < OUTER_N or ii < INNER_N:
    if oi / OUTER_N <= ii / INNER_N and oi < OUTER_N:
        tris.append((outer(oi), outer(oi + 1), inner(ii)))
        oi += 1
    else:
        tris.append((inner(ii + 1), inner(ii), outer(oi)))
        ii += 1

mesh = bpy.data.meshes.new("ChamferRingMesh")
mesh.from_pydata(verts, [], tris)
mesh.update()
mesh["groups"] = [0, len(tris) * 3]
mesh["face_ids"] = [3]

obj = bpy.data.objects.new("ChamferRingObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

prepared = pr.patchprep.prepare_patch(mesh, 3, 135.0, 0.0, 'BOTH')
check("the band is read as two boundary loops", prepared.num_loops == 2,
      prepared.num_loops)
check("so the pipeline calls it a ring", prepared.is_ring)

# The regression, stated directly: no corners may be invented on either loop.
check("neither cornerless rim gets corners invented for it",
      all(len(sides) == 1 for sides in prepared.loops_sides),
      [len(sides) for sides in prepared.loops_sides])

# Which is what a ring wants, and only a single-loop patch does not.
sides_mod = pr.sides
positions = {v.index: v.co.copy() for v in mesh.vertices}
rim = prepared.patch.boundary_loops[0]
check("synthesis is still there for the patches that need it",
      len(sides_mod.resolve_corners(rim, positions, 135.0, None, 'BOTH',
                                    allow_synthesis=True)) == 4)
check("and off it produces none",
      sides_mod.resolve_corners(rim, positions, 135.0, None, 'BOTH',
                                allow_synthesis=False) == [])


# --- what the generator actually builds ---
pr.operators.enter_session_object(bpy.context, obj)
state.ngon_mode = False
state.resolution = 'MID'
name, num_sides, _propagated = pr.operators.set_active_patch(bpy.context, obj, 3)
check("it generates as a Ring", name == "Ring", name)

preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("with a band of quads", len(preview.data.polygons) > 0,
      len(preview.data.polygons))
check("every face a quad, none collapsed into a fan",
      all(len(poly.vertices) == 4 for poly in preview.data.polygons),
      sorted({len(p.vertices) for p in preview.data.polygons}))
check("and none of them degenerate",
      all(poly.area > 1e-9 for poly in preview.data.polygons),
      min(poly.area for poly in preview.data.polygons))

# The real symptom was a sheared band: quads that should sit across the gap
# instead running around it. Every quad of a correct band spans most of the
# radial gap, and none of them is wildly longer than the others.
radii = [math.hypot(v.co.x, v.co.y) for v in preview.data.vertices]
check("the band stays between the two rims",
      all(INNER_R - 0.02 <= r <= OUTER_R + 0.02 for r in radii),
      f"{min(radii):.3f} .. {max(radii):.3f}")

edge_lengths = []
for edge in preview.data.edges:
    a = preview.data.vertices[edge.vertices[0]].co
    b = preview.data.vertices[edge.vertices[1]].co
    edge_lengths.append((a - b).length)
longest = max(edge_lengths)
gap = OUTER_R - INNER_R
check("no edge cuts across the ring -- that is what a shear looks like",
      longest < gap * 3.0, f"longest {longest:.3f}, radial gap {gap:.3f}")

bpy.ops.retop.commit_patch()
result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
check("and it commits", result is not None and len(result.data.polygons) > 0,
      len(result.data.polygons) if result else "none")


# ===========================================================================
# Matching across a CLOSED side
#
# The band's rims are cornerless loops, so each is a single side that starts
# and ends at the same vertex. Asking for a committed vertex at "both ends"
# then asks for two in one place and always refuses -- which is why a bore's
# rim showed red, unmatchable, while visibly bordering finished retopology.
# ===========================================================================
check("each rim is one closed side",
      all(len(sides) == 1 for sides in prepared.loops_sides))
rim_side = prepared.loops_sides[0][0]
check("whose first and last point are the same vertex",
      (rim_side[0] - rim_side[-1]).length < 1e-9,
      (rim_side[0] - rim_side[-1]).length)

# The band we just committed above *is* the neighbour along both rims.
tolerance = pr.mesh_build.side_match_tolerance(state, rim_side)
pool = pr.mesh_build.committed_boundary_points(obj, exclude_face_id=-1)
points, reason = pr.mesh_build.match_side_to_points(pool, rim_side, tolerance)
check("a closed side can be matched at all -- it could not before", points is not None,
      reason)
check("and the match closes back on itself, like the side it replaces",
      points is not None and (points[0] - points[-1]).length < 1e-9)
check("starting on the side's own corner, which welds by identity",
      points is not None and (points[0] - rim_side[0]).length <= tolerance,
      None if points is None else (points[0] - rim_side[0]).length)
check("with as many points as the neighbour put round the rim",
      points is not None and len(points) > 8, None if points is None else len(points))

# A neighbour covering only part of the loop still has to be refused: there is
# nothing to align the rest of the rim against.
half = pr.mesh_build.match_side_to_points(
    pool, rim_side[:len(rim_side) // 2], tolerance)
check("a partial rim is still refused, with a reason",
      half[0] is None and half[1], half[1])

# And the patch itself is excluded, or it would match its own geometry.
own = pr.mesh_build.match_side_to_points(
    pr.mesh_build.committed_boundary_points(obj, exclude_face_id=3),
    rim_side, tolerance)
check("the patch being edited does not match itself", own[0] is None, own[1])


# ===========================================================================
# The case from the field: matching a rim against a neighbour that put its
# points somewhere else entirely.
#
# A disc committed as a Quad places its boundary points at arc-length resamples
# from its *own* four synthesised corners. The band's rim starts wherever the
# half-edge walk happened to, so none of the disc's points sits on it -- and
# requiring one there refused every real case. The start of a cornerless loop
# is arbitrary; it is not a B-rep vertex and nothing else in the model agrees
# on it, so the match rotates to the nearest point and the corner id is
# dropped rather than left naming a vertex that has moved.
# ===========================================================================
pr.operators.end_session(bpy.context)

DISC_N = 40
disc_verts = []
for i in range(DISC_N):
    a = 2 * math.pi * i / DISC_N
    disc_verts.append((INNER_R * math.cos(a), INNER_R * math.sin(a), DROP))
band_start = len(disc_verts)
for i in range(OUTER_N):
    a = 2 * math.pi * i / OUTER_N
    disc_verts.append((OUTER_R * math.cos(a), OUTER_R * math.sin(a), 0.0))
centre = len(disc_verts)
disc_verts.append((0.0, 0.0, DROP))

disc_tris = [(i, (i + 1) % DISC_N, centre) for i in range(DISC_N)]

band_tris = []
di = bi = 0
while di < DISC_N or bi < OUTER_N:
    if bi / OUTER_N <= di / DISC_N and bi < OUTER_N:
        band_tris.append((band_start + bi % OUTER_N,
                          band_start + (bi + 1) % OUTER_N,
                          di % DISC_N))
        bi += 1
    else:
        band_tris.append(((di + 1) % DISC_N, di % DISC_N,
                          band_start + bi % OUTER_N))
        di += 1

pair_mesh = bpy.data.meshes.new("BoreMesh")
pair_mesh.from_pydata(disc_verts, [], disc_tris + band_tris)
pair_mesh.update()
pair_mesh["groups"] = [0, len(disc_tris) * 3, len(disc_tris) * 3, len(band_tris) * 3]
pair_mesh["face_ids"] = [10, 20]   # 10 = the disc floor, 20 = the band round it

pair_obj = bpy.data.objects.new("BoreObj", pair_mesh)
bpy.context.collection.objects.link(pair_obj)
bpy.context.view_layer.objects.active = pair_obj
pr.operators.enter_session_object(bpy.context, pair_obj)

state.ngon_mode = False
pr.operators.set_active_patch(bpy.context, pair_obj, 10)
check("the disc floor comes out as a Quad -- four synthesised corners",
      state.generator_name == "Quad", state.generator_name)
bpy.ops.retop.commit_patch()
check("and is committed", state.committed_patch_count == 1,
      state.committed_patch_count)

pr.operators.set_active_patch(bpy.context, pair_obj, 20)
check("the band round it is a Ring", state.generator_name == "Ring",
      state.generator_name)

references = pr.sidematch.active_sides()
check("it offers both of its rims", len(references) == 2, len(references))
matchable = [r for r in references if r.available]
check("and the one against the committed disc can be matched -- this is the "
      "refusal that was reported", len(matchable) == 1,
      [(r.index, r.reason) for r in references])

rim = matchable[0]
check("the match closes on itself",
      (rim.match_points[0] - rim.match_points[-1]).length < 1e-9)
check("and carries the disc's own boundary vertices",
      len(rim.match_points) > 4, len(rim.match_points))

# The disc put its points at arc-length resamples of its own corners, so the
# rim's arbitrary start is not one of them -- which is exactly why requiring
# one there refused.
prepared_pair = pr.patchprep.prepare_patch(pair_mesh, 20, 135.0, 0.0, 'BOTH')
rim_side = prepared_pair.loops_sides[rim.loop][rim.in_loop]
offset = (rim.match_points[0] - rim_side[0]).length

# Automatic matching now runs for grids and rings too, not only n-gons: a grid
# that copies a neighbour's segment count still lands between the neighbour's
# vertices whenever the neighbour didn't space them evenly, which is the crack
# matching exists to close. Turned off, nothing is taken without being asked.
state.auto_match_neighbours = False
counts, _outvoted = pr.sidematch.apply_side_matches(
    bpy.context, pair_obj, prepared_pair, pr.constants.RING)
check("nothing is matched while automatic matching is off", counts == {}, counts)

state.auto_match_neighbours = True
prepared_pair = pr.patchprep.prepare_patch(pair_mesh, 20, 135.0, 0.0, 'BOTH')
counts, _outvoted = pr.sidematch.apply_side_matches(
    bpy.context, pair_obj, prepared_pair, pr.constants.RING)
check("with it on, the rim is matched unasked", rim.index in counts, counts)

state.auto_match_neighbours = False
pr.operators.adopt_side_reference(bpy.context, rim.index)
prepared_pair = pr.patchprep.prepare_patch(pair_mesh, 20, 135.0, 0.0, 'BOTH')
counts, _outvoted = pr.sidematch.apply_side_matches(
    bpy.context, pair_obj, prepared_pair, pr.constants.RING)
check("adopting it matches that rim", rim.index in counts, counts)
check("the rim now carries the neighbour's points",
      len(prepared_pair.loops_sides[rim.loop][rim.in_loop]) == counts[rim.index] + 1)

# The corner id survives only while the corner itself has not moved. Here the
# neighbour happens to have a vertex on the rim's start, so it does not -- and
# keeping the id is right: it still names the vertex that point actually is.
corner_id = prepared_pair.loops_corner_ids[rim.loop][rim.in_loop]
if offset <= pr.mesh_build.side_match_tolerance(state, rim_side):
    check("the corner id is kept when the match starts on it",
          corner_id != pr.mesh_build.NO_SOURCE, corner_id)
else:
    check("and is dropped when the match moved it",
          corner_id == pr.mesh_build.NO_SOURCE, corner_id)

# The rule itself, on a match that *is* rotated away from the start: a corner
# welds by identity, so an id left on a point that has moved would make a later
# patch reuse a vertex somewhere else.
# The live reference, not the one captured before adopting: regenerating the
# preview rebuilds them, so the old object is no longer the one consulted.
live = pr.sidematch.active_sides()[rim.index]
moved = [point.copy() for point in live.match_points]
shift = len(moved) // 3
rotated = moved[shift:-1] + moved[:shift]
rotated.append(rotated[0].copy())
prepared_moved = pr.patchprep.prepare_patch(pair_mesh, 20, 135.0, 0.0, 'BOTH')
live.match_points = rotated
pr.sidematch.apply_side_matches(bpy.context, pair_obj, prepared_moved, pr.constants.RING)
check("a match that starts elsewhere drops the corner id",
      prepared_moved.loops_corner_ids[rim.loop][rim.in_loop]
      == pr.mesh_build.NO_SOURCE,
      prepared_moved.loops_corner_ids[rim.loop])

preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("and the band still generates", preview is not None
      and len(preview.data.polygons) > 0,
      len(preview.data.polygons) if preview else "none")
bpy.ops.retop.clear_preview()

pr.operators.end_session(bpy.context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
