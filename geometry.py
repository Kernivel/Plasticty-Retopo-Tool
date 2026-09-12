"""Grid generation (transfinite / Coons interpolation) and surface
reprojection helpers, independent of any Blender operator/UI code so they can
be unit-exercised from a --background script.
"""
from typing import TYPE_CHECKING

import mathutils

if TYPE_CHECKING:
    # Imported for annotations only, so the two BVH helpers keep pulling
    # bvhtree in lazily the way they always have.
    import bpy
    from mathutils.bvhtree import BVHTree


def resample_polyline_by_arclength(
    points: list[mathutils.Vector], count: int
) -> list[mathutils.Vector]:
    """Resample an ordered polyline to exactly `count` points (count >= 2),
    evenly spaced by arc length, keeping the first and last points fixed.
    """
    if count < 2:
        raise ValueError("count must be >= 2")
    if len(points) == count:
        return list(points)

    seg_lengths = []
    total = 0.0
    for a, b in zip(points, points[1:]):
        d = (b - a).length
        seg_lengths.append(d)
        total += d

    if total < 1e-12:
        return [points[0].copy() for _ in range(count)]

    result = [points[0].copy()]
    target_step = total / (count - 1)
    seg_i = 0
    seg_acc = 0.0

    for k in range(1, count - 1):
        target = target_step * k
        while seg_i < len(seg_lengths) and seg_acc + seg_lengths[seg_i] < target:
            seg_acc += seg_lengths[seg_i]
            seg_i += 1
        if seg_i >= len(seg_lengths):
            result.append(points[-1].copy())
            continue
        remaining = target - seg_acc
        seg_len = seg_lengths[seg_i]
        t = 0.0 if seg_len < 1e-12 else remaining / seg_len
        a = points[seg_i]
        b = points[seg_i + 1]
        result.append(a.lerp(b, t))

    result.append(points[-1].copy())
    return result


def coons_patch_grid(
    side_bottom: list[mathutils.Vector],
    side_right: list[mathutils.Vector],
    side_top: list[mathutils.Vector],
    side_left: list[mathutils.Vector],
    span_u: int,
    span_v: int,
) -> list[list[mathutils.Vector]]:
    """Build a (span_u+1) x (span_v+1) grid of 3D points spanning a 4-sided
    patch, via bilinearly-blended Coons interpolation.

    Sides must be given walking around the patch boundary in order, already
    resampled:
      side_bottom : span_u+1 points, u=0..1 at v=0   (P00 -> P10)
      side_right  : span_v+1 points, v=0..1 at u=1   (P10 -> P11)
      side_top    : span_u+1 points, u=1..0 at v=1   (P11 -> P01), i.e. reversed u order
      side_left   : span_v+1 points, v=1..0 at u=0   (P01 -> P00), i.e. reversed v order

    Returns a list of rows (v index) of lists of points (u index):
    grid[v][u], both 0-indexed up to span_u / span_v.
    """
    nu = span_u + 1
    nv = span_v + 1

    c0 = side_bottom                          # C(u, 0)
    c1 = list(reversed(side_top))             # C(u, 1)
    d0 = list(reversed(side_left))            # C(0, v)
    d1 = side_right                           # C(1, v)

    p00 = c0[0]
    p10 = c0[-1]
    p01 = c1[0]
    p11 = c1[-1]

    grid = [[None] * nu for _ in range(nv)]

    for vi in range(nv):
        v = vi / span_v
        for ui in range(nu):
            u = ui / span_u

            ruled_u = c0[ui].lerp(c1[ui], v)
            ruled_v = d0[vi].lerp(d1[vi], u)
            bilinear_corners = (
                p00 * (1 - u) * (1 - v)
                + p10 * u * (1 - v)
                + p01 * (1 - u) * v
                + p11 * u * v
            )

            point = ruled_u + ruled_v - bilinear_corners
            grid[vi][ui] = point

    return grid


def fan_collapsed_grid(
    side_ab: list[mathutils.Vector],
    side_bc: list[mathutils.Vector],
    side_ca: list[mathutils.Vector],
) -> list[list[mathutils.Vector]]:
    """Build a triangular-domain grid for a 3-sided patch A-B-C by feeding a
    Coons quad solver a degenerate quad where one corner is repeated: quad
    corners (P00, P10, P11, P01) = (A, B, C, C).

    This is the standard "fan" strategy for filling a triangular patch with a
    regular grid: every row is a normal quad strip except the last, which
    degenerates into a fan of triangles meeting at apex C.

    side_ab : span_u+1 points, A -> B (becomes the Coons "bottom" side)
    side_bc : span_v+1 points, B -> C (becomes the Coons "right" side)
    side_ca : span_v+1 points, C -> A. This already matches the "P01 -> P00"
              (v=1..0 at u=0) convention coons_patch_grid expects for its left
              side verbatim -- do NOT reverse it. Must have the same point
              count as side_bc, since both run in the v direction of the
              collapsed quad.

    Returns grid[v][u] exactly like coons_patch_grid, where row v=span_v
    (the last row) is constant and equal to apex C.
    """
    if len(side_bc) != len(side_ca):
        raise ValueError("side_bc and side_ca must have the same point count (shared span)")

    span_u = len(side_ab) - 1
    span_v = len(side_bc) - 1
    apex = side_bc[-1]

    side_top = [apex] * (span_u + 1)  # P11 -> P01, both C: degenerate
    side_left = side_ca               # P01 (C) -> P00 (A), already in this order

    return coons_patch_grid(side_ab, side_bc, side_top, side_left, span_u, span_v)


def build_bvh_with_polygon_map(mesh: "bpy.types.Mesh") -> tuple["BVHTree", list[int]]:
    """BVH over every polygon of `mesh` (local object space), plus a list
    mapping each BVH triangle index back to the polygon it came from.

    BVHTree.FromPolygons reports the index of the triangle it hit, and
    fan-triangulating a polygon emits several triangles, so the caller needs
    that map to get back to a polygon (and from there to a Plasticity face id).
    """
    from mathutils.bvhtree import BVHTree

    verts = [v.co.copy() for v in mesh.vertices]
    tris = []
    tri_poly = []

    for poly in mesh.polygons:
        loop_verts = list(poly.vertices)
        for i in range(1, len(loop_verts) - 1):
            tris.append((loop_verts[0], loop_verts[i], loop_verts[i + 1]))
            tri_poly.append(poly.index)

    return BVHTree.FromPolygons(verts, tris), tri_poly


def build_bvh_for_polygons(
    mesh: "bpy.types.Mesh", poly_indices: "list[int]"
) -> "BVHTree":
    """Build a BVHTree restricted to the given polygons of `mesh`, in the
    mesh's local object space.
    """
    from mathutils.bvhtree import BVHTree

    vert_remap = {}
    verts = []
    tris = []

    for poly_idx in poly_indices:
        poly = mesh.polygons[poly_idx]
        loop_verts = list(poly.vertices)
        local_ids = []
        for vi in loop_verts:
            if vi not in vert_remap:
                vert_remap[vi] = len(verts)
                verts.append(mesh.vertices[vi].co.copy())
            local_ids.append(vert_remap[vi])
        # fan-triangulate (import is already triangulated, so this is normally a no-op)
        for i in range(1, len(local_ids) - 1):
            tris.append((local_ids[0], local_ids[i], local_ids[i + 1]))

    return BVHTree.FromPolygons(verts, tris)


# How far one relaxation pass moves a vertex towards the average of its
# neighbours. Under-relaxed on purpose: the full step is a Jacobi iteration of
# the Laplace equation, which oscillates on exactly the cells this exists to
# fix -- a long thin cell against a concave boundary overshoots, lands on the
# far side of its neighbours and comes back next pass. Half a step converges
# monotonically and the difference is one more iteration.
RELAX_STRENGTH = 0.5


def cell_quality(
    points: "list[mathutils.Vector]",
    reference_normal: "mathutils.Vector | None" = None,
) -> float:
    """How square a face is, in [0, 1]: 1 for a square or an equilateral
    triangle, 0 for a degenerate or turned-over one.

    Two terms multiplied, because each one alone calls a bad cell good. The
    sine of the **smallest corner angle** catches what is squashed or folded --
    a cell crushed against a concave boundary has an acute corner, a folded one
    has a corner at 180 degrees -- and says nothing at all about a 1x100
    rectangle, whose corners are four perfect right angles. The ratio of the
    **shortest edge to the longest** catches exactly that, and says nothing
    about a rhombus with a 5 degree corner. A stretched cell is the complaint
    this whole pass exists to answer, so the measure it is steered by has to see
    both.

    Cheap enough to run per incident face per vertex per pass: a cross product
    and a length per corner.

    `reference_normal` makes it directional: a face whose normal has turned past
    a right angle from it scores 0 whatever its shape. That is what stops a step
    from turning a cell over *while keeping it square*, which no measure of the
    angles can see.
    """
    count = len(points)
    if count < 3:
        return 0.0

    if reference_normal is not None:
        normal = mathutils.geometry.normal(points)
        if normal.length_squared == 0.0 or normal.dot(reference_normal) <= 0.0:
            return 0.0

    worst_angle = 1.0
    shortest = None
    longest = 0.0
    for i in range(count):
        before = points[i - 1] - points[i]
        after = points[(i + 1) % count] - points[i]
        if before.length_squared == 0.0 or after.length_squared == 0.0:
            return 0.0
        # The sine of the corner angle, via the cross product, so a corner at 0
        # degrees and one at 180 both score 0 -- collapsed and folded alike.
        worst_angle = min(
            worst_angle, before.normalized().cross(after.normalized()).length)
        length = after.length
        shortest = length if shortest is None else min(shortest, length)
        longest = max(longest, length)

    if not longest:
        return 0.0
    return worst_angle * (shortest / longest)


# The cell quality a relaxation pass works up to, and stops at. A cell twice as
# long as it is wide scores 0.5 and is an ordinary retopology cell, not a defect
# -- a patch is rarely square and its grid follows it -- so that is where this
# stops: it is a repair for what is *worse* than that, not a beautifier.
#
# It is also what makes the pass affordable on every hover. Only the vertices
# touching a cell below the target are tried, so a patch with nothing wrong
# costs one sweep of its faces and returns, and the cost of the rest scales with
# the size of the problem rather than with the size of the patch.
RELAX_QUALITY_TARGET = 0.5


def relax_interior_points(
    verts: "list[mathutils.Vector]",
    faces: "list[tuple[int, ...]]",
    pinned: "set[int] | list[int]",
    bvh: "BVHTree",
    iterations: int,
    strength: float = RELAX_STRENGTH,
    target: float = RELAX_QUALITY_TARGET,
) -> int:
    """Laplacian relaxation of a generated patch's interior, in place.

    Returns how many vertices ended up somewhere other than where they started.

    A Coons grid interpolates between opposite sides, which is the right answer
    for a four-sided region whose sides face each other and a poor one as soon
    as they do not: against a concave boundary -- the rim of a hole, a slot's
    flank -- the cells bunch against the concavity and stretch away from it, and
    around an acute corner they collapse. None of that is decided by the
    boundary, so no choice of corners or spans can fix it. Moving the *interior*
    points is the answer, and it costs nothing elsewhere: the boundary is
    pinned, so every vertex a neighbour welds to -- by identity for a corner, by
    proximity for the rest -- stays exactly where the generator put it.

    `pinned` is the generator's own `boundary_local_indices`, never recomputed
    from the topology here. What makes a vertex untouchable is that something
    outside this patch may weld to it, which is a fact about the patch and not
    about whether an edge of the preview happens to carry one face.

    Four things about the method, each of which was the alternative:

    - **A move is taken only if it improves the worst cell it touches.** A plain
      Laplacian pass is not an improvement everywhere: on a grid that is already
      regular it pulls the interior towards equal *edge lengths*, which is not
      where transfinite interpolation put them -- measured across the fixture,
      the unguarded version improved four shapes' cell quality and made three
      others' worse. Scoring each incident face before and after
      (`cell_quality`) and keeping the move only when the worst of them rises
      makes the pass one-directional by construction: a patch it has nothing to
      offer comes back exactly as the generator built it. That is the difference
      between a knob that has to be tuned per part and one that can be left on.
    - **Uniform weights, not cotangent.** Cotangent weights are the better
      smoother on a fixed triangulation and they go *negative* on an obtuse
      triangle, which lets a vertex leave the hull of its neighbours -- i.e.
      turns a cell over, which is what this is here to remove. A plain average
      is unconditionally a convex combination.
    - **Jacobi, not Gauss-Seidel.** Every vertex in a pass reads the previous
      pass's positions, so the outcome does not depend on the order the
      generator happened to emit its vertices in. Two patches of the same shape
      must relax the same way, or a shared boundary stops being reproducible.
    - **Reprojected every pass, not once at the end.** A Laplacian step moves a
      point towards the chord between its neighbours, which on a curved surface
      is *inside* it; iterating without putting it back compounds into a visible
      shrink, and the deviation this addon is measured by is precisely that
      distance. So the relaxation is surface-constrained: step, project, repeat.
      It follows that there is nothing to do without a BVH -- with reprojection
      off this would be the shrink and nothing else -- and the caller is the one
      that knows.

    And a step whose *projection* is longer than the step itself is refused. On
    a curved surface the correction after a tangential move is second order and
    far shorter than the move; a projection longer than its own cause means the
    point has left the patch, and `find_nearest` is then answering with the
    nearest point on the **boundary**, which drags the vertex onto an edge and
    turns over the cells either side of it. That is the concave-centre fold
    `generators.nside.interior_point` exists to avoid, arrived at from the other
    direction. A patch so coarse against its own curvature that every step is
    refused simply holds still.

    This runs on every hover, so what it costs when there is nothing to do
    matters more than what it costs when there is: see `RELAX_QUALITY_TARGET`.
    """
    if iterations <= 0 or bvh is None or not verts or not faces:
        return 0

    fixed = set(pinned)
    neighbours: list[set[int]] = [set() for _ in verts]
    incident: list[list[int]] = [[] for _ in verts]
    for index, face in enumerate(faces):
        count = len(face)
        for i in range(count):
            a = face[i]
            b = face[(i + 1) % count]
            if a != b:  # a collapsed row (a fan's apex) names itself twice
                neighbours[a].add(b)
                neighbours[b].add(a)
            if index not in incident[a]:
                incident[a].append(index)

    free = [i for i in range(len(verts)) if i not in fixed and neighbours[i]]
    if not free:
        return 0

    start = [verts[i].copy() for i in free]

    for _ in range(iterations):
        # One score per face per pass, not one per incident vertex: every
        # candidate below reads its "before" from here.
        quality = [cell_quality([verts[vi] for vi in face]) for face in faces]
        active = [i for i in free
                  if any(quality[f] < target for f in incident[i])]
        if not active:
            break  # nothing below the target: this patch is not the problem

        updated = {}
        for i in active:
            ring = neighbours[i]
            target_point = mathutils.Vector((0.0, 0.0, 0.0))
            for j in ring:
                target_point += verts[j]
            target_point /= len(ring)

            stepped = verts[i].lerp(target_point, strength)
            step = (stepped - verts[i]).length
            if step <= 1e-12:
                continue  # already at the average of its neighbours
            hit = bvh.find_nearest(stepped)
            if hit is None or hit[0] is None:
                continue  # nothing to project onto: leave it where it is
            candidate = hit[0]
            if (candidate - stepped).length > step:
                continue  # the step left the patch -- see the docstring

            if _improves(verts, faces, incident[i], i, candidate,
                         min(quality[f] for f in incident[i])):
                updated[i] = candidate

        if not updated:
            break  # converged: no step left that would improve anything
        for index, point in updated.items():
            verts[index] = point

    return sum(1 for i, was in zip(free, start)
               if (verts[i] - was).length > 1e-9)


def _improves(
    verts: "list[mathutils.Vector]",
    faces: "list[tuple[int, ...]]",
    incident: "list[int]",
    moved: int,
    to: "mathutils.Vector",
    before: "float | None" = None,
) -> bool:
    """Whether putting vertex `moved` at `to` raises the quality of the *worst*
    face it belongs to. `before` is that worst quality, when the caller has
    already scored the faces this pass and need not do it twice.

    The worst one, not every one: a relaxation step almost always takes a little
    from one cell to give to another -- that is what evening them out is -- so
    requiring every incident face to improve would refuse essentially every move
    and the pass would do nothing at all. What must not happen is the worst cell
    getting worse, and that is what this answers.

    Each face keeps its *own* normal as the reference, so "improved" can never
    include having turned it over.
    """
    if before is None:
        before = min(cell_quality([verts[vi] for vi in faces[f]])
                     for f in incident)
    for face_index in incident:
        face = faces[face_index]
        reference = mathutils.geometry.normal([verts[vi] for vi in face])
        after = cell_quality(
            [to if vi == moved else verts[vi] for vi in face], reference)
        if after <= before:
            return False
    return True
