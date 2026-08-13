"""Run inside Blender: blender --background --python tests/test_unwelded.py

Same 2-patch synthetic scene as bg_test_retop.py, but every triangle gets its
own private vertex copies (no shared vertex indices at all, even for
internal triangulation edges within the same patch) -- exactly how the real
Plasticity bridge exports faces. This is what actually broke on the user's
real CAD mesh; the fix is patch_data.build_weld_map / compute_boundary_loops
taking a weld_map argument.
"""
import os
import sys
import importlib

# Make the test runnable from any checkout: the addon package is the parent
# directory of tests/, so put its parent on sys.path and import it by folder
# name (the hyphen means it can only be imported via import_module).
_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import math


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


N = 4


def grid_pos(i, j):
    x, y = i, j
    z = 0.4 * math.sin(x / N * math.pi) * math.sin(y / N * math.pi)
    return (x, y, z)


verts = []
tris = []  # each entry: 3 raw vertex indices, always freshly appended (no reuse)


def add_tri(p0, p1, p2):
    base = len(verts)
    verts.extend([p0, p1, p2])
    tris.append((base, base + 1, base + 2))


patch_a_tri_count = 0
for j in range(N):
    for i in range(N):
        p00 = grid_pos(i, j)
        p10 = grid_pos(i + 1, j)
        p11 = grid_pos(i + 1, j + 1)
        p01 = grid_pos(i, j + 1)
        add_tri(p00, p10, p11)
        add_tri(p00, p11, p01)
        patch_a_tri_count += 2

apex = (N / 2, N + 2.0, 1.9)
patch_b_tri_count = 0
for i in range(N):
    p_a = grid_pos(i, N)
    p_b = grid_pos(i + 1, N)
    add_tri(p_b, p_a, apex)
    patch_b_tri_count += 1

groups = [0, patch_a_tri_count * 3, patch_a_tri_count * 3, patch_b_tri_count * 3]
face_ids = [101, 202]

mesh = bpy.data.meshes.new("UnweldedTestMesh")
mesh.from_pydata(verts, [], tris)
mesh.update()
mesh["groups"] = groups
mesh["face_ids"] = face_ids

obj = bpy.data.objects.new("UnweldedTestObj", mesh)
bpy.context.collection.objects.link(obj)

check("mesh has no accidental vertex reuse", len(mesh.vertices) == len(verts),
      f"expected {len(verts)}, got {len(mesh.vertices)}")

patches = patch_data.get_patches_with_boundaries(mesh)
check("two patches found", len(patches) == 2, f"got {list(patches.keys())}")

patch_a = patches.get(101)
patch_b = patches.get(202)

check("patch A single boundary loop", patch_a is not None and len(patch_a.boundary_loops) == 1,
      f"got {len(patch_a.boundary_loops) if patch_a else 'N/A'} loops")
expected_len_a = 4 * N
check("patch A boundary loop length", patch_a is not None and len(patch_a.boundary_loops[0]) == expected_len_a,
      f"expected {expected_len_a}, got {len(patch_a.boundary_loops[0]) if patch_a else 'N/A'}")

check("patch B single boundary loop", patch_b is not None and len(patch_b.boundary_loops) == 1,
      f"got {len(patch_b.boundary_loops) if patch_b else 'N/A'} loops")
expected_len_b = N + 2
check("patch B boundary loop length", patch_b is not None and len(patch_b.boundary_loops[0]) == expected_len_b,
      f"expected {expected_len_b}, got {len(patch_b.boundary_loops[0]) if patch_b else 'N/A'}")

positions = {v.index: v.co.copy() for v in mesh.vertices}
sides_a = sides_mod.split_into_sides(patch_a.boundary_loops[0], positions, angle_threshold=135.0) if patch_a else []
check("patch A yields 4 sides", len(sides_a) == 4, f"got {len(sides_a)}")

sides_b = sides_mod.split_into_sides(patch_b.boundary_loops[0], positions, angle_threshold=135.0) if patch_b else []
check("patch B yields 3 sides", len(sides_b) == 3, f"got {len(sides_b)}")

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
