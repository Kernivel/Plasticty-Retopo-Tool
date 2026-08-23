"""Run inside Blender: blender --background --python tests/test_weld_scope.py

The bridge tessellates each CAD face on its own, so the two faces meeting along
a B-rep edge each carry a copy of every vertex on it -- but the triangles
*inside* one face may already share their vertices natively. This builds that
half-welded case (patch A's interior shared, the A/B border duplicated) and
pins two things:

  * `weld_candidates` excludes the interior, so the KD-tree only ever sees the
    points that can actually have a twin;
  * the boundary loops that come out are the same ones the whole-mesh weld
    produced, which is the only reason narrowing it is allowed at all.

`tests/test_unwelded.py` covers the other end -- a soup with no native sharing
anywhere -- where `weld_candidates` must decline to filter and the old
behaviour must return unchanged.
"""
import os
import sys
import importlib
import math

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
patch_data = pr.patch_data

FAILURES = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


N = 4


def grid_pos(i, j):
    x, y = float(i), float(j)
    z = 0.4 * math.sin(x / N * math.pi) * math.sin(y / N * math.pi)
    return (x, y, z)


verts = []
tris = []

# --- patch A: an N x N grid whose triangles DO share their vertices ---------
grid_index = {}
for j in range(N + 1):
    for i in range(N + 1):
        grid_index[(i, j)] = len(verts)
        verts.append(grid_pos(i, j))

patch_a_tris = 0
for j in range(N):
    for i in range(N):
        v00 = grid_index[(i, j)]
        v10 = grid_index[(i + 1, j)]
        v11 = grid_index[(i + 1, j + 1)]
        v01 = grid_index[(i, j + 1)]
        tris.append((v00, v10, v11))
        tris.append((v00, v11, v01))
        patch_a_tris += 2

# --- patch B: a fan sharing A's j == N edge, with its OWN copies of it ------
# This is the duplication the bridge really produces: same positions, different
# vertex indices, because the two faces were tessellated separately.
rim = []
for i in range(N + 1):
    rim.append(len(verts))
    verts.append(grid_pos(i, N))

apex_index = len(verts)
verts.append((N / 2, N + 2.0, 1.9))

patch_b_tris = 0
for i in range(N):
    # Wound so B walks the shared edge the opposite way to A -- that
    # opposition is what makes a half-edge pair, and so what lets each patch
    # name the other across the border.
    tris.append((rim[i], rim[i + 1], apex_index))
    patch_b_tris += 1

mesh = bpy.data.meshes.new("WeldScopeTestMesh")
mesh.from_pydata(verts, [], tris)
mesh.update()
mesh["groups"] = [0, patch_a_tris * 3, patch_a_tris * 3, patch_b_tris * 3]
mesh["face_ids"] = [101, 202]

obj = bpy.data.objects.new("WeldScopeTestObj", mesh)
bpy.context.collection.objects.link(obj)

check("mesh built with the intended vertex count",
      len(mesh.vertices) == len(verts),
      f"expected {len(verts)}, got {len(mesh.vertices)}")

# --- the candidate set ------------------------------------------------------
# A sorted index array (numpy on any real Blender), not a set -- the counting
# behind it is all foreach_get + bincount, because doing it per triangle corner
# in Python cost more than the KD-tree it exists to shrink.
candidates = patch_data.weld_candidates(mesh)
check("candidates were narrowed at all", candidates is not None)
candidates = set(int(i) for i in candidates) if candidates is not None else None

interior = {grid_index[(i, j)]
            for j in range(1, N) for i in range(1, N)}
expected = len(mesh.vertices) - len(interior)

check("interior of patch A is excluded",
      candidates is not None and not (candidates & interior),
      f"{len(candidates & interior) if candidates else 'N/A'} interior verts leaked in")
check("every other vertex is a candidate",
      candidates is not None and len(candidates) == expected,
      f"expected {expected}, got {len(candidates) if candidates else 'N/A'}")

# --- the weld map itself ----------------------------------------------------
weld = patch_data.build_weld_map(mesh)
check("interior vertices map to themselves",
      all(weld[i] == i for i in interior))

positions = {v.index: v.co.copy() for v in mesh.vertices}
merged = sum(1 for i in range(len(weld)) if weld[i] != i)
check("the duplicated rim was merged", merged == N + 1,
      f"expected {N + 1} merged verts, got {merged}")
check("merged pairs are actually coincident",
      all((positions[i] - positions[weld[i]]).length < 1e-5
          for i in range(len(weld))))

# --- and the loops are unchanged -------------------------------------------
patches = patch_data.get_patches_with_boundaries(mesh)
check("two patches found", len(patches) == 2, f"got {sorted(patches.keys())}")

patch_a = patches.get(101)
patch_b = patches.get(202)

check("patch A single boundary loop",
      patch_a is not None and len(patch_a.boundary_loops) == 1,
      f"got {len(patch_a.boundary_loops) if patch_a else 'N/A'}")
check("patch A boundary loop length",
      patch_a is not None and len(patch_a.boundary_loops[0]) == 4 * N,
      f"expected {4 * N}, got "
      f"{len(patch_a.boundary_loops[0]) if patch_a else 'N/A'}")
check("patch B single boundary loop",
      patch_b is not None and len(patch_b.boundary_loops) == 1,
      f"got {len(patch_b.boundary_loops) if patch_b else 'N/A'}")
check("patch B boundary loop length",
      patch_b is not None and len(patch_b.boundary_loops[0]) == N + 2,
      f"expected {N + 2}, got "
      f"{len(patch_b.boundary_loops[0]) if patch_b else 'N/A'}")

# The whole point of welding: each patch must see the other across the shared
# edge, which is what the topological corner test and cad_display run on.
neighbours_a = patch_a.boundary_neighbours[0] if patch_a else []
neighbours_b = patch_b.boundary_neighbours[0] if patch_b else []
check("patch A sees patch B across the shared edge",
      sum(1 for n in neighbours_a if n == 202) == N,
      f"got {sum(1 for n in neighbours_a if n == 202)} of {N} segments")
check("patch B sees patch A across the shared edge",
      sum(1 for n in neighbours_b if n == 101) == N,
      f"got {sum(1 for n in neighbours_b if n == 101)} of {N} segments")

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
