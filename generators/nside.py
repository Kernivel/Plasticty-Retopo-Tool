"""Fallback generator for patches with five or more sides.

**The centre vertex is unavoidable; its valence is not.** A quad mesh of an
odd-sided region has to put an irregular vertex somewhere, and the middle is
where every retopology tool puts it. What this used to do, though, was emit one
quad per *boundary vertex* -- so the pole's valence was the side count times
the span, twenty-four spokes on a six-sided patch at span four, and there was
no interior grid at all: the only points inside the patch were that centre and
one midpoint per boundary segment. On a curved face the result sags between
them, which is the "it makes a fan" the shape reports on sight.

So the patch is split into **one Coons sub-patch per side** instead -- the
first half of the ring around the reference tool's N-Side mode, and the first
step of Catmull-Clark subdivision seen from the other end. Each side is split
at its midpoint, a spoke runs from that midpoint to the centre, and the quad
between two consecutive spokes (half a side, spoke, spoke, half the next side)
is filled by the same Coons solver and reprojection every other generator uses.
The pole's valence drops to the number of *sides*, the interior becomes a real
grid, and every interior point is put on the surface through the BVH.

**Which makes the sides largely independent, and that is what lets several of
them be matched at once.** A side is bounded by the spokes of its two
*neighbours* -- `t[i] = s[i-1] + s[i+1]`, its own spoke only saying where it is
split -- so choosing the spokes chooses every side's count. A patch whose left side must reproduce one committed neighbour
and whose bottom must reproduce another needs only two spokes to come out
right, where the single shared span this used to have could honour one of them
and left the other as a crack ("another side drives the same span" was the
whole story on an N-Side patch).

`spoke_allocation` is that solve. It is deliberately not a general one: the
constraint `s[i-1] + s[i] = t[i]` over a cycle is only always solvable for odd
`n` and needs an alternating-sum condition for even `n`, so rather than fail on
a shape it cannot satisfy, it takes the wanted counts in priority order, fixes
what each one implies, and reports which it could not honour. The caller drops
those matches like any other it cannot reproduce.

With nothing matched every spoke is the same, so every side carries an **even**
count -- it is split at one of its own vertices, and `even_span` is what rounds
the uniform case up to something buildable.

**Per-side spans in the panel and hand-placed corners** are still what the
reference tool's full N-Side mode adds, and still not implemented: what is here
is the machinery under them.
"""
import math
from typing import TYPE_CHECKING, Any

import mathutils

from .. import constants
from .. import geometry
from .base import Generator, GenerationResult

if TYPE_CHECKING:
    from mathutils.bvhtree import BVHTree


def even_span(span: int) -> int:
    """The segment count per side an N-Side patch can actually build.

    At least two, and even: the side is split at its midpoint and that midpoint
    has to be one of its own vertices, or the sub-patches on either side of it
    would not share a boundary.
    """
    span = max(2, int(span))
    return span if span % 2 == 0 else span + 1


def spoke_allocation(
    n: int, default_half: int, wanted: dict[int, int] | None = None,
    order: list[int] | None = None,
) -> tuple[list[int], list[int]]:
    """(spoke counts, side indices whose wanted count could not be honoured).

    `wanted[i]` is the number of segments side `i` has to end up with -- a
    committed neighbour's vertex count, almost always. Side `i`'s count is
    `s[i-1] + s[i+1]` (see `side_segments`), so each wanted count fixes a
    *pair* of spokes, and two sides two apart share one and can disagree. `order` is the priority to resolve them in
    (a pin before an automatic match, then the denser one); whatever is left
    undecided gets `default_half`.

    Refusing rather than approximating is the point: a match that comes back
    with a count nobody asked for is a crack that looks like a weld.
    """
    spokes: list[int | None] = [None] * n
    refused = []
    wanted = wanted or {}
    for i in order if order is not None else sorted(wanted):
        total = wanted.get(i)
        if total is None:
            continue
        # The two spokes this side's count is made of -- its neighbours', not
        # its own. See `side_segments`.
        before, after = (i - 1) % n, (i + 1) % n
        fixed_before, fixed_after = spokes[before], spokes[after]
        if fixed_before is None and fixed_after is None:
            if total < 2:
                refused.append(i)  # a side needs a segment either side of its midpoint
                continue
            spokes[before] = total // 2
            spokes[after] = total - total // 2
        elif fixed_before is None:
            spokes[before] = total - fixed_after
            if spokes[before] < 1:
                spokes[before] = None
                refused.append(i)
        elif fixed_after is None:
            spokes[after] = total - fixed_before
            if spokes[after] < 1:
                spokes[after] = None
                refused.append(i)
        elif fixed_before + fixed_after != total:
            # Both spokes are already spoken for by neighbours of this side and
            # they do not add up to what it wants. Nothing to give.
            refused.append(i)

    resolved = [default_half if spoke is None else spoke for spoke in spokes]
    return resolved, refused


def side_segments(spokes: list[int]) -> list[int]:
    """How many segments each side ends up with, given the spokes.

    Side `i` is split where its own spoke leaves it. What lies *before* that
    split is the bottom of sub-patch `i`, which has to be as long as that
    sub-patch's other u-direction edge -- spoke `i-1`; what lies after is the
    left edge of sub-patch `i+1`, which has to match spoke `i+1`. So a side is
    bounded by the spokes of its two *neighbours*, not by its own: `t[i] =
    s[i-1] + s[i+1]`, and its own spoke only says where the split falls.
    """
    n = len(spokes)
    return [spokes[(i - 1) % n] + spokes[(i + 1) % n] for i in range(n)]


class NSideGenerator(Generator):
    name = constants.NSIDE

    def matches(self, num_sides: int) -> bool:
        return num_sides >= 5

    def default_spans(self, sides: list[list[mathutils.Vector]]) -> dict[str, int]:
        seg_lengths = []
        side_lengths = []
        for side in sides:
            total = 0.0
            for a, b in zip(side, side[1:]):
                d = (b - a).length
                total += d
                seg_lengths.append(d)
            side_lengths.append(total)

        target_edge = (sum(seg_lengths) / len(seg_lengths)) if seg_lengths else 1.0
        avg_side = sum(side_lengths) / len(side_lengths)
        return {"span": even_span(round(avg_side / max(target_edge, 1e-6)))}

    def generate(
        self,
        sides: list[list[mathutils.Vector]],
        span_settings: dict[str, Any],
        bvh: "BVHTree | None" = None,
    ) -> GenerationResult:
        if len(sides) < 3:
            raise ValueError("NSideGenerator expects at least 3 sides")

        n = len(sides)
        # Spokes, one per side, are what everything else is derived from: side
        # `i` runs from spoke `i-1` to spoke `i`, so `spokes` decides every
        # side's segment count and where its midpoint falls. Given none, they
        # are uniform and every side comes out with the same even count.
        spokes_counts = list(span_settings.get("spokes") or ())
        if len(spokes_counts) != n or any(count < 1 for count in spokes_counts):
            spokes_counts = [even_span(span_settings.get("span", 2)) // 2] * n
        segments_of = side_segments(spokes_counts)

        # Each side resampled to its own count, split at the vertex where its
        # spoke leaves it -- `spokes[i-1]` segments in, the rest out.
        rings = [geometry.resample_polyline_by_arclength(side, count + 1)
                 for side, count in zip(sides, segments_of)]
        splits = [spokes_counts[(i - 1) % n] for i in range(n)]

        centre = mathutils.Vector((0.0, 0.0, 0.0))
        total_points = 0
        for ring in rings:
            for point in ring[:-1]:
                centre += point
                total_points += 1
        centre /= float(max(1, total_points))

        def project(point: mathutils.Vector) -> mathutils.Vector:
            if bvh is None:
                return point
            hit = bvh.find_nearest(point)
            if hit and hit[0] is not None:
                return hit[0]
            return point

        centre = project(centre)

        # One spoke per side, from that side's midpoint to the centre. Built
        # once and shared by the two sub-patches either side of it, so nothing
        # here relies on a later weld to close the seam between them.
        # Straight, then reprojected -- the same answer the Coons interiors get,
        # and for the same reason: the chord is where the point wants to be, the
        # surface is where it has to sit.
        spokes = []
        for i, ring in enumerate(rings):
            midpoint = ring[splits[i]]
            length = spokes_counts[i]
            spoke = [midpoint]
            for step in range(1, length):
                spoke.append(project(midpoint.lerp(centre, step / length)))
            spoke.append(centre)
            spokes.append(spoke)

        verts: list[mathutils.Vector] = []
        uvs: list[tuple[float, float]] = []
        index_of: dict[tuple, int] = {}

        def disc_uv(angle: float, radius: float) -> tuple[float, float]:
            return (0.5 + 0.5 * radius * math.cos(angle),
                    0.5 + 0.5 * radius * math.sin(angle))

        def add(key: tuple, point: mathutils.Vector,
                uv: tuple[float, float]) -> int:
            """Vertex index for `key`, creating it once.

            Keyed rather than deduplicated by position: the sub-patches share
            whole spokes and half-sides by construction, and knowing *which*
            vertex is shared is exactly what keeps a merge-by-distance out of
            the generator.
            """
            existing = index_of.get(key)
            if existing is not None:
                return existing
            index_of[key] = len(verts)
            verts.append(point)
            uvs.append(uv)
            return index_of[key]

        def side_angle(side: int, along: float) -> float:
            """Where a point `along` (0..1) side `side` sits round the disc."""
            return 2.0 * math.pi * (side + along) / n

        def boundary_index(side: int, t: int) -> int:
            # A side's last point is the next side's first: one point, one key.
            side, t = ((side + 1) % n, 0) if t == segments_of[side] else (side, t)
            return add(("b", side, t), rings[side][t],
                       disc_uv(side_angle(side, t / segments_of[side]), 1.0))

        def spoke_index(side: int, k: int) -> int:
            # Both ends of a spoke belong to something else: the midpoint is a
            # boundary vertex and the far end is the one centre. Keyed as those,
            # or the two sub-patches meeting along this spoke would each get
            # their own copy of a point they are supposed to share.
            if k == 0:
                return boundary_index(side, splits[side])
            if k == spokes_counts[side]:
                return add(("centre",), centre, (0.5, 0.5))
            return add(("s", side, k), spokes[side][k],
                       disc_uv(side_angle(side, splits[side] / segments_of[side]),
                               1.0 - k / spokes_counts[side]))

        faces = []
        for i in range(n):
            previous = (i - 1) % n
            # The sub-patch between spoke `previous` and spoke `i`. Its two
            # directions are those spokes' counts, which is exactly why the
            # sides can differ: `span_u` is spoke `previous`, `span_v` is spoke
            # `i`, and side `i` gets `span_u` segments before its midpoint and
            # `span_v` after it.
            span_u = spokes_counts[previous]
            span_v = spokes_counts[i]
            # Corners: C = this side's first point, M = its midpoint,
            # Z = the centre, P = the previous side's midpoint.
            bottom = rings[i][:span_u + 1]                # C -> M
            right = spokes[i]                             # M -> Z
            top = list(reversed(spokes[previous]))        # Z -> P
            left = rings[previous][splits[previous]:]     # P -> C

            grid = geometry.coons_patch_grid(bottom, right, top, left, span_u, span_v)

            # The sub-patch's four corners on the disc, for its interior UVs.
            # Computed rather than read back off the grid: the last row is not
            # filled in yet when the interior of the first one is reached.
            corner_uvs = (
                disc_uv(side_angle(i, 0.0), 1.0),        # C
                disc_uv(side_angle(i, splits[i] / segments_of[i]), 1.0),  # M
                (0.5, 0.5),                              # centre
                disc_uv(side_angle(previous,
                                   splits[previous] / segments_of[previous]), 1.0),  # P
            )

            local = [[0] * (span_u + 1) for _ in range(span_v + 1)]
            for vi in range(span_v + 1):
                for ui in range(span_u + 1):
                    if vi == 0:
                        local[vi][ui] = boundary_index(i, ui)
                    elif ui == span_u:
                        local[vi][ui] = spoke_index(i, vi)
                    elif vi == span_v:
                        local[vi][ui] = spoke_index(previous, ui)
                    elif ui == 0:
                        local[vi][ui] = boundary_index(
                            previous, segments_of[previous] - vi)
                    else:
                        # Interior of this sub-patch: nothing else can reach it,
                        # so it is created here and reprojected like every other
                        # interior point.
                        uv_u = ui / span_u
                        uv_v = vi / span_v
                        uv = tuple(
                            corner_uvs[0][axis] * (1 - uv_u) * (1 - uv_v)
                            + corner_uvs[1][axis] * uv_u * (1 - uv_v)
                            + corner_uvs[2][axis] * uv_u * uv_v
                            + corner_uvs[3][axis] * (1 - uv_u) * uv_v
                            for axis in (0, 1))
                        local[vi][ui] = add(("i", i, ui, vi),
                                            project(grid[vi][ui]), uv)

            for vi in range(span_v):
                for ui in range(span_u):
                    faces.append((local[vi][ui], local[vi][ui + 1],
                                  local[vi + 1][ui + 1], local[vi + 1][ui]))

        corner_local_indices = [index_of[("b", i, 0)] for i in range(n)]
        boundary_local_indices = [index_of[("b", i, t)]
                                  for i in range(n) for t in range(segments_of[i])]

        result = GenerationResult(verts, faces, uvs,
                                  corner_local_indices, boundary_local_indices)
        # What each side actually got, for the commit path to register: with
        # per-side counts there is no single span to recompute it from.
        result.side_allocation = segments_of
        return result
