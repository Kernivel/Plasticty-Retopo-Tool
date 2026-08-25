"""Single-n-gon patch: no interior grid, no spans.

For a planar (or near-planar) face, a Coons grid is wasted geometry -- one
n-gon following the boundary carries the same shape. What it still has to get
right is the *boundary*: a straight side collapses to its two corners, while a
curved side keeps enough points to stay round. That is the "densify curved
edges" rule -- point count comes from how much the boundary turns, not from
how long it is.

**The boundary is selected, never resampled.** Points are *kept* from the
source boundary rather than spread evenly along it by arc length, and that
distinction is the whole correctness of this generator. `sides.py` only calls
a vertex a corner when the boundary turns sharper than
`corner_angle_threshold` (45 degrees of deviation by default), so a chamfer --
which usually deviates 20-40 degrees -- is *not* a corner and lands in the
middle of a side. Arc-length resampling put its points wherever the even
spacing fell and cut a straight chord across the chamfer; accumulating turn
and keeping the vertex where it happens reproduces it exactly, because the
kept points are genuine CAD boundary vertices.

The trade-off that buys: an n-gon side no longer lines up point-for-point with
a *grid* neighbour along a shared edge (a grid resamples evenly, this doesn't),
so only their shared corners weld. Raising `corner_angle_threshold` until the
feature reads as a real corner restores both the shape and the welding.

A face **with a hole** is filled by `generate_holed`, which bridges the hole to
the outer boundary with two edges and emits two n-gons rather than one. That is
the only way to do it: a Blender n-gon has a single loop, and the alternative
(one "keyhole" face running up to the hole and back) needs the bridge vertices
duplicated, which the boundary weld would then merge back and destroy the face.
Two faces need no duplicates and stay manifold. Where the bridges land is
arbitrary -- nearest pair, then roughly opposite -- since on a flat face it
changes nothing but which two edges are drawn.

Reached explicitly (like the Ring generator, and unlike the span-based ones):
it's a mode the user toggles during a session, not something a side count
selects.
"""
import math
from typing import TYPE_CHECKING, Any

import mathutils

from .. import constants
from .. import geometry
from .base import Generator, GenerationResult

if TYPE_CHECKING:
    from mathutils.bvhtree import BVHTree

DEFAULT_ANGLE = 20.0  # degrees of boundary turn per kept point

# Below this, a vertex is straight as far as anyone cares. Without it, the
# rounding noise of a dense tessellation would accumulate along a dead-straight
# edge and sprinkle it with pointless vertices.
TURN_EPSILON = 0.05


def turn_at(
    prev_co: mathutils.Vector, co: mathutils.Vector, next_co: mathutils.Vector
) -> float:
    """How much the boundary deviates from straight at `co`, in degrees.
    0 is dead straight; a 90 degree corner returns 90.
    """
    incoming = co - prev_co
    outgoing = next_co - co
    if incoming.length < 1e-12 or outgoing.length < 1e-12:
        return 0.0
    return math.degrees(incoming.angle(outgoing, 0.0))


def side_turn_degrees(points: list[mathutils.Vector]) -> float:
    """Total turning angle along a polyline, in degrees.

    0 for a straight side however long it is, 180 for a half circle.
    """
    return sum(turn_at(a, b, c) for a, b, c in zip(points, points[1:], points[2:]))


def side_points(
    points: list[mathutils.Vector], angle_per_segment: float
) -> list[mathutils.Vector]:
    """The boundary vertices this side keeps, first and last always included.

    Walks the side accumulating how much it has turned since the last kept
    vertex and keeps one every `angle_per_segment` degrees. Three behaviours
    fall out of that single rule:

    - a straight run never accumulates, so it collapses to its two corners
      however long it is;
    - a curve accumulates steadily, so it keeps a vertex every
      `angle_per_segment` degrees of arc and stays round;
    - a lone kink (a chamfer, a shallow crease) crosses the threshold on its
      own vertex, so it is kept *exactly where it is* -- which is what an
      arc-length resample could not do, and why chamfers used to be cut off.

    A feature shallower than `angle_per_segment` is deliberately dropped: that
    is what the setting means. Lower it to keep finer ones.
    """
    if len(points) <= 2:
        return list(points)

    angle_per_segment = max(1e-3, float(angle_per_segment))
    kept = [points[0]]
    accumulated = 0.0
    for i in range(1, len(points) - 1):
        turn = turn_at(points[i - 1], points[i], points[i + 1])
        if turn < TURN_EPSILON:
            continue
        accumulated += turn
        if accumulated >= angle_per_segment - 1e-9:
            kept.append(points[i])
            accumulated = 0.0
    kept.append(points[-1])
    return kept


def side_segments(points: list[mathutils.Vector], angle_per_segment: float) -> int:
    """How many segments a side ends up with -- never fewer than one, since a
    side always keeps its two corners.
    """
    return max(1, len(side_points(points, angle_per_segment)) - 1)


def loop_points(
    loop_sides: list[list[mathutils.Vector]],
    angle_per_segment: float,
    forced_segments: dict[int, int] | None = None,
) -> tuple[list[mathutils.Vector], list[int], list[int]]:
    """Walk one boundary loop's sides and return
    (points, corner_indices, segments_per_side).

    Each side drops its last point -- it is the next side's first -- so the
    result is a closed ring of distinct points, and `corner_indices` says where
    in it each side started. Those are the patch's real corners, the only
    points that weld across patches by identity.

    `forced_segments` maps a side's index in this loop to an exact segment
    count, and switches that side from curvature selection to plain
    arc-length resampling. That is the point of it: a neighbour that already
    committed N segments along the shared edge put them at even spacing, so
    matching the *count* is only half of it -- the positions have to match too,
    or the two boundaries still don't weld. Every other side keeps following
    its own curvature.
    """
    forced_segments = forced_segments or {}
    points = []
    corners = []
    allocation = []
    for index, side in enumerate(loop_sides):
        forced = forced_segments.get(index)
        if forced:
            kept = geometry.resample_polyline_by_arclength(side, max(1, int(forced)) + 1)
        else:
            kept = side_points(side, angle_per_segment)
        allocation.append(max(1, len(kept) - 1))
        corners.append(len(points))
        points.extend(point.copy() for point in kept[:-1])
    return points, corners, allocation


def loop_allocation(
    loop_sides: list[list[mathutils.Vector]],
    angle_per_segment: float,
    forced_segments: dict[int, int] | None = None,
) -> list[int]:
    """Segments per side for one loop -- what the commit path registers."""
    return loop_points(loop_sides, angle_per_segment, forced_segments)[2]


def _nearest_pair(
    outer: list[mathutils.Vector], hole: list[mathutils.Vector]
) -> tuple[int, int] | None:
    """Indices (i, j) of the closest outer/hole point pair. O(n*m), which is
    nothing at these counts and avoids a KD-tree for a dozen points.
    """
    best = None
    best_distance = float("inf")
    for i, a in enumerate(outer):
        for j, b in enumerate(hole):
            distance = (a - b).length_squared
            if distance < best_distance:
                best_distance = distance
                best = (i, j)
    return best


def _arc(start: int, end: int, count: int) -> list[int]:
    """Indices from `start` forward to `end` inclusive, wrapping at `count`."""
    walk = [start]
    current = start
    while current != end:
        current = (current + 1) % count
        walk.append(current)
    return walk


def _plane_uvs(points: list[mathutils.Vector]) -> list[tuple[float, float]]:
    """UVs from a best-fit plane through the boundary (Newell's method), scaled
    into 0..1. A patch retopped as an n-gon is planar or nearly so, which is
    exactly when a planar projection is the right unwrap.
    """
    normal = mathutils.Vector((0.0, 0.0, 0.0))
    count = len(points)
    for i, current in enumerate(points):
        nxt = points[(i + 1) % count]
        normal.x += (current.y - nxt.y) * (current.z + nxt.z)
        normal.y += (current.z - nxt.z) * (current.x + nxt.x)
        normal.z += (current.x - nxt.x) * (current.y + nxt.y)
    if normal.length < 1e-12:
        normal = mathutils.Vector((0.0, 0.0, 1.0))
    normal.normalize()

    # Any vector not parallel to the normal gives a usable tangent frame; UV
    # rotation is arbitrary for a planar projection.
    reference = (mathutils.Vector((1.0, 0.0, 0.0))
                 if abs(normal.x) < 0.9 else mathutils.Vector((0.0, 1.0, 0.0)))
    tangent = (reference - normal * reference.dot(normal)).normalized()
    bitangent = normal.cross(tangent)

    origin = points[0]
    raw = [((p - origin).dot(tangent), (p - origin).dot(bitangent)) for p in points]
    min_u = min(u for u, _ in raw)
    max_u = max(u for u, _ in raw)
    min_v = min(v for _, v in raw)
    max_v = max(v for _, v in raw)
    span_u = max(max_u - min_u, 1e-9)
    span_v = max(max_v - min_v, 1e-9)
    return [((u - min_u) / span_u, (v - min_v) / span_v) for u, v in raw]


class NgonGenerator(Generator):
    name = constants.NGON

    def matches(self, num_sides: int) -> bool:
        # Never picked by side count -- see the module docstring.
        return False

    def default_spans(self, sides: list[list[mathutils.Vector]]) -> dict[str, int]:
        return {}

    def generate(
        self,
        sides: list[list[mathutils.Vector]],
        span_settings: dict[str, Any],
        bvh: "BVHTree | None" = None,
    ) -> GenerationResult:
        """`sides` are the outer loop's sides in boundary order, consecutive
        sides sharing their corner point. `bvh` is ignored: every vertex sits
        on the boundary, i.e. already exactly on the CAD surface -- there is
        nothing in the interior to reproject.
        """
        if not sides:
            raise ValueError("NgonGenerator needs at least one side")

        angle = span_settings.get("ngon_angle", DEFAULT_ANGLE)
        verts, corner_local_indices, allocation = loop_points(
            sides, angle, span_settings.get("side_segments"))

        if len(verts) < 3:
            raise ValueError("N-gon needs at least 3 boundary points")

        uvs = _plane_uvs(verts)
        boundary_local_indices = list(range(len(verts)))
        faces = [tuple(range(len(verts)))]

        result = GenerationResult(verts, faces, uvs,
                                  corner_local_indices, boundary_local_indices)
        result.side_allocation = allocation
        return result

    def generate_holed(
        self,
        loops_sides: list[list[list[mathutils.Vector]]],
        span_settings: dict[str, Any],
        bvh: "BVHTree | None" = None,
    ) -> GenerationResult:
        """Fill a face with one hole: two n-gons joined by two bridge edges.

        `loops_sides` is [outer_sides, hole_sides], outer first (the caller
        sorts them -- which loop comes out of the boundary walk first is hash
        order). Corner indices are emitted outer-loop-first to match the order
        `PreparedPatch.corner_source_ids` flattens them in, or the welding
        would pair a corner with the wrong source vertex.
        """
        if len(loops_sides) != 2:
            raise ValueError("generate_holed expects exactly two boundary loops")

        angle = span_settings.get("ngon_angle", DEFAULT_ANGLE)
        # One override map per loop, in the same order as loops_sides.
        forced = span_settings.get("side_segments") or [None, None]
        outer, outer_corners, outer_allocation = loop_points(
            loops_sides[0], angle, forced[0])
        hole, hole_corners, hole_allocation = loop_points(
            loops_sides[1], angle, forced[1] if len(forced) > 1 else None)

        if len(outer) < 3 or len(hole) < 3:
            raise ValueError("N-gon with a hole needs 3+ points on each boundary")

        n_outer = len(outer)
        n_hole = len(hole)

        # First bridge on the closest pair, second roughly opposite it, so the
        # two arcs are comparable and the bridges don't cross.
        i_a, j_a = _nearest_pair(outer, hole)
        i_b = (i_a + n_outer // 2) % n_outer
        j_b = _nearest_pair([outer[i_b]], hole)[1]
        if j_b == j_a:
            # Degenerate: the whole hole is nearest to one point. Any second
            # attachment will do -- this is an arbitrary cut by definition.
            j_b = (j_a + n_hole // 2) % n_hole

        verts = outer + hole
        uvs = _plane_uvs(verts)

        # The hole's loop is wound opposite to the outer one (both are boundary
        # half-edges of the same patch), so walking both *forward* is what
        # closes each face consistently.
        faces = [
            tuple(_arc(i_a, i_b, n_outer)
                  + [n_outer + k for k in _arc(j_b, j_a, n_hole)]),
            tuple(_arc(i_b, i_a, n_outer)
                  + [n_outer + k for k in _arc(j_a, j_b, n_hole)]),
        ]

        corner_local_indices = outer_corners + [n_outer + c for c in hole_corners]
        result = GenerationResult(verts, faces, uvs, corner_local_indices,
                                  list(range(len(verts))))
        result.side_allocation = outer_allocation + hole_allocation
        return result
