from .. import constants
from .. import geometry
from .base import Generator, GenerationResult


class QuadGenerator(Generator):
    name = constants.QUAD

    def matches(self, num_sides):
        return num_sides == 4

    def default_spans(self, sides):
        """sides: list of 4 point-lists (already resolved to Vectors), walking
        the patch boundary in order."""
        lengths = []
        seg_lengths = []
        for side in sides:
            total = 0.0
            for a, b in zip(side, side[1:]):
                d = (b - a).length
                total += d
                seg_lengths.append(d)
            lengths.append(total)

        target_edge = (sum(seg_lengths) / len(seg_lengths)) if seg_lengths else 1.0
        span_u = max(1, round(((lengths[0] + lengths[2]) / 2) / max(target_edge, 1e-6)))
        span_v = max(1, round(((lengths[1] + lengths[3]) / 2) / max(target_edge, 1e-6)))
        return {"span_u": span_u, "span_v": span_v}

    def generate(self, sides, span_settings, bvh=None):
        if len(sides) != 4:
            raise ValueError("QuadGenerator expects exactly 4 sides")

        span_u = max(1, int(span_settings.get("span_u", 1)))
        span_v = max(1, int(span_settings.get("span_v", 1)))

        side0, side1, side2, side3 = sides  # A->B, B->C, C->D, D->A (point lists)

        r_side0 = geometry.resample_polyline_by_arclength(side0, span_u + 1)
        r_side1 = geometry.resample_polyline_by_arclength(side1, span_v + 1)
        r_side2 = geometry.resample_polyline_by_arclength(side2, span_u + 1)
        r_side3 = geometry.resample_polyline_by_arclength(side3, span_v + 1)

        grid = geometry.coons_patch_grid(r_side0, r_side1, r_side2, r_side3, span_u, span_v)

        nu = span_u + 1
        nv = span_v + 1

        verts = []
        uvs = []
        index_of = {}
        boundary_local_indices = []
        for vi in range(nv):
            for ui in range(nu):
                is_boundary = ui in (0, nu - 1) or vi in (0, nv - 1)
                point = grid[vi][ui]
                if not is_boundary and bvh is not None:
                    hit = bvh.find_nearest(point)
                    if hit and hit[0] is not None:
                        point = hit[0]
                index_of[(ui, vi)] = len(verts)
                if is_boundary:
                    boundary_local_indices.append(len(verts))
                verts.append(point)
                uvs.append((ui / span_u, vi / span_v))

        faces = []
        for vi in range(span_v):
            for ui in range(span_u):
                a = index_of[(ui, vi)]
                b = index_of[(ui + 1, vi)]
                c = index_of[(ui + 1, vi + 1)]
                d = index_of[(ui, vi + 1)]
                faces.append((a, b, c, d))

        corner_local_indices = [
            index_of[(0, 0)],
            index_of[(span_u, 0)],
            index_of[(span_u, span_v)],
            index_of[(0, span_v)],
        ]

        return GenerationResult(verts, faces, uvs, corner_local_indices, boundary_local_indices)
