"""Run inside Blender: blender --background --python tests/test_match_neighbour.py

Matching a committed neighbour's density along a shared side.

The mesh is the case from the request: a bevel-like strip (patch B) already
retopologized with 3 segments across, and a flat face (patch A) next to it.
Nothing about A's own geometry says "3", so without pointing at the shared
boundary the two meet at different vertex counts and crack.
"""
import os
import sys
import importlib
import json

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
#  A: the flat face being retopped        B: the strip already committed
#
#   (0,3) ------------------- (4,3)
#     |                         |     A (id 1)
#   (0,0) ------------------- (4,0)   <- the shared side
#     |                         |     B (id 2)
#   (0,-1) ------------------ (4,-1)
# ---------------------------------------------------------------------------
verts = [
    (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0),
    (0.0, -1.0, 0.0), (4.0, -1.0, 0.0),
]
a0, a1, a2, a3, b0, b1 = range(6)
tris_a = [(a0, a1, a2), (a0, a2, a3)]
tris_b = [(b0, b1, a1), (b0, a1, a0)]

mesh = bpy.data.meshes.new("MatchMesh")
mesh.from_pydata(verts, [], tris_a + tris_b)
mesh.update()
mesh["groups"] = [0, len(tris_a) * 3, len(tris_a) * 3, len(tris_b) * 3]
mesh["face_ids"] = [1, 2]

obj = bpy.data.objects.new("MatchObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

pr.operators.enter_session_object(bpy.context, obj)

# --- commit B with a distinctive count across the shared edge ---
state.ngon_mode = False
pr.operators.set_active_patch(bpy.context, obj, 2)
check("B is a quad", state.generator_name == "Quad", state.generator_name)
# Two distinct counts, because which of them lands on the shared side depends
# on where the boundary walk started -- compute_boundary_loops walks a *set* of
# half-edges, so that is hash order and nothing to assert against. What the
# registry recorded for the shared corner pair is the ground truth here.
state.span_u = 3
state.span_v = 5
bpy.ops.retop.commit_patch()
check("B is committed", state.committed_patch_count == 1, state.committed_patch_count)

EXPECTED = pr.mesh_build.lookup_propagated_span(obj, 0, 1)
check("B registered a span along the shared corner pair", EXPECTED in (3, 5), EXPECTED)


# ===========================================================================
# The references A can see
# ===========================================================================
# Isolate the manual path first: automatic matching now runs for every
# generator, not just n-gons, so leaving it on would match the shared side
# before anything is adopted and there would be no "before" to compare.
state.auto_match_neighbours = False
pr.operators.set_active_patch(bpy.context, obj, 1)
references = pr.sidematch.active_sides()
check("A's sides are offered to the picker", len(references) == 4, len(references))
check("each carries its world-space polyline",
      all(len(reference.points) >= 2 for reference in references))

available = [reference for reference in references if reference.available]
check("exactly one side borders a committed patch", len(available) == 1,
      [(r.index, r.span, r.neighbour) for r in references])
shared = available[0]
check("and it reports exactly what B put along it", shared.span == EXPECTED,
      f"{shared.span} vs {EXPECTED}")
check("the picker names the neighbour it would match", shared.neighbour == 2,
      shared.neighbour)
check("the others have nothing to match",
      all(reference.span is None for reference in references
          if reference.index != shared.index))

# The shared side is the one on y = 0.
midpoints = [sum(p.y for p in reference.points) / len(reference.points)
             for reference in references]
check("the offered side is the shared boundary, not another one",
      abs(midpoints[shared.index]) < 1e-6, midpoints)


# ===========================================================================
# Adopting it, on a grid patch
# ===========================================================================
def shared_boundary_xs(mesh_object):
    """The preview's vertices lying on the shared edge (y = 0), left to right."""
    return sorted(round(v.co.x, 5) for v in mesh_object.data.vertices
                  if abs(v.co.y) < 1e-6)


# What the neighbour actually committed along the shared edge. Matching means
# landing on *these*, not on a count that happens to agree.
committed_xs = sorted(
    round((bpy.data.objects[pr.mesh_build.result_object_name_for(obj)].matrix_world @ v.co).x, 5)
    for v in bpy.data.objects[pr.mesh_build.result_object_name_for(obj)].data.vertices
    if abs(v.co.y) < 1e-6)
check("B left one vertex per segment boundary on the shared edge",
      len(committed_xs) == EXPECTED + 1, committed_xs)

SENTINEL = 9  # distinct from both of B's counts, so "before" is provable
state.span_u = SENTINEL
state.span_v = SENTINEL
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("before matching, the two disagree along the shared edge",
      shared_boundary_xs(preview) != committed_xs, shared_boundary_xs(preview))

adopted = pr.operators.adopt_side_reference(bpy.context, shared.index)
check("adopting reports what it matched",
      adopted is not None and adopted.span == EXPECTED,
      adopted.span if adopted else None)

# The point of the whole feature: not the same count, the same *vertices*.
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("after matching, the grid lands on the neighbour's own vertices",
      shared_boundary_xs(preview) == committed_xs,
      f"{shared_boundary_xs(preview)} vs {committed_xs}")

# ===========================================================================
# Saying which sides are actually being matched
#
# "Could be matched" and "is being matched" are different answers, and the
# viewport used to give only the first: a side that had lost a span collision,
# or whose span the user had typed since, drew the same green as one the
# preview was genuinely welding to. That is most of why the feature read as
# arbitrary, so the state is now recorded per side and the colour follows it.
# ===========================================================================
references = pr.sidematch.active_sides()
matched = [r for r in references if r.applied]
check("exactly the pinned side reports itself as matched",
      [r.index for r in matched] == [shared.index], [r.index for r in matched])

title, detail = pr.sidematch.status_of(matched[0], pr.sidematch.PIN_NEIGHBOUR)
check("and says so in words", title == "Selected for surface matching", title)
check("naming the patch it reproduces", "patch" in detail, detail)

idle = next(r for r in references if not r.applied and not r.available)
idle_title, idle_detail = pr.sidematch.status_of(idle, None)
check("a side with nothing to match says it is not selected",
      idle_title == "Not selected for surface matching", idle_title)
check("and gives the reason, not just the refusal",
      idle_detail == idle.reason and idle_detail != "", idle_detail)

# The colour is what the user actually reads, so pin the mapping rather than
# only the flags: green is reserved for a side being reproduced.
matched_color, matched_width = pr.overlay._side_appearance(
    matched[0], pr.sidematch.PIN_NEIGHBOUR, False)
idle_color, _idle_width = pr.overlay._side_appearance(idle, None, False)
check("a matched side is drawn in the matched colour",
      matched_color == pr.overlay.SIDE_MATCHED_COLOR, matched_color)
check("a side that is not being matched is not drawn green",
      idle_color != pr.overlay.SIDE_MATCHED_COLOR, idle_color)
check("and the matched one is drawn heavier",
      matched_width > pr.overlay.SIDE_WIDTH, matched_width)

# The report: clicking a matched side to unmatch it left it green and gave a
# strange grid. Releasing the pin was all the click did, and automatic matching
# put the match straight back on the very next regeneration.
pr.operators.adopt_side_reference(bpy.context, shared.index)
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
released = next(r for r in pr.sidematch.active_sides() if r.index == shared.index)
check("clicking a matched side stops it being matched", not released.applied)
check("and the grid goes back to its own spacing",
      shared_boundary_xs(preview) != committed_xs, shared_boundary_xs(preview))

pr.operators.adopt_side_reference(bpy.context, shared.index)
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
rematched = next(r for r in pr.sidematch.active_sides() if r.index == shared.index)
check("clicking it once more matches it again", rematched.applied)
check("landing back on the neighbour's vertices",
      shared_boundary_xs(preview) == committed_xs, shared_boundary_xs(preview))

lonely = next(r.index for r in references if not r.available)
check("a side with no committed neighbour cannot be pinned to one",
      pr.operators.adopt_side_reference(
          bpy.context, lonely, pr.sidematch.PIN_NEIGHBOUR) is None)
# ...but it can still be pinned to the CAD tessellation of the side itself,
# which needs no neighbour at all -- that is what makes the first patch of a
# model matchable.
check("and can be pinned to the source topology instead",
      pr.operators.adopt_side_reference(
          bpy.context, lonely, pr.sidematch.PIN_SOURCE) is not None)
check("which is recorded as a source pin",
      json.loads(state.side_overrides).get(str(lonely)) == pr.sidematch.PIN_SOURCE,
      state.side_overrides)
# Clicking it again turns the match *off* rather than merely dropping the pin.
# Dropping it is what this used to do, and with automatic matching on -- the
# default -- the automatic match put itself straight back on the next
# regeneration: the side stayed green and the click read as broken.
pr.operators.adopt_side_reference(bpy.context, lonely, pr.sidematch.PIN_SOURCE)
check("and clicking it again releases it, explicitly",
      json.loads(state.side_overrides).get(str(lonely)) == pr.sidematch.PIN_EXCLUDED,
      state.side_overrides)
check("which is what stops automatic matching taking it back",
      lonely not in {r.index for r in pr.sidematch.active_sides() if r.applied},
      state.side_overrides)
pr.operators.adopt_side_reference(bpy.context, lonely, pr.sidematch.PIN_SOURCE)
check("and clicking a released side matches it again",
      json.loads(state.side_overrides).get(str(lonely)) == pr.sidematch.PIN_SOURCE,
      state.side_overrides)
pr.operators.adopt_side_reference(bpy.context, lonely, pr.sidematch.PIN_SOURCE)
check("nor can an index that isn't a side",
      pr.operators.adopt_side_reference(bpy.context, 99) is None)
check("nor can -1, which is what 'nothing hovered' looks like",
      pr.operators.adopt_side_reference(bpy.context, -1) is None)

bpy.ops.retop.clear_preview()


# ===========================================================================
# The same, on an N-gon -- where the count is stored per side
# ===========================================================================
state.ngon_mode = True
state.auto_match_neighbours = False  # isolate the manual path first
pr.operators.set_active_patch(bpy.context, obj, 1)
check("picking a patch drops the pins from the previous one",
      state.side_overrides == "", state.side_overrides)
check("A is generated as an n-gon", state.generator_name == "N-gon",
      state.generator_name)

preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
plain_verts = len(preview.data.vertices)
check("a flat quad n-gon is just its corners", plain_verts == 4, plain_verts)

references = pr.sidematch.active_sides()
shared = next(reference for reference in references if reference.available)
adopted = pr.operators.adopt_side_reference(bpy.context, shared.index)
check("the n-gon records the match per side", adopted is not None)
stored = json.loads(state.side_overrides)
check("in side_overrides, keyed by side",
      stored == {str(shared.index): pr.sidematch.PIN_NEIGHBOUR}, stored)

preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("the matched side gained the neighbour's vertices",
      len(preview.data.vertices) == plain_verts + EXPECTED - 1,
      f"{plain_verts} -> {len(preview.data.vertices)}, expected +{EXPECTED - 1}")
check("and it is still a single face", len(preview.data.polygons) == 1,
      len(preview.data.polygons))

# Positions, not just counts: a neighbour spreads its N segments evenly, so
# matching the count without the spacing would still leave a crack.
xs = sorted(v.co.x for v in preview.data.vertices if abs(v.co.y) < 1e-6)
check("the matched side carries one vertex per segment boundary",
      len(xs) == EXPECTED + 1, xs)
check("evenly spaced, like the grid it meets -- matching the count alone "
      "would still leave a crack",
      all(abs(xs[i] - i * 4.0 / EXPECTED) < 1e-5 for i in range(len(xs))), xs)

# --- and the automatic path does the same without being asked ---
state.side_overrides = ""
state.auto_match_neighbours = True
pr.operators.regenerate_active_preview(bpy.context)
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("Match Committed Neighbours picks the same side up on its own",
      len(preview.data.vertices) == plain_verts + EXPECTED - 1,
      len(preview.data.vertices))

state.auto_match_neighbours = False
pr.operators.regenerate_active_preview(bpy.context)
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("turning it off goes back to the curvature rule",
      len(preview.data.vertices) == plain_verts, len(preview.data.vertices))
state.auto_match_neighbours = True

# --- committing must register what was built, not what curvature said ---
pr.operators.regenerate_active_preview(bpy.context)
bpy.ops.retop.commit_patch()
result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
registry = pr.mesh_build.get_span_registry(result)
check("the matched count is what gets registered for the next neighbour",
      registry.get(pr.mesh_build._span_key(0, 1)) == EXPECTED, registry)


# ===========================================================================
# Housekeeping: the picker is per patch
# ===========================================================================
pr.operators.set_active_patch(bpy.context, obj, 2)
check("picking another patch drops the previous overrides",
      state.side_overrides == "", state.side_overrides)
bpy.ops.retop.clear_preview()

pr.operators.end_session(bpy.context)
check("ending the session clears the side cache", pr.sidematch.active_sides() == [])
check("and forgets the hover", state.hovered_side == -1)
# match_mode is a preference, not patch state: it is on by default and survives
# a session, so the highlight is there again next time without re-arming it.
check("but keeps the highlight preference", state.match_mode is True)


# ===========================================================================
# A side running against TWO committed patches
#
# This is what refused to match in the field. Filtering the committed vertices
# down to the *majority* neighbour handed back half a side's worth of points,
# which then failed endpoint coverage and reported "no committed neighbour" on
# a side that was visibly, fully bordered by retopology.
# ===========================================================================
verts2 = [
    (0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (4.0, 0.0, 0.0),      # 0,1,2 shared edge
    (4.0, 3.0, 0.0), (0.0, 3.0, 0.0),                        # 3,4 top
    (0.0, -1.0, 0.0), (2.0, -1.0, 0.0), (4.0, -1.0, 0.0),    # 5,6,7 bottom
]
t_top = [(0, 1, 4), (1, 3, 4), (1, 2, 3)]     # face 1: one side spanning 0->2
t_left = [(5, 6, 1), (5, 1, 0)]               # face 2: under 0->1
t_right = [(6, 7, 2), (6, 2, 1)]              # face 3: under 1->2

mesh2 = bpy.data.meshes.new("TwoNeighbourMesh")
mesh2.from_pydata(verts2, [], t_top + t_left + t_right)
mesh2.update()
mesh2["groups"] = [
    0, len(t_top) * 3,
    len(t_top) * 3, len(t_left) * 3,
    (len(t_top) + len(t_left)) * 3, len(t_right) * 3,
]
mesh2["face_ids"] = [1, 2, 3]

obj2 = bpy.data.objects.new("TwoNeighbourObj", mesh2)
bpy.context.collection.objects.link(obj2)
bpy.context.view_layer.objects.active = obj2
pr.operators.enter_session_object(bpy.context, obj2)

state.ngon_mode = False
for face_id in (2, 3):
    pr.operators.set_active_patch(bpy.context, obj2, face_id)
    state.span_u = 2
    state.span_v = 2
    bpy.ops.retop.commit_patch()
check("both neighbours are committed", state.committed_patch_count == 2,
      state.committed_patch_count)

pr.operators.set_active_patch(bpy.context, obj2, 1)
references = pr.sidematch.active_sides()
bottom = [reference for reference in references
          if all(abs((reference.points[i]).y) < 1e-6
                 for i in range(len(reference.points)))]
check("the top patch has a side lying on the shared edge", len(bottom) == 1,
      len(bottom))
side = bottom[0]
check("it spans both neighbours, not just one",
      abs(side.points[0].x - 0.0) < 1e-6 and abs(side.points[-1].x - 4.0) < 1e-6,
      f"{side.points[0].x} .. {side.points[-1].x}")
check("and it can be matched -- the whole side is covered", side.available,
      side.reason)
check("picking up every committed vertex along it, from both patches",
      side.span == 4, side.span)

adopted = pr.operators.adopt_side_reference(bpy.context, side.index)
check("adopting it works", adopted is not None, adopted)
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
xs = sorted(round(v.co.x, 5) for v in preview.data.vertices if abs(v.co.y) < 1e-6)
check("and the patch lands on both neighbours' vertices",
      xs == [0.0, 1.0, 2.0, 3.0, 4.0], xs)

# A side with nothing committed along it must still say so, and say why.
free = [reference for reference in references if not reference.available]
check("the untouched sides are still refused", len(free) >= 1, len(free))
check("with a reason, not silence", all(reference.reason for reference in free),
      [reference.reason for reference in free])

pr.operators.end_session(bpy.context)


# ===========================================================================
# The match margin
#
# Two patches can be a little too far apart to find each other: a coarse
# neighbour whose chords sag off a curved boundary, two CAD edges tessellated
# slightly differently. Pointing at a side says which neighbour you mean, so
# the picker can reach further than the automatic path -- which fires without
# being asked and must never grab whatever happens to be nearby.
# ===========================================================================
import mathutils  # noqa: E402 -- only needed for this section

V = mathutils.Vector
straight = [V((0.0, 0.0, 0.0)), V((1.0, 0.0, 0.0)), V((2.0, 0.0, 0.0))]
DRIFT = 0.05  # 2.5% of the side's length

drifted = [V((0.0, DRIFT, 0.0)), V((1.0, DRIFT, 0.0)), V((2.0, DRIFT, 0.0))]

state.boundary_weld_distance = 1e-4
state.length_unit = 'M'

strict = pr.mesh_build.side_match_tolerance(state, straight)
check("the strict tolerance is float slack, nothing more", strict < 0.01, strict)

state.match_margin = 0.0
check("a zero margin is the strict tolerance",
      pr.mesh_build.side_match_tolerance(state, straight, margin=True) == strict)

state.match_margin = 5.0
generous = pr.mesh_build.side_match_tolerance(state, straight, margin=True)
check("5% of a 2-unit side reaches 0.1", abs(generous - 0.1) < 1e-9, generous)
check("and the margin only ever widens, never narrows", generous > strict)

# A margin says how far *off* the side a vertex may sit. It must not also
# become how close two of them have to be to count as one: at 5% of a 2-unit
# side the margin is 0.1, and the neighbour's own vertices are 1 apart... but
# on a real part the two numbers cross, and every second vertex was swallowed
# as a duplicate -- 61 points came back as 31, which is the zigzag band in the
# report. `merge` is that second question, answered by the weld distance.
dense = [V((i * 0.05, 0.0, 0.0)) for i in range(41)]
dense_side = [V((0.0, 0.0, 0.0)), V((2.0, 0.0, 0.0))]
wide = 0.2  # wider than the neighbour's 0.05 spacing, as a real margin is
swallowed, _reason = pr.mesh_build.match_side_to_points(dense, dense_side, wide)
check("deduping at the margin swallows the neighbour's own vertices",
      swallowed is not None and len(swallowed) < len(dense), len(swallowed or []))
kept, _reason = pr.mesh_build.match_side_to_points(
    dense, dense_side, wide, merge=strict)
check("deduping at the weld distance keeps every one of them",
      kept is not None and len(kept) == len(dense), len(kept or []))

# And the second row of the neighbour's grid, a cell behind the shared edge,
# is not the edge under the cursor. Only a *gap* tells them apart: within one
# row the distances vary smoothly, which is the drift the margin exists for.
second_row = [V((i * 0.05, 0.14, 0.0)) for i in range(41)]
rows, _reason = pr.mesh_build.match_side_to_points(
    dense + second_row, dense_side, wide, merge=strict)
check("a match takes the row on the side, not the one behind it",
      rows is not None and len(rows) == len(dense), len(rows or []))
check("and it is the near row it kept",
      rows is not None and all(abs(point.y) < 1e-9 for point in rows))

# A single row drifted as a whole is still one row, however far it has moved:
# the distances climb smoothly, so there is no gap to cut at.
sagging = [V((i * 0.05, 0.02 + 0.001 * i, 0.0)) for i in range(41)]
sagged, _reason = pr.mesh_build.match_side_to_points(
    sagging, dense_side, wide, merge=strict)
check("a row that drifts gradually is kept whole",
      sagged is not None and len(sagged) == len(sagging), len(sagged or []))

check("a neighbour drifted off the side is out of strict reach",
      pr.mesh_build.match_side_to_points(drifted, straight, strict)[0] is None,
      pr.mesh_build.match_side_to_points(drifted, straight, strict)[1])
found, reason = pr.mesh_build.match_side_to_points(drifted, straight, generous)
check("but within the margin", found is not None, reason)
check("and it hands back the neighbour's own points, drift included",
      found is not None and all(abs(point.y - DRIFT) < 1e-9 for point in found),
      None if found is None else [round(p.y, 4) for p in found])

state.match_margin = 1.0  # 0.02 -- narrower than the drift
check("a margin below the drift still refuses",
      pr.mesh_build.match_side_to_points(
          drifted, straight,
          pr.mesh_build.side_match_tolerance(state, straight, margin=True))[0] is None)

# The margin is scale-free: it is a share of the side, so it means the same
# thing on a 2 mm fillet and a 2 m panel.
state.match_margin = 5.0
tiny = [V((0.0, 0.0, 0.0)), V((0.002, 0.0, 0.0))]
check("5% of a 2 mm side is 0.1 mm, not 0.1 m",
      abs(pr.mesh_build.side_match_tolerance(state, tiny, margin=True) - 0.0001) < 1e-9,
      pr.mesh_build.side_match_tolerance(state, tiny, margin=True))
state.match_margin = 5.0

# --- and the margin belongs to the *patch*, not to each side ---
#
# A neighbour's drift is an absolute distance. Scaling the margin by the side
# being matched gave a short side a tiny reach, so a stub between two retopped
# faces refused while the long side beside it matched without trouble. Every
# side of one patch gets the same reach: the longest side's.
short = [V((0.0, 0.0, 0.0)), V((0.1, 0.0, 0.0))]
own_scale = pr.mesh_build.side_match_tolerance(state, short, margin=True)
patch_scale = pr.mesh_build.side_match_tolerance(
    state, short, margin=True, reference_length=2.0)
check("a short side's own reach is tiny", own_scale < 0.01, own_scale)
check("but the patch's reach is the same for every side of it",
      abs(patch_scale - 0.1) < 1e-9, patch_scale)

drifted_short = [V((0.0, DRIFT, 0.0)), V((0.05, DRIFT, 0.0)), V((0.1, DRIFT, 0.0))]
check("so a short side can no longer be out of reach of a neighbour the long "
      "one reaches",
      pr.mesh_build.match_side_to_points(drifted_short, short, patch_scale)[0]
      is not None,
      pr.mesh_build.match_side_to_points(drifted_short, short, patch_scale)[1])
check("which it was when the reach was its own",
      pr.mesh_build.match_side_to_points(drifted_short, short, own_scale)[0] is None)

# One point is not something to follow, and says so rather than "no neighbour":
# a side shorter than the neighbour's vertex spacing genuinely has nothing.
# A pool with plenty in it, but only one point anywhere near this side --
# not the same thing as an empty pool, and it should not read like one.
lone = pr.mesh_build.match_side_to_points(
    [V((0.05, DRIFT, 0.0)), V((9.0, 9.0, 0.0)), V((9.5, 9.0, 0.0))],
    short, patch_scale)
check("a single committed vertex is refused with its own reason",
      lone[0] is None and "one committed vertex" in lone[1], lone[1])

state.match_margin = 2.0

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
