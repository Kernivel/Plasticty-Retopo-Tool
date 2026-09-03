"""Run inside Blender: blender --background --python tests/test_tjunction.py

Two patches sharing one CAD edge that each tessellated *differently* -- the
finer one drops a vertex in the middle of the coarser one's segment. That is a
T-junction along a patch border, and it is what a real Plasticity part does:
on one exported object, 2327 of 4857 boundary segments failed to find their
opposite half-edge this way.

The consequence is not a quiet degradation. A segment with no opposite reports
no neighbour at all, `detect_topological_corners` fires wherever the neighbour
changes, and the border therefore reads as a string of phantom B-rep vertices
-- which is what picks the generator, so the patch comes out filled by the
wrong one.

Both halves are asserted here. The plain half-edge pairing must still fail on
this mesh, or the test proves nothing about the fallback; and `analyse`, which
runs `resolve_neighbours_by_geometry` after it, must name the neighbour on
every segment and leave the two genuine junctions.
"""
import importlib
import os
import sys

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
patch_data = pr.patch_data
sides_mod = pr.sides

FAILURES = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


FACE_A = 101
FACE_B = 202

# Patch A covers x 0..1, patch B covers x 1..2, both y 0..2. They share the
# edge x == 1, and they sample it differently: A at y 0, 1, 2 and B at y 0,
# 0.5, 1, 2. Only the stretch y 1..2 is sampled the same on both sides, so
# exactly one of A's two segments finds its opposite -- the alternation the
# real part shows, rather than a border that is uniformly unpaired.
A_FAN = [
    ((0, 0), (1, 0), (1, 1)),
    ((0, 0), (1, 1), (1, 2)),
    ((0, 0), (1, 2), (0, 2)),
]
B_FAN = [
    ((2, 0), (2, 2), (1, 2)),
    ((2, 0), (1, 2), (1, 1)),
    ((2, 0), (1, 1), (1, 0.5)),
    ((2, 0), (1, 0.5), (1, 0)),
]


def build_mesh():
    """The two patches as a triangle soup: every triangle its own vertices,
    which is how the bridge writes them.
    """
    verts = []
    tris = []
    groups = []
    face_ids = []

    for face_id, fan in ((FACE_A, A_FAN), (FACE_B, B_FAN)):
        loop_start = len(tris) * 3
        for (x0, y0), (x1, y1), (x2, y2) in fan:
            base = len(verts)
            verts.extend([(x0, y0, 0.0), (x1, y1, 0.0), (x2, y2, 0.0)])
            tris.append((base, base + 1, base + 2))
        groups.extend([loop_start, len(fan) * 3])
        face_ids.append(face_id)

    mesh = bpy.data.meshes.new("TJunction")
    mesh.from_pydata(verts, [], tris)
    mesh.update()
    mesh["groups"] = groups
    mesh["face_ids"] = face_ids
    return mesh


mesh = build_mesh()

# --- the pairing on its own, which is what the fallback exists to rescue ----

patches, face_id_of_poly, _ids = patch_data.build_patches(mesh)
weld_map = patch_data.build_weld_map(mesh)
owners = patch_data.build_directed_owners(mesh, face_id_of_poly, weld_map)
for patch in patches.values():
    patch_data.compute_boundary_loops(
        mesh, patch, face_id_of_poly, weld_map, owners)

raw_a = patches[FACE_A].boundary_neighbours[0]
raw_unpaired = sum(1 for n in raw_a if n is None)
check("half-edge pairing leaves the differently tessellated segment unpaired",
      raw_unpaired == 4 and raw_a.count(FACE_B) == 1,
      f"neighbours {raw_a}")

raw_loop = patches[FACE_A].boundary_loops[0]
raw_junctions = sides_mod.detect_topological_corners(raw_loop, raw_a)
check("and that shows up as phantom junctions", len(raw_junctions) == 2,
      f"{len(raw_junctions)} junctions")

positions = {v.index: v.co.copy() for v in mesh.vertices}
raw_junction_points = sorted(
    tuple(round(c, 4) for c in positions[raw_loop[i]]) for i in raw_junctions)
check("one of them sitting mid-edge, where no CAD vertex is",
      (1.0, 1.0, 0.0) in raw_junction_points,
      f"{raw_junction_points}")

# --- the full parse, which runs the geometric fallback ---------------------

patch_data.invalidate(mesh)
analysis = patch_data.analyse(mesh)

for face_id, other in ((FACE_A, FACE_B), (FACE_B, FACE_A)):
    patch = analysis.patches[face_id]
    loop = patch.boundary_loops[0]
    neighbours = patch.boundary_neighbours[0]
    named = [n for n in neighbours if n is not None]
    check(f"face {face_id}: every shared segment names its neighbour",
          all(n == other for n in named) and len(named) == 2 + (face_id == FACE_B),
          f"neighbours {neighbours}")

    junctions = sides_mod.detect_topological_corners(loop, neighbours)
    points = sorted(
        tuple(round(c, 4) for c in analysis.positions[loop[i]]) for i in junctions)
    check(f"face {face_id}: exactly the two genuine B-rep vertices",
          points == [(1.0, 0.0, 0.0), (1.0, 2.0, 0.0)], f"{points}")

# --- and a border that is already paired must be left alone -----------------

resolved = patch_data.resolve_neighbours_by_geometry(
    analysis.patches, analysis.positions)
check("running the fallback again finds nothing left to do", resolved == 0,
      f"{resolved} resolved")

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
