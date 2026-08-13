"""Grid generation (transfinite / Coons interpolation) and surface
reprojection helpers, independent of any Blender operator/UI code so they can
be unit-exercised from a --background script.
"""
import mathutils


def resample_polyline_by_arclength(points, count):
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
    acc = 0.0
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


def coons_patch_grid(side_bottom, side_right, side_top, side_left, span_u, span_v):
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


def fan_collapsed_grid(side_ab, side_bc, side_ca):
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


def project_points_to_surface(points, bvh, max_distance=1e6):
    """Snap each point in `points` (iterable of Vector) to the nearest point
    on the surface represented by `bvh` (mathutils.bvhtree.BVHTree).

    Returns a new list in the same order; points that fail to find a hit
    (shouldn't normally happen against a closed patch BVH) are left as-is.
    """
    result = []
    for p in points:
        hit = bvh.find_nearest(p, max_distance)
        if hit is None or hit[0] is None:
            result.append(p)
        else:
            result.append(hit[0])
    return result


def build_bvh_for_polygons(mesh, poly_indices):
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
