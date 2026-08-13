"""Run inside Blender: blender --background --python tests/test_retop.py

Builds a synthetic mesh with two Plasticity-style patches (a curved 4-sided
patch and a 3-sided patch sharing an edge with it), then exercises
patch_data / sides / generators exactly like the real addon would, without
needing any UI or the actual Plasticity bridge running.
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
import mathutils

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
patch_data = pr.patch_data
sides_mod = pr.sides
geometry = pr.geometry
generators = pr.generators

FAILURES = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Build a synthetic combined mesh: patch A (4-sided, curved, 4x4 grid) glued
# along its "top" edge to patch B (3-sided fan patch).
# ---------------------------------------------------------------------------
N = 4  # grid resolution for patch A
verts = []
tri_indices = []  # flat list of 3 * ntris
groups = []       # [loop_start, loop_count] pairs, in loop units (3 per tri)
face_ids = []

grid_index = {}
for j in range(N + 1):
    for i in range(N + 1):
        x = i
        y = j
        z = 0.4 * math.sin(x / N * math.pi) * math.sin(y / N * math.pi)
        grid_index[(i, j)] = len(verts)
        verts.append((x, y, z))

patch_a_tris = []
for j in range(N):
    for i in range(N):
        v00 = grid_index[(i, j)]
        v10 = grid_index[(i + 1, j)]
        v11 = grid_index[(i + 1, j + 1)]
        v01 = grid_index[(i, j + 1)]
        patch_a_tris.append((v00, v10, v11))
        patch_a_tris.append((v00, v11, v01))

loop_cursor = 0
groups.extend([loop_cursor, len(patch_a_tris) * 3])
face_ids.append(101)
for tri in patch_a_tris:
    tri_indices.extend(tri)
loop_cursor += len(patch_a_tris) * 3

# Patch B: a triangular fan patch glued along the top edge of patch A
# (the row j == N, i.e. vertices (0,N) .. (N,N)), extending to a new apex.
apex_index = len(verts)
apex_z = 0.4 + 1.5
verts.append((N / 2, N + 2.0, apex_z))

patch_b_tris = []
for i in range(N):
    v_a = grid_index[(i, N)]
    v_b = grid_index[(i + 1, N)]
    # winding chosen so this triangle's outward boundary matches a consistent
    # orientation with patch A along the shared edge (opposite direction).
    patch_b_tris.append((v_b, v_a, apex_index))

groups.extend([loop_cursor, len(patch_b_tris) * 3])
face_ids.append(202)
for tri in patch_b_tris:
    tri_indices.extend(tri)
loop_cursor += len(patch_b_tris) * 3

mesh = bpy.data.meshes.new("PlasticityTestMesh")
mesh.from_pydata(verts, [], patch_a_tris + patch_b_tris)
mesh.update()
mesh["groups"] = groups
mesh["face_ids"] = face_ids

obj = bpy.data.objects.new("PlasticityTestObj", mesh)
bpy.context.collection.objects.link(obj)

# ---------------------------------------------------------------------------
# 1. Patch parsing
# ---------------------------------------------------------------------------
patches = patch_data.get_patches_with_boundaries(mesh)

check("two patches found", len(patches) == 2, f"got {list(patches.keys())}")
patch_a = patches.get(101)
patch_b = patches.get(202)
check("patch A polygon count", patch_a is not None and len(patch_a.poly_indices) == len(patch_a_tris),
      f"got {len(patch_a.poly_indices) if patch_a else 'N/A'}")
check("patch B polygon count", patch_b is not None and len(patch_b.poly_indices) == len(patch_b_tris),
      f"got {len(patch_b.poly_indices) if patch_b else 'N/A'}")

check("patch A single boundary loop", patch_a is not None and len(patch_a.boundary_loops) == 1,
      f"got {len(patch_a.boundary_loops) if patch_a else 'N/A'} loops")
check("patch B single boundary loop", patch_b is not None and len(patch_b.boundary_loops) == 1,
      f"got {len(patch_b.boundary_loops) if patch_b else 'N/A'} loops")

expected_boundary_len_a = 4 * N  # perimeter vertex count of an NxN grid
check("patch A boundary loop length", patch_a is not None and len(patch_a.boundary_loops[0]) == expected_boundary_len_a,
      f"expected {expected_boundary_len_a}, got {len(patch_a.boundary_loops[0]) if patch_a else 'N/A'}")

expected_boundary_len_b = N + 2  # N+1 base verts + apex
check("patch B boundary loop length", patch_b is not None and len(patch_b.boundary_loops[0]) == expected_boundary_len_b,
      f"expected {expected_boundary_len_b}, got {len(patch_b.boundary_loops[0]) if patch_b else 'N/A'}")

positions = {v.index: v.co.copy() for v in mesh.vertices}

# ---------------------------------------------------------------------------
# 2. Side splitting / corner detection
# ---------------------------------------------------------------------------
sides_a = sides_mod.split_into_sides(patch_a.boundary_loops[0], positions, angle_threshold=135.0)
check("patch A yields 4 sides", len(sides_a) == 4, f"got {len(sides_a)}")

sides_b = sides_mod.split_into_sides(patch_b.boundary_loops[0], positions, angle_threshold=135.0)
check("patch B yields 3 sides", len(sides_b) == 3, f"got {len(sides_b)}")

# ---------------------------------------------------------------------------
# 3. Quad generator on patch A, with reprojection onto the curved surface
# ---------------------------------------------------------------------------
gen_quad = generators.find_generator(4)
check("quad generator resolved", gen_quad is not None and gen_quad.name == "Quad")

bvh_a = geometry.build_bvh_for_polygons(mesh, patch_a.poly_indices)
side_points_a = pr.generators.base.resolve_side_points(sides_a, positions)
span_settings = gen_quad.default_spans(side_points_a)
check("quad default spans reasonable", span_settings["span_u"] >= 1 and span_settings["span_v"] >= 1,
      str(span_settings))

# force a finer span than the source tessellation to make reprojection matter
span_settings = {"span_u": 8, "span_v": 8}
result_no_reproj = gen_quad.generate(side_points_a, span_settings, bvh=None)
result_reproj = gen_quad.generate(side_points_a, span_settings, bvh=bvh_a)

expected_verts = (span_settings["span_u"] + 1) * (span_settings["span_v"] + 1)
expected_faces = span_settings["span_u"] * span_settings["span_v"]
check("quad vert count", len(result_reproj.verts) == expected_verts,
      f"expected {expected_verts}, got {len(result_reproj.verts)}")
check("quad face count", len(result_reproj.faces) == expected_faces,
      f"expected {expected_faces}, got {len(result_reproj.faces)}")
check("quad faces are all quads", all(len(f) == 4 for f in result_reproj.faces))

# Reprojection should move at least some interior verts measurably closer to
# the true curved surface than the raw bilinear (planar-ish) blend.
def max_dist_to_surface(verts_list, bvh):
    max_d = 0.0
    for p in verts_list:
        hit = bvh.find_nearest(p)
        if hit and hit[0] is not None:
            max_d = max(max_d, (hit[0] - p).length)
    return max_d

dist_before = max_dist_to_surface(result_no_reproj.verts, bvh_a)
dist_after = max_dist_to_surface(result_reproj.verts, bvh_a)
check("reprojection reduces surface deviation", dist_after < dist_before,
      f"before={dist_before:.5f} after={dist_after:.5f}")
check("reprojected verts lie (near) exactly on surface", dist_after < 1e-4,
      f"after={dist_after:.6f}")

# ---------------------------------------------------------------------------
# 4. Triangle generator on patch B
# ---------------------------------------------------------------------------
gen_tri = generators.find_generator(3)
check("triangle generator resolved", gen_tri is not None and gen_tri.name == "Triangle")

bvh_b = geometry.build_bvh_for_polygons(mesh, patch_b.poly_indices)
side_points_b = pr.generators.base.resolve_side_points(sides_b, positions)
span = 5
result_tri = gen_tri.generate(side_points_b, {"span": span}, bvh=bvh_b)

expected_tri_faces = span * span
check("triangle face count", len(result_tri.faces) == expected_tri_faces,
      f"expected {expected_tri_faces}, got {len(result_tri.faces)}")
check("triangle faces are tri or quad", all(len(f) in (3, 4) for f in result_tri.faces))
n_tris = sum(1 for f in result_tri.faces if len(f) == 3)
check("triangle grid has exactly `span` triangles at the apex", n_tris == span,
      f"expected {span}, got {n_tris}")

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 5. Generator coverage beyond quads: Wedge (2 sides) and N-Side (5+).
# ---------------------------------------------------------------------------
import mathutils

check("2-sided patches resolve to Wedge",
      generators.find_generator(2) is not None and generators.find_generator(2).name == "Wedge",
      str(generators.find_generator(2)))
for n in (5, 6, 8):
    gen = generators.find_generator(n)
    check(f"{n}-sided patches resolve to N-Side",
          gen is not None and gen.name == "N-Side", f"got {gen.name if gen else None}")
check("4 sides still resolve to Quad, not N-Side",
      generators.find_generator(4).name == "Quad", generators.find_generator(4).name)
check("3 sides still resolve to Triangle, not N-Side",
      generators.find_generator(3).name == "Triangle", generators.find_generator(3).name)

# --- Wedge: a lens bounded by two arcs meeting at two corners ---
import math as _math
arc_top = [mathutils.Vector((t, 0.35 * _math.sin(_math.pi * t / 4.0), 0.0)) for t in
           [i * 4.0 / 8 for i in range(9)]]
arc_bottom = list(reversed([mathutils.Vector((t, -0.35 * _math.sin(_math.pi * t / 4.0), 0.0)) for t in
                            [i * 4.0 / 8 for i in range(9)]]))
gen_wedge = generators.find_generator(2)
wedge_spans = gen_wedge.default_spans([arc_top, arc_bottom])
check("wedge proposes a sane default span", wedge_spans["span_u"] >= 2, str(wedge_spans))

res_wedge = gen_wedge.generate([arc_top, arc_bottom], {"span_u": 6, "span_v": 2})
check("wedge faces are tris or quads", all(len(f) in (3, 4) for f in res_wedge.faces),
      str(sorted({len(f) for f in res_wedge.faces})))
check("wedge has no degenerate faces (no repeated vertex in a face)",
      all(len(set(f)) == len(f) for f in res_wedge.faces))
wedge_corner_ids = set(res_wedge.corner_local_indices)
check("wedge reports its 2 corners", len(wedge_corner_ids) == 2, str(res_wedge.corner_local_indices))
# the two tips must each be a single shared vertex, not a seam of duplicates
tip_a = res_wedge.verts[res_wedge.corner_local_indices[0]]
tip_b = res_wedge.verts[res_wedge.corner_local_indices[1]]
check("wedge tips sit at the two shared corners",
      (tip_a - arc_top[0]).length < 1e-6 and (tip_b - arc_top[-1]).length < 1e-6,
      f"a={tuple if False else tuple(tip_a)}, b={tuple(tip_b)}")

# --- N-Side: a regular hexagon, 6 sides ---
hex_corners = [mathutils.Vector((_math.cos(a), _math.sin(a), 0.0))
               for a in [i * _math.pi / 3.0 for i in range(6)]]
hex_sides = []
for i in range(6):
    a = hex_corners[i]
    b = hex_corners[(i + 1) % 6]
    hex_sides.append([a, (a + b) * 0.5, b])

gen_nside = generators.find_generator(6)
res_hex = gen_nside.generate(hex_sides, {"span": 2})
check("n-side output is all quads", all(len(f) == 4 for f in res_hex.faces),
      str(sorted({len(f) for f in res_hex.faces})))
n_boundary = 6 * 2  # sides * span
check("n-side emits one quad per boundary segment", len(res_hex.faces) == n_boundary,
      f"expected {n_boundary}, got {len(res_hex.faces)}")
check("n-side has no degenerate faces", all(len(set(f)) == 4 for f in res_hex.faces))
check("n-side reports one corner per side", len(res_hex.corner_local_indices) == 6,
      str(res_hex.corner_local_indices))
check("n-side marks its whole boundary ring",
      len(res_hex.boundary_local_indices) == n_boundary, str(len(res_hex.boundary_local_indices)))
check("n-side has one uv per vertex", len(res_hex.uvs) == len(res_hex.verts),
      f"{len(res_hex.uvs)} uvs vs {len(res_hex.verts)} verts")

# Every vertex must be used by at least one face (no orphans).
used = set()
for f in res_hex.faces:
    used.update(f)
check("n-side leaves no orphan vertices", len(used) == len(res_hex.verts),
      f"{len(used)} used of {len(res_hex.verts)}")

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
