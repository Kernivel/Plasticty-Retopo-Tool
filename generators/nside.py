import mathutils

from .. import geometry
from .base import Generator, GenerationResult


class NSideGenerator(Generator):
    """Fallback generator for patches with five or more sides.

    Fills the patch with pure quads using the classic midpoint
    quadrangulation: insert a centre point, split every boundary segment at
    its midpoint, then emit one quad per boundary vertex
    (corner, next midpoint, centre, previous midpoint). This works for any
    number of boundary segments -- odd counts included, since every segment
    contributes its own midpoint -- and always yields quads only.

    All sides share one span here: per-side span control is what the
    reference tool's full N-Side mode adds, and is not implemented yet.
    """

    name = "N-Side"

    def matches(self, num_sides):
        return num_sides >= 5

    def default_spans(self, sides):
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
        span = max(1, round(avg_side / max(target_edge, 1e-6)))
        return {"span": span}

    def generate(self, sides, span_settings, bvh=None):
        if len(sides) < 3:
            raise ValueError("NSideGenerator expects at least 3 sides")

        span = max(1, int(span_settings.get("span", 1)))

        # Resample every side to the same span, then chain them into one
        # boundary ring (each side's last point is the next side's first).
        boundary = []
        corner_local_indices = []
        for side in sides:
            resampled = geometry.resample_polyline_by_arclength(side, span + 1)
            corner_local_indices.append(len(boundary))
            boundary.extend(resampled[:-1])  # drop the shared corner, next side re-adds it

        n = len(boundary)
        if n < 3:
            raise ValueError("N-Side patch boundary is degenerate")

        centre = mathutils.Vector((0.0, 0.0, 0.0))
        for p in boundary:
            centre += p
        centre /= n

        def project(point):
            if bvh is None:
                return point
            hit = bvh.find_nearest(point)
            if hit and hit[0] is not None:
                return hit[0]
            return point

        verts = list(boundary)
        uvs = []
        boundary_local_indices = list(range(n))

        # Radial UVs: boundary on the unit circle, centre in the middle.
        import math
        for i in range(n):
            angle = 2.0 * math.pi * i / n
            uvs.append((0.5 + 0.5 * math.cos(angle), 0.5 + 0.5 * math.sin(angle)))

        centre_index = len(verts)
        verts.append(project(centre))
        uvs.append((0.5, 0.5))

        # One midpoint per boundary segment; midpoint i sits between boundary
        # vertex i and i+1.
        midpoint_indices = []
        for i in range(n):
            a = boundary[i]
            b = boundary[(i + 1) % n]
            midpoint_indices.append(len(verts))
            verts.append(project((a + b) * 0.5))
            uv_a = uvs[i]
            uv_b = uvs[(i + 1) % n]
            uvs.append(((uv_a[0] + uv_b[0]) * 0.5, (uv_a[1] + uv_b[1]) * 0.5))

        faces = []
        for i in range(n):
            prev_mid = midpoint_indices[(i - 1) % n]
            next_mid = midpoint_indices[i]
            faces.append((i, next_mid, centre_index, prev_mid))

        return GenerationResult(verts, faces, uvs, corner_local_indices, boundary_local_indices)
