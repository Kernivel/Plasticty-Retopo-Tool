"""Band generator for patches bounded by TWO closed loops.

That covers two shapes at once:

- a face with a hole in it (a slot in a panel): outer boundary + hole boundary;
- a tube-like face with no corners at all (a fillet running all the way round,
  a cylinder wall): two rim loops.

Both are filled the same way -- a ring of quads running around the patch
(`span_u`, "around") and across the gap between the two loops (`span_v`,
"across"). Unlike the other generators this one is never chosen by side count;
`operators` picks it when a patch turns out to have two boundary loops.

Two things it deliberately does NOT do yet, both inherited from the single
shared span model: the two loops are matched by arc length, not by pairing
their corners, so a hole shaped very differently from the outer boundary gives
a distorted band (splitting the face in Plasticity is the better answer there);
and spans are not propagated *into* a ring from its neighbours, since "around"
is one number for the whole loop rather than a per-side one. Spans are still
propagated *out* of it, per side (see operators' commit path).
"""
import math

from .. import geometry
from .base import Generator, GenerationResult


def polyline_length(points):
    return sum((b - a).length for a, b in zip(points, points[1:]))


def allocate_segments(lengths, total):
    """Split `total` segments among sides proportionally to `lengths`, with at
    least one segment per side (largest-remainder rounding).

    `total` is raised to the number of sides if it is smaller -- a side can't
    have zero segments, and both loops of a ring must end up with exactly the
    same number of points.
    """
    n = len(lengths)
    if n == 0:
        return []

    total = max(int(total), n)
    span_total = sum(lengths)
    if span_total <= 0.0:
        raw = [total / n] * n
    else:
        raw = [total * length / span_total for length in lengths]

    alloc = [max(1, int(math.floor(value))) for value in raw]
    diff = total - sum(alloc)

    if diff > 0:
        # hand the leftovers to the sides with the largest dropped fraction
        order = sorted(range(n), key=lambda i: raw[i] - math.floor(raw[i]), reverse=True)
        for k in range(diff):
            alloc[order[k % n]] += 1
    while diff < 0:
        reducible = [i for i in range(n) if alloc[i] > 1]
        if not reducible:
            break
        alloc[max(reducible, key=lambda i: alloc[i])] -= 1
        diff += 1

    return alloc


def ring_from_sides(sides, total):
    """Resample a loop's sides into exactly `total` points walking around it.

    Returns (points, corner_indices, alloc): `corner_indices` are the positions
    in `points` of each side's first point, i.e. the patch corners -- those are
    untouched source-mesh vertices, so they stay weldable by identity.
    """
    alloc = allocate_segments([polyline_length(side) for side in sides], total)

    points = []
    corner_indices = []
    for side, count in zip(sides, alloc):
        resampled = geometry.resample_polyline_by_arclength(side, count + 1)
        corner_indices.append(len(points))
        points.extend(resampled[:-1])  # the next side re-adds the shared corner

    return points, corner_indices, alloc


def around_count(loops, span_u):
    """Points around the ring for a given "around" span.

    Both loops must come out with exactly the same count, and neither can have
    fewer points than it has sides, so the two side counts are a floor here.
    The commit path needs the same number to re-derive how the ring split its
    span per side, hence one definition shared by both.
    """
    return max(int(span_u), len(loops[0]), len(loops[1]), 3)


def align_rings(outer, inner):
    """Re-index `inner` so that inner[i] faces outer[i].

    A hole's boundary winds the opposite way from the face's outer boundary,
    and neither has a meaningful start point, so both the direction and the
    starting offset have to be recovered -- otherwise the band comes out
    twisted or turned inside out. Every (direction, offset) candidate is scored
    on a subsample of the ring, which keeps this O(n) rather than O(n^2).

    Returns (aligned_points, position_of_original_index).
    """
    n = len(outer)
    samples = range(0, n, max(1, n // 16))

    def order_at(reverse, offset, i):
        return (offset - i) % n if reverse else (offset + i) % n

    best = None
    for reverse in (False, True):
        for offset in range(n):
            cost = sum((outer[i] - inner[order_at(reverse, offset, i)]).length
                       for i in samples)
            if best is None or cost < best[0]:
                best = (cost, reverse, offset)

    _cost, reverse, offset = best
    order = [order_at(reverse, offset, i) for i in range(n)]
    position_of = {original: i for i, original in enumerate(order)}
    return [inner[original] for original in order], position_of


class RingGenerator(Generator):
    name = "Ring"

    def matches(self, num_sides):
        return False  # chosen by loop count, never by side count

    def _target_edge(self, loops):
        lengths = [(b - a).length
                   for sides in loops for side in sides for a, b in zip(side, side[1:])]
        return (sum(lengths) / len(lengths)) if lengths else 1.0

    def default_spans(self, loops):
        outer_sides, inner_sides = loops[0], loops[1]
        target_edge = max(self._target_edge(loops), 1e-6)

        outer_points = [p for side in outer_sides for p in side]
        inner_points = [p for side in inner_sides for p in side]

        perimeter = (sum(polyline_length(side) for side in outer_sides)
                     + sum(polyline_length(side) for side in inner_sides)) * 0.5
        around = max(3, round(perimeter / target_edge))

        # How wide the band is: the typical distance from the outer boundary to
        # the nearest point of the hole, sampled rather than measured in full.
        step = max(1, len(outer_points) // 8)
        gaps = [min((p - q).length for q in inner_points)
                for p in outer_points[::step]] if inner_points else []
        across = max(1, round((sum(gaps) / len(gaps)) / target_edge)) if gaps else 1

        return {"span_u": around, "span_v": across}

    def generate(self, loops, span_settings, bvh=None):
        if len(loops) != 2:
            raise ValueError("RingGenerator expects exactly two boundary loops")

        outer_sides, inner_sides = loops[0], loops[1]
        across = max(1, int(span_settings.get("span_v", 1)))
        around = around_count(loops, span_settings.get("span_u", 1))

        outer, outer_corners, outer_alloc = ring_from_sides(outer_sides, around)
        inner, inner_corners, inner_alloc = ring_from_sides(inner_sides, around)
        n = len(outer)
        if n < 3 or len(inner) != n:
            raise ValueError("Ring patch boundary is degenerate")

        inner, inner_position_of = align_rings(outer, inner)

        verts = []
        uvs = []
        for r in range(across + 1):
            t = r / across
            # Annulus UVs: the ring closes on itself in UV space too, so the
            # seam column isn't stretched the way a flat u=i/n layout would be.
            radius = 1.0 - 0.6 * t
            for i in range(n):
                point = outer[i].lerp(inner[i], t)
                if 0 < r < across and bvh is not None:
                    hit = bvh.find_nearest(point)
                    if hit and hit[0] is not None:
                        point = hit[0]
                verts.append(point)

                angle = 2.0 * math.pi * i / n
                uvs.append((0.5 + 0.5 * radius * math.cos(angle),
                            0.5 + 0.5 * radius * math.sin(angle)))

        def index_of(r, i):
            return r * n + (i % n)

        faces = []
        for r in range(across):
            for i in range(n):
                faces.append((index_of(r, i), index_of(r, i + 1),
                              index_of(r + 1, i + 1), index_of(r + 1, i)))

        # Corners first of the outer loop then of the hole, matching the order
        # operators._prepare_patch collects their source vertex ids in.
        corner_local_indices = [index_of(0, c) for c in outer_corners]
        corner_local_indices += [index_of(across, inner_position_of[c]) for c in inner_corners]

        boundary_local_indices = [index_of(0, i) for i in range(n)]
        boundary_local_indices += [index_of(across, i) for i in range(n)]

        result = GenerationResult(verts, faces, uvs, corner_local_indices, boundary_local_indices)
        # Kept for the commit path: propagating a ring's spans to its neighbours
        # is per side, and only the generator knows how it split "around" up.
        result.side_allocation = (outer_alloc, inner_alloc)
        return result
