"""Run inside Blender: blender --background --python tests/test_disc.py

A face bounded by one closed curve with no corner on it -- a disc, the flat
floor of a circular pocket, a rounded slot end.

These could not be picked at all. `sides.py` found no corner, so the patch had
a single side; `find_generator` accepts 2, 3, 4 or 5+ and has nothing that
takes one, so generation returned None, the hover silently failed, and the face
read as "not selectable" with no message anywhere. Four corners are synthesised
by arc length instead, which makes it a Quad.
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

# ---------------------------------------------------------------------------
# A tessellated circle: no vertex on it turns sharply enough to be a corner.
# Sampled unevenly on purpose -- a real mesher does not space them evenly, and
# picking every n//4th vertex would then bunch the corners where it was dense.
# ---------------------------------------------------------------------------
SEGMENTS = 48
angles = []
for i in range(SEGMENTS):
    t = i / SEGMENTS
    # squeeze the sampling into the first quarter
    angles.append(2 * math.pi * (t ** 1.6))

circle = [V((math.cos(a), math.sin(a), 0.0)) for a in angles]
positions = {i: circle[i] for i in range(SEGMENTS)}
loop = list(range(SEGMENTS))

check("no vertex of a circle is sharp enough to be a corner",
      sides_mod.detect_corners(loop, positions, 135.0) == [],
      sides_mod.detect_corners(loop, positions, 135.0))
check("and a single neighbour all the way round gives no junction either",
      sides_mod.detect_topological_corners(loop, [7] * SEGMENTS) == [])

corners = sides_mod.resolve_corners(loop, positions, 135.0, [7] * SEGMENTS, 'BOTH')
check("so four are synthesised", len(corners) == 4, corners)
check("which is what makes it a Quad",
      pr.generators.find_generator(len(corners)) is not None
      and pr.generators.find_generator(len(corners)).name == "Quad",
      pr.generators.find_generator(len(corners)))
check("and nothing at all accepted one side -- the bug",
      pr.generators.find_generator(1) is None)


def arc_between(a, b):
    """Arc length from corner index a to corner index b, walking forward."""
    total = 0.0
    i = a
    while i != b:
        total += (positions[loop[(i + 1) % SEGMENTS]] - positions[loop[i]]).length
        i = (i + 1) % SEGMENTS
    return total


quarters = [arc_between(corners[k], corners[(k + 1) % 4]) for k in range(4)]
circumference = sum(quarters)
check("the four sides are near-equal arcs, not equal vertex counts",
      all(abs(q - circumference / 4) < circumference * 0.05 for q in quarters),
      [round(q, 4) for q in quarters])

spacings = [(corners[(k + 1) % 4] - corners[k]) % SEGMENTS for k in range(4)]
check("their vertex counts differ, which is why arc length was the right rule",
      len(set(spacings)) > 1, spacings)

check("a corner the tests do find is still preferred over synthesising",
      sides_mod.resolve_corners(loop, positions, 135.0, [7] * 24 + [9] * 24,
                                'TOPOLOGY') != corners)


# ---------------------------------------------------------------------------
# End to end: a disc-bottomed pocket floor, picked and committed
# ---------------------------------------------------------------------------
verts = [(math.cos(a), math.sin(a), 0.0) for a in angles]
centre = len(verts)
verts.append((0.0, 0.0, 0.0))
tris = [(i, (i + 1) % SEGMENTS, centre) for i in range(SEGMENTS)]

mesh = bpy.data.meshes.new("DiscMesh")
mesh.from_pydata(verts, [], tris)
mesh.update()
mesh["groups"] = [0, len(tris) * 3]
mesh["face_ids"] = [42]

obj = bpy.data.objects.new("DiscObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

prepared = pr.patchprep.prepare_patch(mesh.copy() if False else mesh, 42, 135.0, 0.0, 'BOTH')
check("the disc prepares into four sides", len(prepared.sides) == 4,
      len(prepared.sides))
check("with four corners to weld by", len(prepared.corner_source_ids) == 4,
      prepared.corner_source_ids)

pr.operators.enter_session_object(bpy.context, obj)
state = bpy.context.scene.plasticity_retop

# N-gon first, while the patch is still uncommitted: a committed patch reopens
# as whatever it was committed as, so asking after the commit below would only
# be testing that rule again.
state.ngon_mode = True
name, _num_sides, _propagated = pr.operators.set_active_patch(bpy.context, obj, 42)
check("a disc is an n-gon too, when asked", name == "N-gon", name)
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("a single face following the circle", len(preview.data.polygons) == 1,
      len(preview.data.polygons))
check("with enough vertices to stay round",
      len(preview.data.vertices) >= 8, len(preview.data.vertices))
bpy.ops.retop.clear_preview()

state.ngon_mode = False
name, num_sides, _propagated = pr.operators.set_active_patch(bpy.context, obj, 42)
check("the disc is now pickable at all -- this returned None before",
      name is not None, name)
check("as a Quad", name == "Quad", name)
check("with four sides", num_sides == 4, num_sides)

preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("and it generates a grid", preview is not None and len(preview.data.polygons) > 0,
      len(preview.data.polygons) if preview else "none")
check("of span_u x span_v quads",
      len(preview.data.polygons) == state.span_u * state.span_v,
      f"{len(preview.data.polygons)} vs {state.span_u}x{state.span_v}")

bpy.ops.retop.commit_patch()
result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
check("committing works too", result is not None and len(result.data.polygons) > 0,
      len(result.data.polygons) if result else "none")

pr.operators.end_session(bpy.context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
