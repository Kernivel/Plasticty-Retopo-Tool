"""Run inside Blender: blender --background --python tests/test_strip.py

A long strip that curves back on itself: a rounded slot, the wall of a bore,
a ribbon running round a feature. No vertex on its boundary is sharp enough for
the angle test, and it borders one single neighbour, so neither corner test
finds anything.

Falling back to four corners spread evenly by arc length is wrong here, and
visibly so: a strip's perimeter is dominated by its two long sides, so the
quarter points land in the *middle* of them. The "quad" handed to the Coons
patch is then half a long side plus half an end, and it comes out as a fan.

The boundary's shape is asked first instead (`sides.shape_corners`): turn
measured over a window rather than at a vertex, which reads a rounded end as
one feature instead of dozens of insignificant ones.
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


try:
    pr.unregister()
except Exception:
    pass
pr.register()

sides_mod = pr.sides
V = mathutils.Vector


def as_loop(points):
    """(loop indices, positions) for a closed boundary given as points."""
    positions = {i: V(p) for i, p in enumerate(points)}
    return list(range(len(points))), positions


# ---------------------------------------------------------------------------
# A stadium: two straight sides of length 4, capped by semicircles of radius 1.
# The classic strip. Its perimeter is 8 + 2*pi*1 ~ 14.3, so the ends are barely
# a fifth of it -- quarter points land squarely in the middle of the sides.
# ---------------------------------------------------------------------------
STRAIGHT, RADIUS, CAP_SEGMENTS, SIDE_SEGMENTS = 4.0, 1.0, 24, 40

points = []
for i in range(SIDE_SEGMENTS):
    points.append((STRAIGHT * i / SIDE_SEGMENTS, -RADIUS, 0.0))
for i in range(CAP_SEGMENTS):
    a = -math.pi / 2 + math.pi * i / CAP_SEGMENTS
    points.append((STRAIGHT + RADIUS * math.cos(a), RADIUS * math.sin(a), 0.0))
for i in range(SIDE_SEGMENTS):
    points.append((STRAIGHT * (1 - i / SIDE_SEGMENTS), RADIUS, 0.0))
for i in range(CAP_SEGMENTS):
    a = math.pi / 2 + math.pi * i / CAP_SEGMENTS
    points.append((RADIUS * math.cos(a), RADIUS * math.sin(a), 0.0))

loop, positions = as_loop(points)

check("no vertex of the strip is sharp enough to be a corner",
      sides_mod.detect_corners(loop, positions, 135.0) == [],
      sides_mod.detect_corners(loop, positions, 135.0))
check("and one neighbour all the way round gives no junction either",
      sides_mod.detect_topological_corners(loop, [1] * len(loop)) == [])

turns = sides_mod.shape_turns(loop, positions)
check("the shape reads flat along the straight sides",
      turns[SIDE_SEGMENTS // 2] < 5.0, turns[SIDE_SEGMENTS // 2])
check("and turns hard at the caps",
      turns[SIDE_SEGMENTS + CAP_SEGMENTS // 2] > 45.0,
      turns[SIDE_SEGMENTS + CAP_SEGMENTS // 2])

corners = sides_mod.shape_corners(loop, positions)
check("so the strip is read as two ends, not four quarters",
      len(corners) == 2, corners)


def x_of(index):
    return positions[loop[index]].x


check("and both corners sit on the caps, not mid-side",
      all(x_of(i) < 0.2 or x_of(i) > STRAIGHT - 0.2 for i in corners),
      [round(x_of(i), 2) for i in corners])
check("one at each end, not both at the same one",
      min(x_of(i) for i in corners) < 0.2
      and max(x_of(i) for i in corners) > STRAIGHT - 0.2,
      [round(x_of(i), 2) for i in corners])

resolved = sides_mod.resolve_corners(loop, positions, 135.0, [1] * len(loop), 'BOTH')
check("resolve_corners hands the shape's answer through", resolved == corners,
      f"{resolved} vs {corners}")

split = sides_mod.split_into_sides(loop, positions, corner_indices=resolved)
check("two corners split it into two sides", len(split) == 2, len(split))
generator = pr.generators.find_generator(len(split))
check("which is a Wedge -- a grid running along the strip",
      generator is not None and generator.name == "Wedge",
      generator.name if generator else None)

lengths = [sum((positions[b] - positions[a]).length for a, b in zip(side, side[1:]))
           for side in split]
check("and its two sides are the strip's two long runs, near enough equal",
      abs(lengths[0] - lengths[1]) < max(lengths) * 0.1,
      [round(length, 3) for length in lengths])

# ---------------------------------------------------------------------------
# A circle still has no shape to find, and still gets its four.
# ---------------------------------------------------------------------------
circle = [(math.cos(2 * math.pi * i / 48), math.sin(2 * math.pi * i / 48), 0.0)
          for i in range(48)]
circle_loop, circle_positions = as_loop(circle)
check("a circle turns the same everywhere, so it has no peaks",
      sides_mod.shape_corners(circle_loop, circle_positions) == [])
check("and still falls back to four, evenly spread",
      len(sides_mod.synthesise_corners(circle_loop, circle_positions)) == 4)


# ---------------------------------------------------------------------------
# A rounded rectangle has four ends, and should be read as four.
# ---------------------------------------------------------------------------
def rounded_rect(width, height, radius, per_arc=10, per_side=12):
    pts = []
    corners_at = [(width - radius, height - radius, 0.0),
                  (radius, height - radius, math.pi / 2),
                  (radius, radius, math.pi),
                  (width - radius, radius, 3 * math.pi / 2)]
    for cx, cy, start in corners_at:
        for i in range(per_arc + 1):
            a = start + math.pi / 2 * i / per_arc
            pts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), 0.0))
        nxt = corners_at[(corners_at.index((cx, cy, start)) + 1) % 4]
        ax = cx + radius * math.cos(start + math.pi / 2)
        ay = cy + radius * math.sin(start + math.pi / 2)
        bx = nxt[0] + radius * math.cos(nxt[2])
        by = nxt[1] + radius * math.sin(nxt[2])
        for i in range(1, per_side):
            pts.append((ax + (bx - ax) * i / per_side,
                        ay + (by - ay) * i / per_side, 0.0))
    return pts


rect_loop, rect_positions = as_loop(rounded_rect(6.0, 4.0, 0.5))
rect_corners = sides_mod.shape_corners(rect_loop, rect_positions)
check("a rounded rectangle is read as four ends", len(rect_corners) == 4,
      rect_corners)
rect_generator = pr.generators.find_generator(
    len(sides_mod.split_into_sides(rect_loop, rect_positions,
                                   corner_indices=rect_corners)))
check("which makes it a Quad",
      rect_generator is not None and rect_generator.name == "Quad",
      rect_generator.name if rect_generator else None)


# ---------------------------------------------------------------------------
# End to end, through a real patch
# ---------------------------------------------------------------------------
verts = [(x, y, 0.0) for x, y, _z in points]
centre = len(verts)
verts.append((STRAIGHT / 2, 0.0, 0.0))
tris = [(i, (i + 1) % len(points), centre) for i in range(len(points))]

mesh = bpy.data.meshes.new("StripMesh")
mesh.from_pydata(verts, [], tris)
mesh.update()
mesh["groups"] = [0, len(tris) * 3]
mesh["face_ids"] = [8]

obj = bpy.data.objects.new("StripObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

prepared = pr.patchprep.prepare_patch(mesh, 8, 135.0, 0.0, 'BOTH')
check("the strip prepares into two sides", len(prepared.sides) == 2,
      len(prepared.sides))

pr.operators.enter_session_object(bpy.context, obj)
state = bpy.context.scene.plasticity_retop
state.ngon_mode = False
name, num_sides, _propagated = pr.operators.set_active_patch(bpy.context, obj, 8)
check("and generates as a Wedge", name == "Wedge", name)
check("with two sides", num_sides == 2, num_sides)

preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("producing real geometry", preview is not None
      and len(preview.data.polygons) > 0,
      len(preview.data.polygons) if preview else "none")
check("with no degenerate faces -- a fan is full of them",
      all(poly.area > 1e-9 for poly in preview.data.polygons),
      min(poly.area for poly in preview.data.polygons))

bpy.ops.retop.commit_patch()
result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
check("and it commits", result is not None and len(result.data.polygons) > 0,
      len(result.data.polygons) if result else "none")

pr.operators.end_session(bpy.context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
