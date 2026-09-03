"""Run inside Blender: blender --background --python tests/test_boundary_walk.py

A patch whose boundary carries a genuine edge *shorter than the weld epsilon*.

Real CAD parts have them: on one, the smallest features sat at 1e-5, exactly
where `build_weld_map` merges. Merging the two ends of a real mesh edge
destroys the triangle carrying it -- its two directed corners are then dropped
as `a == b` -- and a patch's directed boundary stops being balanced. The walk
in `compute_boundary_loops` runs into a dead end and hands back an *open
chain*; every reader closes a loop with `% n`, so that chain draws a chord from
its last vertex straight back to its first, across a face the model never
divided, and counts as an extra boundary loop besides. On one object 205 real
edges were collapsed and 101 of 245 loops came back open.

Two rules are pinned here. The weld must leave edge-joined vertices alone
however close they are -- while still merging the bridge's duplicated copies,
which is what it exists for. And the walk must return only loops that actually
closed, so a malformed patch loses a fragment of border rather than inventing
geometry across the whole part.
"""
import importlib
import os
import sys

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
patch_data = pr.patch_data

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


FACE_A = 11
FACE_B = 22
EPSILON = 1e-5
# Well inside the epsilon, so a weld that only looks at distance merges it.
TINY = 4e-6

# A: the unit square with a tiny step across its top right corner, fanned from
# the origin. B: the square beside it, sharing the edge x == 1.
P = {
    "a0": (0.0, 0.0), "a1": (1.0, 0.0), "a2": (1.0, 1.0),
    "a3": (1.0 - TINY, 1.0), "a4": (0.0, 1.0),
    "b0": (2.0, 0.0), "b1": (2.0, 1.0),
}
A_FAN = [("a0", "a1", "a2"), ("a0", "a2", "a3"), ("a0", "a3", "a4")]
B_FAN = [("b0", "b1", "a2"), ("b0", "a2", "a1")]


def build_mesh():
    """Every triangle gets its own vertex copies, as the bridge writes them."""
    verts, tris, groups, face_ids = [], [], [], []
    for face_id, fan in ((FACE_A, A_FAN), (FACE_B, B_FAN)):
        loop_start = len(tris) * 3
        for names in fan:
            base = len(verts)
            verts.extend([(P[n][0], P[n][1], 0.0) for n in names])
            tris.append((base, base + 1, base + 2))
        groups.extend([loop_start, len(fan) * 3])
        face_ids.append(face_id)

    mesh = bpy.data.meshes.new("BoundaryWalk")
    mesh.from_pydata(verts, [], tris)
    mesh.update()
    mesh["groups"] = groups
    mesh["face_ids"] = face_ids
    return mesh


mesh = build_mesh()
weld = patch_data.build_weld_map(mesh, EPSILON)


def welded_at(name):
    """The welded ids of every copy of point `name`."""
    target = (P[name][0], P[name][1], 0.0)
    return {weld[v.index] for v in mesh.vertices
            if all(abs(v.co[i] - target[i]) < TINY * 0.25 for i in range(3))}


a2 = welded_at("a2")
a3 = welded_at("a3")
check("the tiny edge survives the weld", a2.isdisjoint(a3),
      f"a2 {sorted(a2)} vs a3 {sorted(a3)} (gap {TINY:g} < epsilon {EPSILON:g})")
check("...and each end is one point, not several",
      len(a2) == 1 and len(a3) == 1, f"{len(a2)} / {len(a3)}")

# The point A and B both put at (1, 0): three separate copies, no edge between
# the copies, so the weld must still merge them -- that is what it is for.
check("the bridge's duplicated copies still weld", len(welded_at("a1")) == 1,
      f"{sorted(welded_at('a1'))}")

analysis = patch_data.analyse(mesh, weld_epsilon=EPSILON)
patch = analysis.patches[FACE_A]
check("patch A has one boundary loop, not a pile of fragments",
      len(patch.boundary_loops) == 1, f"{len(patch.boundary_loops)} loops")

loop = patch.boundary_loops[0] if patch.boundary_loops else []
check("...running round all five of its boundary vertices", len(loop) == 5,
      f"{len(loop)} verts")

# Every step of the loop, the closing one included, must be a half-edge the
# patch actually has. A fabricated closure is exactly the phantom chord.
present = set()
for poly_idx in patch.poly_indices:
    verts = [analysis.weld_map[vi] for vi in mesh.polygons[poly_idx].vertices]
    n = len(verts)
    for i in range(n):
        a, b = verts[i], verts[(i + 1) % n]
        if a != b:
            present.add((a, b))

n = len(loop)
fabricated = [i for i in range(n) if (loop[i], loop[(i + 1) % n]) not in present]
check("no step of the loop is invented", not fabricated,
      f"steps {fabricated} are not half-edges of the patch")

longest = max(((analysis.positions[loop[(i + 1) % n]]
                - analysis.positions[loop[i]]).length for i in range(n)),
              default=0.0)
check("so no segment cuts across the patch", longest <= 1.0 + 1e-9,
      f"longest segment {longest:.4f}")

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
