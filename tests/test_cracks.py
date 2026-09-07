"""Run inside Blender: blender --background --python tests/test_cracks.py

Borders two committed patches failed to close.

The case is the one from the report: patch B is committed, patch A is matched
to it and welds, and then A is re-opened and its span typed over. Nothing about
B changes -- and B is the one left with a seam down the side it shares.

The side picker already says this *while* A is open (the side goes red), but
that warning leaves with the session. `mesh_build.crack_edges` is what says it
afterwards, and this pins both ends of it: a welded border reports nothing, or
the test proves nothing at all.
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

# ---------------------------------------------------------------------------
#  A (id 1) above the shared edge, B (id 2) below it. The same two-patch sheet
#  the matching tests use: one border, and both patches tessellate all of it.
# ---------------------------------------------------------------------------
verts = [
    (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0),
    (0.0, -1.0, 0.0), (4.0, -1.0, 0.0),
]
a0, a1, a2, a3, b0, b1 = range(6)
tris_a = [(a0, a1, a2), (a0, a2, a3)]
tris_b = [(b0, b1, a1), (b0, a1, a0)]

mesh = bpy.data.meshes.new("CrackMesh")
mesh.from_pydata(verts, [], tris_a + tris_b)
mesh.update()
mesh["groups"] = [0, len(tris_a) * 3, len(tris_a) * 3, len(tris_b) * 3]
mesh["face_ids"] = [1, 2]

obj = bpy.data.objects.new("CrackObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

pr.operators.enter_session_object(bpy.context, obj)
state.ngon_mode = False
state.auto_match_neighbours = True


def cracks():
    return pr.mesh_build.crack_edges(obj)


def pairs():
    return sorted(tuple(sorted((owner, other))) for owner, other, _points in cracks())


# ===========================================================================
# One patch committed: a border with nothing on the far side is not a crack
# ===========================================================================
pr.operators.set_active_patch(bpy.context, obj, 2)
state.span_u = 3
state.span_v = 3
bpy.ops.retop.commit_patch()
check("B is committed", state.committed_patch_count == 1, state.committed_patch_count)
# B's shared side is wide open -- there is simply no patch across it yet, which
# is what every border looks like until the model is finished. Reporting that
# would paint the frontier of the work red on every part.
check("a border with only one side committed is not a crack", cracks() == [], pairs())

# ===========================================================================
# Both committed and welded: still nothing
# ===========================================================================
pr.operators.set_active_patch(bpy.context, obj, 1)
bpy.ops.retop.commit_patch()
check("A is committed too", state.committed_patch_count == 2, state.committed_patch_count)

check("automatic matching welded the two along the shared side",
      cracks() == [], pairs())

# ===========================================================================
# ...then A's span is typed over, which is what breaks it
# ===========================================================================
pr.operators.set_active_patch(bpy.context, obj, 1)
check("re-opening A finds it committed", state.editing_committed)
# Whichever direction runs along the shared side, one of these is it. Changing
# the count is how the user says "don't weld here" -- `_honours` drops the
# match -- so this is the gesture from the report, not a contrived one.
state.span_u = 7
state.span_v = 7
bpy.ops.retop.commit_patch()

broken = pairs()
check("the border is reported as cracked", broken == [(1, 2)], broken)
check("and it is one edge, not one per boundary segment", len(cracks()) == 1, len(cracks()))

owner, other, polyline = cracks()[0]
check("the crack carries both patch ids", {owner, other} == {1, 2}, (owner, other))
check("and a polyline to draw", len(polyline) >= 2, len(polyline))
# It is the CAD edge, not either patch's own row: both rows sag off it by
# different amounts, which is the very thing being reported.
on_shared_edge = all(abs(point.y) < 1e-6 and -1e-6 <= point.x <= 4.0 + 1e-6
                     for point in polyline)
check("drawn along the shared CAD edge itself", on_shared_edge,
      [tuple(round(v, 3) for v in point) for point in polyline])

# The dashes are geometry, so they must actually be shorter than the edge --
# a "dashed" line that emits one segment per span is a solid one.
dashed = pr.mesh_build.crack_segments(obj, 0.25)
check("the overlay gets dashes, not one long segment", len(dashed) >= 4, len(dashed))
check("and they are pairs, for a LINES batch", len(dashed) % 2 == 0, len(dashed))
total_drawn = sum((dashed[i + 1] - dashed[i]).length for i in range(0, len(dashed), 2))
check("covering less than the whole edge", total_drawn < 4.0, total_drawn)

# ===========================================================================
# Which border an open edge belongs to
#
# The rule that decides it, on geometry built for the purpose. This is where
# the first version went wrong: it asked "is there an open edge within reach of
# this point on the border", and the reach has to be about the size of a
# retopology cell -- which on a bevelled part is also the distance to the next
# border along. Perfectly welded borders came back cracked because the open
# rows of the borders either side of them were within reach.
# ===========================================================================
import mathutils                                                    # noqa: E402
from mathutils.kdtree import KDTree                                 # noqa: E402

V = mathutils.Vector
#        (0,1)
#          |          border Y (patches 1 and 3)
#          |
# (0,0) ---+--- (1,0)  border X (patches 1 and 2), meeting Y at the origin
border_x = (1, 2, [V((0.0, 0.0, 0.0)), V((1.0, 0.0, 0.0))])
border_y = (1, 3, [V((0.0, 0.0, 0.0)), V((0.0, 1.0, 0.0))])
borders = [border_x, border_y]
near = 0.2
tree, sample_owner, spans = pr.mesh_build._shared_edge_index(borders, near, KDTree)


def along(start, finish, patch):
    edge = pr.mesh_build._border_along(
        tree, sample_owner, borders, V(start), V(finish), patch, near)
    return None if edge is None else (borders[edge][0], borders[edge][1])


check("an edge lying on a border belongs to it",
      along((0.2, 0.0, 0.0), (0.5, 0.0, 0.0), 1) == (1, 2),
      along((0.2, 0.0, 0.0), (0.5, 0.0, 0.0), 1))
# The one that broke it: an edge *leaving* the junction. It touches border X at
# the origin, and the whole of it lies along border Y.
check("an edge leaving a junction belongs to the border it follows, not the "
      "one it touches",
      along((0.0, 0.0, 0.0), (0.0, 0.5, 0.0), 1) == (1, 3),
      along((0.0, 0.0, 0.0), (0.0, 0.5, 0.0), 1))
# A whole border committed as one edge: both its ends are junctions, so asking
# the ends which border it lies along answers with either of them. Asking its
# interior answers correctly -- and a coarse patch does exactly this.
check("an edge spanning a whole border still belongs to it",
      along((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 1) == (1, 2),
      along((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 1))
check("an edge along a border of another patch belongs to nothing here",
      along((0.2, 0.0, 0.0), (0.5, 0.0, 0.0), 9) is None,
      along((0.2, 0.0, 0.0), (0.5, 0.0, 0.0), 9))
check("and one out in the open belongs to nothing",
      along((0.5, 0.9, 0.0), (0.8, 0.9, 0.0), 1) is None,
      along((0.5, 0.9, 0.0), (0.8, 0.9, 0.0), 1))
# Patch 3 is not party to border X, so its row along X -- if it somehow had one
# -- is not X's evidence. Only the two patches of a border can crack it.
check("a border only ever hears from its own two patches",
      along((0.2, 0.0, 0.0), (0.5, 0.0, 0.0), 3) is None,
      along((0.2, 0.0, 0.0), (0.5, 0.0, 0.0), 3))

# ===========================================================================
# What the overlay reads
#
# Not the draw callbacks -- headless there is no GPU context to batch into,
# and `tests/test_overlay.py` already covers those for names that do not
# exist. These are the parts that decide *what* gets drawn, which is where a
# crack that is real can still fail to appear.
# ===========================================================================
check("the overlay finds the session's source to scan",
      pr.overlay._crack_source(state) is obj)
check("and a model extent to size the dashes by",
      pr.overlay._crack_extent(obj) > 0.0, pr.overlay._crack_extent(obj))
# The tooltip needs a pointer, and a draw handler has no event to read one
# from -- the modal leaves it in `overlay.cursor_window`, which is None the
# moment the pointer leaves the viewport. That is not a failure to report.
pr.overlay.cursor_window = None
check("with no pointer, nothing is named",
      pr.overlay._crack_under_cursor(bpy.context, state, None) is None)
# ===========================================================================
# ...and matching it again closes it
# ===========================================================================
pr.operators.set_active_patch(bpy.context, obj, 1)
references = pr.sidematch.active_sides()
shared = next((r for r in references if r.available), None)
check("A's shared side can see the neighbour again", shared is not None)
if shared is not None:
    pr.operators.adopt_side_reference(bpy.context, shared.index)
    bpy.ops.retop.commit_patch()
    check("re-matching it closes the crack", cracks() == [], pairs())

pr.operators.end_session(bpy.context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
