from .. import constants
from .. import geometry
from .base import Generator, GenerationResult


def _dedup_face(face):
    """Drop consecutive duplicate indices in a face loop (used where a Coons
    row collapses to a single apex vertex, turning a quad into a triangle).
    Returns None if fewer than 3 unique vertices remain.
    """
    result = []
    for idx in face:
        if not result or result[-1] != idx:
            result.append(idx)
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    if len(result) < 3:
        return None
    return tuple(result)


class TriangleGenerator(Generator):
    name = constants.TRIANGLE

    def matches(self, num_sides):
        return num_sides == 3

    def default_spans(self, sides):
        """sides: list of 3 point-lists (already resolved to Vectors), walking
        the patch boundary in order."""
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
        if len(sides) != 3:
            raise ValueError("TriangleGenerator expects exactly 3 sides")

        span = max(1, int(span_settings.get("span", 1)))

        side_ab, side_bc, side_ca = sides

        r_ab = geometry.resample_polyline_by_arclength(side_ab, span + 1)
        r_bc = geometry.resample_polyline_by_arclength(side_bc, span + 1)
        r_ca = geometry.resample_polyline_by_arclength(side_ca, span + 1)

        grid = geometry.fan_collapsed_grid(r_ab, r_bc, r_ca)

        nu = span + 1
        nv = span + 1

        verts = []
        uvs = []
        index_of = {}
        apex_index = None
        boundary_local_indices = []

        for vi in range(nv):
            for ui in range(nu):
                if vi == span:
                    # apex row: every column collapses to the same vertex
                    if apex_index is None:
                        apex_index = len(verts)
                        verts.append(grid[vi][0])
                        uvs.append((0.5, 1.0))
                        boundary_local_indices.append(apex_index)
                    index_of[(ui, vi)] = apex_index
                    continue

                is_boundary = ui in (0, nu - 1) or vi == 0
                point = grid[vi][ui]
                if not is_boundary and bvh is not None:
                    hit = bvh.find_nearest(point)
                    if hit and hit[0] is not None:
                        point = hit[0]
                index_of[(ui, vi)] = len(verts)
                if is_boundary:
                    boundary_local_indices.append(len(verts))
                verts.append(point)
                uvs.append((ui / span, vi / span))

        faces = []
        for vi in range(span):
            for ui in range(span):
                a = index_of[(ui, vi)]
                b = index_of[(ui + 1, vi)]
                c = index_of[(ui + 1, vi + 1)]
                d = index_of[(ui, vi + 1)]
                face = _dedup_face((a, b, c, d))
                if face is not None:
                    faces.append(face)

        corner_local_indices = [
            index_of[(0, 0)],
            index_of[(span, 0)],
            apex_index,
        ]

        return GenerationResult(verts, faces, uvs, corner_local_indices, boundary_local_indices)
