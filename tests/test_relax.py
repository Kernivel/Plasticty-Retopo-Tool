"""Run inside Blender: blender --background --python tests/test_relax.py

The interior relaxation (`geometry.relax_interior_points`): the pass that runs
after a generator has built a patch and evens out its cells without moving its
boundary.

Three things are pinned, and each of them is a way the feature could be worse
than useless rather than merely ineffective.

**The boundary does not move, at all.** Not "hardly moves": a corner is welded
to its neighbours *by identity* and every other boundary point by proximity at
a tolerance far below a cell, so a relaxation that nudged them would open the
cracks that the whole matching machinery exists to close. The check is exact
equality, not a tolerance.

**Nothing leaves the surface.** The step is tangential and the projection puts
it back, every pass -- iterate without that and the patch shrinks towards the
chords between its vertices, which is precisely the deviation this addon is
measured by.

**A patch it cannot improve comes back untouched.** Every move has to raise the
worst cell it touches, so a grid that is already regular is returned exactly as
the generator built it. Without that guard the relaxation is a trade -- measured
across the fixture, the unguarded version improved four shapes' cell quality and
made three others' worse -- and would have to be a per-part setting rather than
a default.

The pass also *stops* at `RELAX_QUALITY_TARGET` rather than smoothing on: a cell
twice as long as it is wide is an ordinary retopology cell, and only what is
worse than that is a defect. That is what keeps it affordable on every hover --
only the vertices touching a bad cell are tried at all.
"""
import os
import sys
import importlib

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy
import mathutils
from mathutils.bvhtree import BVHTree

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
geometry = pr.geometry

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


N = 5  # a 4x4 grid of cells


def build_grid(interior=None):
    """A unit grid on z=0. `interior(k, j)` places the free vertices; the
    default is where a Coons patch would put them.
    """
    verts = []
    for j in range(N):
        for k in range(N):
            u, v = k / (N - 1), j / (N - 1)
            if interior is not None and 0 < j < N - 1 and 0 < k < N - 1:
                u, v = interior(k, j)
            verts.append(mathutils.Vector((u, v, 0.0)))
    faces = []
    for j in range(N - 1):
        for k in range(N - 1):
            a = j * N + k
            faces.append((a, a + 1, a + N + 1, a + N))
    boundary = [j * N + k for j in range(N) for k in range(N)
                if j in (0, N - 1) or k in (0, N - 1)]
    return verts, faces, boundary


# The surface the patch lies on, big enough that a projection never falls off
# its edge -- this is about the relaxation, not about the BVH.
PLANE = BVHTree.FromPolygons(
    [mathutils.Vector(p) for p in ((-2, -2, 0), (3, -2, 0), (3, 3, 0), (-2, 3, 0))],
    [(0, 1, 2), (0, 2, 3)])


def worst_cell(verts, faces):
    return min(geometry.cell_quality([verts[i] for i in face]) for face in faces)


# ===========================================================================
# The quality measure the guard is built on
# ===========================================================================
square = [mathutils.Vector(p) for p in
          ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))]
check("a square scores 1", abs(geometry.cell_quality(square) - 1.0) < 1e-9,
      geometry.cell_quality(square))

sliver = [mathutils.Vector(p) for p in
          ((0, 0, 0), (1, 0, 0), (1, 0.01, 0), (0, 0.01, 0))]
check("a sliver scores near 0", geometry.cell_quality(sliver) < 0.02,
      geometry.cell_quality(sliver))

collapsed = [mathutils.Vector(p) for p in
             ((0, 0, 0), (1, 0, 0), (1, 0, 0), (0, 1, 0))]
check("a cell with two corners in one place scores 0",
      geometry.cell_quality(collapsed) == 0.0, geometry.cell_quality(collapsed))

# The directional half: a perfectly square cell that has turned over is not a
# good cell, and no measure of its angles can say so.
up = mathutils.Vector((0.0, 0.0, 1.0))
check("a square facing the reference still scores 1",
      abs(geometry.cell_quality(square, up) - 1.0) < 1e-9)
check("and the same square facing away scores 0",
      geometry.cell_quality(square, -up) == 0.0)


# ===========================================================================
# A patch whose interior has been bunched into one corner
#
# The shape a Coons grid takes against a concave boundary, reproduced directly:
# the boundary is a clean square, the interior is crowded into a corner, so
# every cell on the far side is a sliver.
# ===========================================================================
verts, faces, boundary = build_grid(lambda k, j: (0.12 * k, 0.12 * j))
kept = [verts[i].copy() for i in boundary]
before = worst_cell(verts, faces)

moved = geometry.relax_interior_points(verts, faces, boundary, PLANE, 16)
after = worst_cell(verts, faces)

check("the bunched interior really is bad to start with", before < 0.1, before)
check("every free vertex moved", moved == (N - 2) ** 2, moved)
check("and the worst cell is brought up to the target it works to",
      after >= geometry.RELAX_QUALITY_TARGET,
      f"{before:.4f} -> {after:.4f}, target {geometry.RELAX_QUALITY_TARGET}")

check("the boundary is exactly where it was -- not nearly",
      all((verts[i] - was).length == 0.0 for i, was in zip(boundary, kept)))
check("and nothing left the surface",
      max(abs(v.z) for v in verts) < 1e-9, max(abs(v.z) for v in verts))


# ===========================================================================
# A patch that is already regular
# ===========================================================================
verts, faces, boundary = build_grid()
snapshot = [v.copy() for v in verts]
moved = geometry.relax_interior_points(verts, faces, boundary, PLANE, 12)
check("an even grid is left completely alone", moved == 0, moved)
check("...to the last float",
      all((a - b).length == 0.0 for a, b in zip(verts, snapshot)))

# An even grid is also a fixed point of the averaging, so the check above would
# pass with no guard at all. What the guard actually does is tested directly:
# one cell, one candidate position, is this move taken or not.
square_face = [(0, 1, 2, 3)]
sliver_patch = [mathutils.Vector(p) for p in
                ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))]
check("a move that makes the worst cell better is taken",
      geometry._improves(
          [mathutils.Vector((0.0, 0.0, 0.0)), mathutils.Vector((1.0, 0.0, 0.0)),
           mathutils.Vector((1.0, 1.0, 0.0)), mathutils.Vector((0.02, 1.0, 0.0))],
          square_face, [0], 3, mathutils.Vector((0.0, 1.0, 0.0))))
check("a move that makes it worse is refused",
      not geometry._improves(
          sliver_patch, square_face, [0], 3,
          mathutils.Vector((0.9, 1.0, 0.0))))
check("and one that turns the cell over is refused however square it lands",
      not geometry._improves(
          sliver_patch, square_face, [0], 3,
          mathutils.Vector((0.0, -1.0, 0.0))))


# ===========================================================================
# The cases where there is nothing to do
# ===========================================================================
verts, faces, boundary = build_grid(lambda k, j: (0.12 * k, 0.12 * j))
snapshot = [v.copy() for v in verts]
check("zero passes is a no-op",
      geometry.relax_interior_points(verts, faces, boundary, PLANE, 0) == 0)
check("and with no BVH there is nothing safe to do, so nothing is done",
      geometry.relax_interior_points(verts, faces, boundary, None, 12) == 0)
check("neither touched a vertex",
      all((a - b).length == 0.0 for a, b in zip(verts, snapshot)))

# Every vertex pinned: a patch whose points are all on the boundary -- an n-gon,
# a one-cell grid -- has no interior to relax.
verts, faces, _ = build_grid()
check("a fully pinned patch relaxes nothing",
      geometry.relax_interior_points(
          verts, faces, list(range(len(verts))), PLANE, 12) == 0)


# ===========================================================================
# On a curved surface
#
# The projection is what keeps the patch on the surface; this is the case that
# tells a surface-constrained relaxation from a plain one.
# ===========================================================================
RADIUS = 4.0


def on_sphere(point):
    return point.normalized() * RADIUS


sphere_verts = []
sphere_faces = []
STEPS = 12
for j in range(STEPS + 1):
    for k in range(STEPS + 1):
        u = -0.6 + 1.2 * k / STEPS
        v = -0.6 + 1.2 * j / STEPS
        sphere_verts.append(on_sphere(mathutils.Vector((u, v, 1.0))))
for j in range(STEPS):
    for k in range(STEPS):
        a = j * (STEPS + 1) + k
        sphere_faces.append((a, a + 1, a + STEPS + 2, a + STEPS + 1))
SPHERE = BVHTree.FromPolygons(sphere_verts, [tuple(f[:3]) for f in sphere_faces]
                              + [tuple((f[0], f[2], f[3])) for f in sphere_faces])

# A patch on that sphere, its interior bunched the same way.
verts, faces, boundary = build_grid(lambda k, j: (0.12 * k, 0.12 * j))
verts = [on_sphere(mathutils.Vector((v.x - 0.5, v.y - 0.5, 1.0))) for v in verts]
kept = [verts[i].copy() for i in boundary]


def off_surface(points):
    return max(abs(p.length - RADIUS) for p in points)


free_indices = [i for i in range(len(verts)) if i not in set(boundary)]
geometry.relax_interior_points(verts, faces, boundary, SPHERE, 12)
check("the boundary of a curved patch is untouched too",
      all((verts[i] - was).length == 0.0 for i, was in zip(boundary, kept)))

# *On the surface* means on the tessellation the BVH was built from -- the only
# surface this addon has. Measuring against the analytic sphere instead would
# report the tessellation's own sagitta as a relaxation error.
worst_gap = max(SPHERE.find_nearest(verts[i])[3] for i in free_indices)
check("and every relaxed vertex sits on the surface it was projected onto",
      worst_gap < 1e-6, worst_gap)
check("which is not the same as having stayed put",
      max((verts[i] - on_sphere(mathutils.Vector((0.12 * (i % N) - 0.5,
                                                  0.12 * (i // N) - 0.5, 1.0)))).length
          for i in free_indices) > 1e-3)
check("and the patch did not shrink towards its chords",
      abs(sum(v.length for v in verts) / len(verts) - RADIUS) < 0.01,
      sum(v.length for v in verts) / len(verts))


print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
