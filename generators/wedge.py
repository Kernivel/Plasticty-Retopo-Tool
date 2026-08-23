from .. import constants
from .. import geometry
from .base import Generator, GenerationResult
from .triangle import _dedup_face


class WedgeGenerator(Generator):
    """Two-sided patch: a lens bounded by two curves meeting at two corners
    (the shape a fillet collapses to at its ends). Both sides share the same
    span, as they must stay compatible along the whole patch.
    """

    name = constants.WEDGE

    def matches(self, num_sides):
        return num_sides == 2

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
        span_u = max(2, round(avg_side / max(target_edge, 1e-6)))
        return {"span_u": span_u, "span_v": 1}

    def generate(self, sides, span_settings, bvh=None):
        if len(sides) != 2:
            raise ValueError("WedgeGenerator expects exactly 2 sides")

        span_u = max(2, int(span_settings.get("span_u", 2)))
        span_v = max(1, int(span_settings.get("span_v", 1)))

        side_ab, side_ba = sides

        # Both curves run A -> B once the second one is reversed, so the patch
        # becomes a Coons quad whose left and right sides collapse to the two
        # corner points.
        curve_0 = geometry.resample_polyline_by_arclength(side_ab, span_u + 1)
        curve_1 = geometry.resample_polyline_by_arclength(list(reversed(side_ba)), span_u + 1)

        corner_a = curve_0[0]
        corner_b = curve_0[-1]

        side_bottom = curve_0
        side_top = list(reversed(curve_1))          # P11 -> P01
        side_right = [corner_b] * (span_v + 1)      # P10 -> P11, both corner B
        side_left = [corner_a] * (span_v + 1)       # P01 -> P00, both corner A

        grid = geometry.coons_patch_grid(side_bottom, side_right, side_top, side_left, span_u, span_v)

        nu = span_u + 1
        nv = span_v + 1

        verts = []
        uvs = []
        index_of = {}
        boundary_local_indices = []
        corner_a_index = None
        corner_b_index = None

        for vi in range(nv):
            for ui in range(nu):
                # the whole u=0 column is corner A, the whole u=span_u column is corner B
                if ui == 0:
                    if corner_a_index is None:
                        corner_a_index = len(verts)
                        verts.append(grid[vi][ui])
                        uvs.append((0.0, 0.5))
                        boundary_local_indices.append(corner_a_index)
                    index_of[(ui, vi)] = corner_a_index
                    continue
                if ui == span_u:
                    if corner_b_index is None:
                        corner_b_index = len(verts)
                        verts.append(grid[vi][ui])
                        uvs.append((1.0, 0.5))
                        boundary_local_indices.append(corner_b_index)
                    index_of[(ui, vi)] = corner_b_index
                    continue

                is_boundary = vi in (0, nv - 1)
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
                face = _dedup_face((a, b, c, d))
                if face is not None:
                    faces.append(face)

        corner_local_indices = [corner_a_index, corner_b_index]

        return GenerationResult(verts, faces, uvs, corner_local_indices, boundary_local_indices)
