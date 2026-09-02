"""Run inside Blender: blender --background --python tests/test_nside_match.py

An N-Side patch can reproduce more than one committed neighbour.

Its sides used to share a single span, so two of them bordering two finished
patches were a collision by construction: one was matched, the other was told
"another side drives the same span" and left on the CAD tessellation -- a crack
along an edge that was visibly against retopology, which is what the report
showed.

Since the fill became a ring of Coons sub-patches (see generators/nside.py),
a side is bounded by the spokes of its two *neighbours* -- `t[i] = s[i-1] +
s[i+1]`, its own spoke only saying where it is split. Choosing the spokes
chooses every side's count, so several matches can be honoured at once -- and
the ones that genuinely cannot (two sides two apart, sharing a spoke and
wanting counts that disagree) are *refused*
rather than approximated, because a match that comes back with a count nobody
asked for is a crack that looks like a weld.
"""
import os
import sys
import importlib
import math

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


nside = pr.generators.nside

# ---------------------------------------------------------------------------
# The solve, on its own
# ---------------------------------------------------------------------------
spokes, refused = nside.spoke_allocation(5, 2)
check("with nothing matched every spoke is the same", spokes == [2] * 5, spokes)
check("so every side carries the same even count",
      nside.side_segments(spokes) == [4] * 5, nside.side_segments(spokes))
check("and nothing is refused", refused == [], refused)

# One matched side fixes the two spokes its count is made of -- its
# *neighbours'* spokes, not its own.
spokes, refused = nside.spoke_allocation(5, 2, {0: 7}, [0])
check("a matched side gets exactly the count it asked for",
      nside.side_segments(spokes)[0] == 7, nside.side_segments(spokes))
check("and it is honoured", refused == [], refused)
check("only the two spokes it needed moved",
      [i for i, count in enumerate(spokes) if count != 2] == [1, 4], spokes)

# Two sides whose spoke pairs are disjoint are independent -- and on an odd
# patch those are the *adjacent* ones, since a side is bounded by the spokes
# two apart from it. This is the case the single shared span could not do at
# all: two committed neighbours, two different counts, one patch.
spokes, refused = nside.spoke_allocation(5, 2, {0: 7, 1: 5}, [0, 1])
segments = nside.side_segments(spokes)
check("two independent matches are both honoured",
      segments[0] == 7 and segments[1] == 5 and refused == [], (segments, refused))

# Sides two apart share a spoke, so the second is solved against the first.
spokes, refused = nside.spoke_allocation(5, 2, {0: 6, 2: 5}, [0, 2])
segments = nside.side_segments(spokes)
check("a match sharing a spoke is honoured when it can be",
      segments[0] == 6 and segments[2] == 5 and refused == [], (segments, refused))

# ...and refused when it cannot: side 0 took 3 of the shared spoke, so side 2
# cannot come out at 3 without a spoke of zero.
spokes, refused = nside.spoke_allocation(5, 2, {0: 6, 2: 3}, [0, 2])
segments = nside.side_segments(spokes)
check("and refused rather than approximated when it cannot",
      refused == [2] and segments[0] == 6, (segments, refused))
check("every spoke is still buildable", all(count >= 1 for count in spokes), spokes)

check("a side wanting one segment is refused -- it has no midpoint to split at",
      nside.spoke_allocation(5, 2, {0: 1}, [0])[1] == [0])

# The generator has to actually build what the solve promised.
hex_corners = [mathutils.Vector((math.cos(a), math.sin(a), 0.0))
               for a in [i * math.pi / 3.0 for i in range(6)]]
sides = []
for i in range(6):
    a = hex_corners[i]
    b = hex_corners[(i + 1) % 6]
    sides.append([a.lerp(b, t / 12.0) for t in range(13)])

spokes, _refused = nside.spoke_allocation(6, 2, {0: 7, 3: 3}, [0, 3])
wanted = nside.side_segments(spokes)
result = nside.NSideGenerator().generate(sides, {"spokes": spokes})
check("all quads whatever the sides carry",
      all(len(face) == 4 for face in result.faces),
      sorted({len(face) for face in result.faces}))
check("the boundary ring is as long as the counts add up to",
      len(result.boundary_local_indices) == sum(wanted),
      f"{len(result.boundary_local_indices)} vs {sum(wanted)}")
check("no vertex is emitted twice",
      len({tuple(round(c, 7) for c in v) for v in result.verts}) == len(result.verts))
check("one corner per side", len(result.corner_local_indices) == 6,
      result.corner_local_indices)
check("and it reports what each side got, for the registry",
      result.side_allocation == wanted, result.side_allocation)

# Every corner has to be a real corner of the shape, or the sides have moved.
corner_positions = [tuple(round(c, 5) for c in result.verts[i])
                    for i in result.corner_local_indices]
check("the corners are still the patch's own",
      all(tuple(round(c, 5) for c in corner) in corner_positions
          for corner in hex_corners),
      corner_positions)


# ===========================================================================
# End to end: a pentagon against two committed neighbours
# ===========================================================================
try:
    pr.unregister()
except Exception:
    pass
pr.register()

state = bpy.context.scene.plasticity_retop

R = 2.0
pent = [mathutils.Vector((R * math.cos(math.pi / 2 + i * 2 * math.pi / 5),
                          R * math.sin(math.pi / 2 + i * 2 * math.pi / 5), 0.0))
        for i in range(5)]


def outward(i):
    """A quad glued to pentagon edge i, pushed away from the centre."""
    a, b = pent[i], pent[(i + 1) % 5]
    mid = (a + b) * 0.5
    away = mid.normalized() * 1.2
    return a + away, b + away


verts = [tuple(p) for p in pent]
tris = [(0, 1, 2), (0, 2, 3), (0, 3, 4)]        # the pentagon, id 1
groups = [0, 9]
face_ids = [1]

# Two neighbours, on sides that do not share a spoke.
for face_id, edge in ((2, 0), (3, 1)):
    a, b = edge, (edge + 1) % 5
    q0, q1 = outward(edge)
    i0, i1 = len(verts), len(verts) + 1
    verts += [tuple(q0), tuple(q1)]
    groups += [len(tris) * 3, 6]
    # Wound so this face carries the half-edge (b, a) against the pentagon's
    # (a, b): that opposition is the whole of how a patch learns who is across
    # a side, and two faces wound the same way are two faces that never meet.
    tris += [(b, a, i0), (b, i0, i1)]
    face_ids.append(face_id)

mesh = bpy.data.meshes.new("NSideMatchMesh")
mesh.from_pydata(verts, [], tris)
mesh.update()
mesh["groups"] = groups
mesh["face_ids"] = face_ids

obj = bpy.data.objects.new("NSideMatchObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

pr.operators.enter_session_object(bpy.context, obj)

# Commit the two neighbours at different densities, so "both were matched"
# cannot pass by them happening to agree.
state.ngon_mode = False
for face_id, span in ((2, 3), (3, 6)):
    pr.operators.set_active_patch(bpy.context, obj, face_id)
    state.span_u = span
    state.span_v = 2
    pr.operators.regenerate_active_preview(bpy.context)
    bpy.ops.retop.commit_patch()
check("both neighbours are committed", state.committed_patch_count == 2,
      state.committed_patch_count)

generator, sides_count, _propagated = pr.operators.set_active_patch(bpy.context, obj, 1)
check("the pentagon is an N-Side patch", generator == "N-Side", generator)
check("with five sides", sides_count == 5, sides_count)

references = pr.sidematch.active_sides()
available = [r for r in references if r.available]
check("two of its sides border committed retopology", len(available) == 2,
      [(r.index, r.available, r.reason) for r in references])
check("and both are being matched, not one of them",
      all(r.applied for r in available),
      [(r.index, r.applied, r.outvoted) for r in references])
check("nothing was outvoted", not any(r.outvoted for r in references),
      [r.index for r in references if r.outvoted])
check("the two want different counts, so agreeing by luck is ruled out",
      len({len(r.match_points) for r in available}) == 2,
      [len(r.match_points) for r in available])

# The point of a match: the preview lands on the neighbour's own vertices.
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
preview_points = [v.co.copy() for v in preview.data.vertices]
worst = 0.0
for reference in available:
    for point in reference.match_points:
        worst = max(worst, min((point - p).length for p in preview_points))
check("every vertex both neighbours committed is reproduced exactly",
      worst < 1e-6, f"worst {worst:.8f}")

bpy.ops.retop.commit_patch()
check("and it commits", state.committed_patch_count == 3,
      state.committed_patch_count)

# The registry has to advertise what the mesh got, per side -- an N-Side's
# sides no longer share one number, so a single span would describe the
# matched sides wrongly and the next neighbour would propagate from it.
result_obj = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
import bmesh
bm = bmesh.new()
bm.from_mesh(result_obj.data)
open_edges = sum(1 for e in bm.edges if e.is_boundary)
non_manifold = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
bm.free()
check("the pentagon welded onto both neighbours", non_manifold == 0, non_manifold)
# Only the outer rim of the three patches is left open: the two shared edges
# are welded, so they no longer count.
check("with no crack along either shared edge", open_edges > 0 and open_edges < 40,
      open_edges)

pr.operators.end_session(bpy.context)
pr.unregister()

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
