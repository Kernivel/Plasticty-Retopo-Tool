"""Run inside Blender: blender --background --python tests/test_disc_match.py

A disc welding to the band committed around it.

The case from the report: the cap of a truncated cone, bordering a wall already
committed as a Ring. Nothing on a disc's boundary is a corner, so
`sides.synthesise_corners` cuts it into four at the quarter points of its arc
length -- and those four are arbitrary. The neighbour has its own vertices
along the same circle at its own phase, the quarter points fall *between* them,
and `match_side_to_points` then asks each side for a committed vertex at a
corner the neighbour has no reason to have one at.

Measured on the fixture before the fix: two of the four sides happened to land
within 0.0026 of a rim vertex and matched, the other two had theirs claimed by
the side next door and refused with "neighbour stops short of this side's
start". Which sides won was the neighbour's phase, i.e. a coin toss.

So the test asserts both ends of it: that the *original* quarter cut really is
unmatchable -- otherwise it proves nothing -- and that after the re-cut every
side is applied, on a grid as well as on an n-gon.
"""
import importlib
import math
import os
import sys

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy
import mathutils

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


# ===========================================================================
#  The mesh: a disc (face 1) inside a flat band (face 2), sharing their rim.
#
#  The band is what gets committed first, exactly as a cone's wall is; the
#  disc is the cap that then has to weld onto it.
# ===========================================================================
SEGMENTS = 24
INNER, OUTER = 1.0, 1.6

verts = [(0.0, 0.0, 0.0)]                      # 0: the disc's centre
rim = []
for k in range(SEGMENTS):
    angle = 2.0 * math.pi * k / SEGMENTS
    rim.append(len(verts))
    verts.append((INNER * math.cos(angle), INNER * math.sin(angle), 0.0))
outer = []
for k in range(SEGMENTS):
    angle = 2.0 * math.pi * k / SEGMENTS
    outer.append(len(verts))
    verts.append((OUTER * math.cos(angle), OUTER * math.sin(angle), 0.0))

disc_tris = [(0, rim[k], rim[(k + 1) % SEGMENTS]) for k in range(SEGMENTS)]
band_tris = []
for k in range(SEGMENTS):
    a, b = rim[k], rim[(k + 1) % SEGMENTS]
    c, d = outer[k], outer[(k + 1) % SEGMENTS]
    band_tris.append((a, c, d))
    band_tris.append((a, d, b))

mesh = bpy.data.meshes.new("DiscMesh")
mesh.from_pydata(verts, [], disc_tris + band_tris)
mesh.update()
mesh["groups"] = [0, len(disc_tris) * 3, len(disc_tris) * 3, len(band_tris) * 3]
mesh["face_ids"] = [1, 2]

obj = bpy.data.objects.new("DiscObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

pr.operators.enter_session_object(bpy.context, obj)


# ===========================================================================
#  The disc's corners are arbitrary, and the band's are not
# ===========================================================================
prepared_disc = pr.patchprep.prepare_patch(mesh, 1, 135.0, 0.0, 'BOTH')
check("the disc has one boundary loop", prepared_disc.num_loops == 1,
      prepared_disc.num_loops)
check("its corners are flagged arbitrary -- nothing on a circle is a corner",
      prepared_disc.loops_corners_arbitrary == [True],
      prepared_disc.loops_corners_arbitrary)
check("and it still has four sides to hand a generator",
      len(prepared_disc.sides) == 4, len(prepared_disc.sides))

# A boundary whose shape *does* say where its ends are must never be re-cut:
# a stadium's ends are a fact about the strip, and moving them onto a
# neighbour's phase would destroy the one feature the shape has.
stadium = [(-2.0, -1.0, 0.0), (0.0, -1.0, 0.0), (2.0, -1.0, 0.0),
           (2.6, 0.0, 0.0),
           (2.0, 1.0, 0.0), (0.0, 1.0, 0.0), (-2.0, 1.0, 0.0),
           (-2.6, 0.0, 0.0)]
strip_mesh = bpy.data.meshes.new("StripMesh")
strip_tris = [(0, 1, 5), (0, 5, 6), (1, 2, 3), (1, 3, 5), (3, 4, 5), (6, 7, 0)]
strip_mesh.from_pydata(stadium, [], strip_tris)
strip_mesh.update()
strip_mesh["groups"] = [0, len(strip_tris) * 3]
strip_mesh["face_ids"] = [8]
prepared_strip = pr.patchprep.prepare_patch(strip_mesh, 8, 135.0, 0.0, 'BOTH')
check("a shape-cornered boundary is never flagged arbitrary",
      prepared_strip is not None
      and prepared_strip.loops_corners_arbitrary == [False],
      None if prepared_strip is None else prepared_strip.loops_corners_arbitrary)


# ===========================================================================
#  Commit the band, then look at what the disc can do
# ===========================================================================
state.ngon_mode = False
state.auto_match_neighbours = True
pr.operators.set_active_patch(bpy.context, obj, 2)
check("the band is a ring", state.generator_name == "Ring", state.generator_name)
bpy.ops.retop.commit_patch()
check("the band is committed", state.committed_patch_count == 1,
      state.committed_patch_count)

committed = pr.mesh_build.committed_boundary_map(obj)
pool = pr.sidematch._match_pool(committed, [2], 1)
check("the band left vertices on the shared rim", len(pool) >= SEGMENTS,
      len(pool))


# --- the "before": the quarter cut cannot be matched -----------------------
# Run the *unmodified* pipeline's own answer against the untouched quarter
# sides. Without this the test would pass on a build that never had the bug.
reference_length = max(
    sum((b - a).length for a, b in zip(side, side[1:]))
    for side in prepared_disc.sides)
refused = 0
for side in prepared_disc.sides:
    strict = pr.mesh_build.side_match_tolerance(
        state, side, reference_length=reference_length)
    rivals = [other for other in prepared_disc.sides if other is not side]
    points, _reason = pr.mesh_build.match_side_to_points(
        pool, side, strict, merge=strict, rivals=rivals)
    if points is None:
        refused += 1
check("cut at the quarter points, the disc's sides cannot all be matched",
      refused > 0, f"{refused} of {len(prepared_disc.sides)} refused")


# --- the "after": every side is matched, and on both generators ------------
for ngon_mode in (False, True):
    state.ngon_mode = ngon_mode
    label = "n-gon" if ngon_mode else "grid"
    pr.operators.set_active_patch(bpy.context, obj, 1)
    references = pr.sidematch.active_sides()
    check(f"({label}) the disc still offers four sides",
          len(references) == 4, len(references))
    check(f"({label}) every side is matched, not merely matchable",
          all(reference.applied for reference in references),
          [(r.index, r.applied, r.outvoted, r.reason) for r in references])
    check(f"({label}) none was outvoted -- opposite sides get equal counts",
          not any(reference.outvoted for reference in references),
          [r.outvoted for r in references])

    # Every corner now sits on one of the neighbour's own committed vertices.
    # That is the whole point: it is what makes the strict tolerance -- the one
    # automatic matching uses -- pass at all.
    worst = 0.0
    for reference in references:
        start = obj.matrix_world.inverted() @ reference.points[0]
        worst = max(worst, min((point - start).length for point in pool))
    check(f"({label}) every corner landed on a committed vertex",
          worst < 1e-6, f"worst {worst:.9f}")


# ===========================================================================
#  Sharing one span between two sides that want the same count
# ===========================================================================
# A quad's opposite sides drive one span, so a re-cut that gave them 12 and 13
# left one of them outvoted -- half the disc welded, half on the CAD boundary.
counts = pr.sidematch._opposed_segment_counts(50, 4)
check("50 segments over four sides pair up", counts == [13, 12, 13, 12], counts)
check("opposite sides get equal counts",
      counts[0] == counts[2] and counts[1] == counts[3], counts)
check("an odd total falls back to spreading one at a time",
      sum(pr.sidematch._opposed_segment_counts(51, 4)) == 51,
      pr.sidematch._opposed_segment_counts(51, 4))
check("an odd side count still adds up",
      sum(pr.sidematch._opposed_segment_counts(23, 5)) == 23,
      pr.sidematch._opposed_segment_counts(23, 5))
check("a boundary with fewer points than sides is refused",
      pr.sidematch._opposed_segment_counts(3, 4) is None)


# ===========================================================================
#  With automatic matching off, nothing is re-cut
# ===========================================================================
# The re-cut moves a patch's corners, so it may only happen where the user has
# asked for neighbours to be followed at all.
state.auto_match_neighbours = False
state.ngon_mode = False
pr.operators.set_active_patch(bpy.context, obj, 1)
untouched = pr.sidematch.active_sides()
check("with auto-matching off the disc keeps its own corners",
      all(not reference.applied for reference in untouched),
      [r.applied for r in untouched])

pr.operators.end_session(bpy.context)

print(f"\n=== {'ALL CHECKS PASSED' if not FAILURES else str(len(FAILURES)) + ' FAILURE(S): ' + str(FAILURES)}")
if FAILURES:
    sys.exit(1)
