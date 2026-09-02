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

Two consequences worth stating:

- **each side carries an even number of segments**, because it is split at a
  vertex. `operators._prepare_patch` rounds the span up to even before the
  spans are resolved, so what the panel shows, what a match has to reproduce
  and what the mesh gets are one number rather than three.
- **all sides still share one span.** Per-side spans and hand-placed corners
  are what the reference tool's full N-Side mode adds, and are still not
  implemented.
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

        segments = even_span(span_settings.get("span", 2))
        half = segments // 2
        n = len(sides)

        # Every side resampled to the same even count, so the midpoint is a
        # vertex and two sub-patches can meet along the spoke that starts there.
        rings = [geometry.resample_polyline_by_arclength(side, segments + 1)
                 for side in sides]

        centre = mathutils.Vector((0.0, 0.0, 0.0))
        for ring in rings:
            for point in ring[:-1]:
                centre += point
        centre /= float(n * segments)

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
        for ring in rings:
            midpoint = ring[half]
            spoke = [midpoint]
            for step in range(1, half):
                spoke.append(project(midpoint.lerp(centre, step / half)))
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
            side, t = ((side + 1) % n, 0) if t == segments else (side, t)
            return add(("b", side, t), rings[side][t],
                       disc_uv(side_angle(side, t / segments), 1.0))

        def spoke_index(side: int, k: int) -> int:
            # Both ends of a spoke belong to something else: the midpoint is a
            # boundary vertex and the far end is the one centre. Keyed as those,
            # or the two sub-patches meeting along this spoke would each get
            # their own copy of a point they are supposed to share.
            if k == 0:
                return boundary_index(side, half)
            if k == half:
                return add(("centre",), centre, (0.5, 0.5))
            return add(("s", side, k), spokes[side][k],
                       disc_uv(side_angle(side, 0.5), 1.0 - k / half))

        faces = []
        for i in range(n):
            previous = (i - 1) % n
            # Corners: C = this side's first point, M = its midpoint,
            # Z = the centre, P = the previous side's midpoint.
            bottom = rings[i][:half + 1]                  # C -> M
            right = spokes[i]                             # M -> Z
            top = list(reversed(spokes[previous]))        # Z -> P
            left = rings[previous][half:]                 # P -> C

            grid = geometry.coons_patch_grid(bottom, right, top, left, half, half)

            # The sub-patch's four corners on the disc, for its interior UVs.
            # Computed rather than read back off the grid: the last row is not
            # filled in yet when the interior of the first one is reached.
            corner_uvs = (
                disc_uv(side_angle(i, 0.0), 1.0),        # C
                disc_uv(side_angle(i, 0.5), 1.0),        # M
                (0.5, 0.5),                              # centre
                disc_uv(side_angle(previous, 0.5), 1.0),  # P
            )

            local = [[0] * (half + 1) for _ in range(half + 1)]
            for vi in range(half + 1):
                for ui in range(half + 1):
                    if vi == 0:
                        local[vi][ui] = boundary_index(i, ui)
                    elif ui == half:
                        local[vi][ui] = spoke_index(i, vi)
                    elif vi == half:
                        local[vi][ui] = spoke_index(previous, ui)
                    elif ui == 0:
                        local[vi][ui] = boundary_index(previous, segments - vi)
                    else:
                        # Interior of this sub-patch: nothing else can reach it,
                        # so it is created here and reprojected like every other
                        # interior point.
                        uv_u = ui / half
                        uv_v = vi / half
                        uv = tuple(
                            corner_uvs[0][axis] * (1 - uv_u) * (1 - uv_v)
                            + corner_uvs[1][axis] * uv_u * (1 - uv_v)
                            + corner_uvs[2][axis] * uv_u * uv_v
                            + corner_uvs[3][axis] * (1 - uv_u) * uv_v
                            for axis in (0, 1))
                        local[vi][ui] = add(("i", i, ui, vi),
                                            project(grid[vi][ui]), uv)

            for vi in range(half):
                for ui in range(half):
                    faces.append((local[vi][ui], local[vi][ui + 1],
                                  local[vi + 1][ui + 1], local[vi + 1][ui]))

        corner_local_indices = [index_of[("b", i, 0)] for i in range(n)]
        boundary_local_indices = [index_of[("b", i, t)]
                                  for i in range(n) for t in range(segments)]

        return GenerationResult(verts, faces, uvs,
                                corner_local_indices, boundary_local_indices)
