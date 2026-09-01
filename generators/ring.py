"""Band generator for patches bounded by TWO closed loops.

That covers two shapes at once:

- a face with a hole in it (a slot in a panel): outer boundary + hole boundary;
- a tube-like face with no corners at all (a fillet running all the way round,
  a cylinder wall): two rim loops.

Both are filled the same way -- a ring of quads running around the patch
(`span_u`, "around") and across the gap between the two loops (`span_v`,
"across"). Unlike the other generators this one is never chosen by side count;
`operators` picks it when a patch turns out to have two boundary loops.

How the two loops are paired against each other is what decides whether the
rungs run straight across the band or all lean by the same small angle; see
the note above `phase_align`.

Two things it deliberately does NOT do yet, both inherited from the single
shared span model: the loops are matched by arc length, not by pairing their
corners, so a hole shaped very differently from the outer boundary gives a
distorted band (splitting the face in Plasticity is the better answer there);
and spans are not propagated *into* a ring from its neighbours, since "around"
is one number for the whole loop rather than a per-side one. Spans are still
propagated *out* of it, per side (see operators' commit path).
"""
import math
from typing import TYPE_CHECKING, Any

import mathutils

from .. import constants
from .. import geometry
from .base import Generator, GenerationResult

if TYPE_CHECKING:
    from mathutils.bvhtree import BVHTree

# One boundary loop, already split into sides and resolved to points: a ring
# takes two of them (outer first, then the hole).
Loop = list[list[mathutils.Vector]]


def polyline_length(points: list[mathutils.Vector]) -> float:
    return sum((b - a).length for a, b in zip(points, points[1:]))


def allocate_segments(lengths: list[float], total: int) -> list[int]:
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


def ring_from_sides(
    sides: list[list[mathutils.Vector]], total: int
) -> tuple[list[mathutils.Vector], list[int], list[int]]:
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


# --- is this really a band? --------------------------------------------------
#
# Two boundary loops is a *topological* annulus, and this generator fills any
# annulus. Whether it should is another question. A washer, a tube wall, a
# fillet running all the way round a boss: the gap between the two loops is
# roughly the same everywhere, and a ring of quads across it is exactly right.
# A 200x100 plate with a 5mm hole is also an annulus, and filling it as a band
# is a disaster -- both loops must end up with the same number of points, so
# either the hole gets a hundred of them or the plate's outline gets twelve,
# and every quad is stretched the width of the plate.
#
# The two are told apart by how *even* the gap is, and by how far apart the two
# perimeters are. Both limits are deliberately generous: a band whose hole is a
# different shape from its outer boundary is still a band, and the cost of
# calling one a plate is worse than the cost of the reverse.
BAND_GAP_SPREAD = 4.0       # widest gap over narrowest, sampled around the loop
BAND_PERIMETER_RATIO = 6.0  # outer perimeter over inner


def band_gaps(loops: list[Loop], samples: int = 16) -> list[float]:
    """Distance from a sample of outer-loop points to the nearest inner-loop
    point, walking the outer boundary."""
    outer = [p for side in loops[0] for p in side]
    inner = [p for side in loops[1] for p in side]
    if not outer or not inner:
        return []
    step = max(1, len(outer) // samples)
    return [min((p - q).length for q in inner) for p in outer[::step]]


def is_band(loops: list[Loop]) -> bool:
    """True when the two loops sit at a comparable distance all the way round,
    i.e. when a ring of quads across them is the right fill. See above.
    """
    if len(loops) != 2:
        return False

    gaps = band_gaps(loops)
    if len(gaps) < 3:
        return False
    widest = max(gaps)
    if widest <= 1e-12:
        return True  # the two loops coincide: degenerate either way, and a
        # zero-width band is at least what the geometry says it is.
    # Floored, so one sample landing on a point the two loops share cannot make
    # an otherwise even band look infinitely uneven.
    narrowest = max(min(gaps), widest * 1e-3)
    if widest > narrowest * BAND_GAP_SPREAD:
        return False

    outer = sum(polyline_length(side) for side in loops[0])
    inner = sum(polyline_length(side) for side in loops[1])
    if inner <= 1e-12:
        return False
    return max(outer, inner) <= min(outer, inner) * BAND_PERIMETER_RATIO


def around_count(loops: list[Loop], span_u: int) -> int:
    """Points around the ring for a given "around" span.

    Both loops must come out with exactly the same count, and neither can have
    fewer points than it has sides, so the two side counts are a floor here.
    The commit path needs the same number to re-derive how the ring split its
    span per side, hence one definition shared by both.
    """
    return max(int(span_u), len(loops[0]), len(loops[1]), 3)


# --- pairing the two loops --------------------------------------------------
#
# Every rung of the band runs from outer[i] to inner[i], so how the two loops
# are indexed against each other *is* the shape of the quads. Two things have
# to be recovered: the direction (a hole winds the opposite way from the face's
# outer boundary) and where inner[0] sits.
#
# `align_rings` searches whole indices, which is all it can do once both loops
# are resampled -- and that leaves up to half a step of rotation unaccounted
# for. On an annulus that residue is not noise: it is a *constant* skew, the
# same small angle on every rung, which is precisely the "the edges aren't
# straight across" look. Half a step of 64 is about 2.8 degrees.
#
# `phase_align` fixes it by choosing where the inner loop is *sampled from*
# rather than which sample to start at, so the residue goes to zero. It is only
# safe on a loop with no corners of its own: a corner is an untouched source
# vertex welded by identity, and moving one while keeping its name would make a
# later patch reuse a vertex that is no longer there. A cornerless rim has no
# such name to keep -- its start is wherever the half-edge walk happened to
# begin, which nothing else in the model agrees on anyway.


def closed_points(side: list[mathutils.Vector]) -> list[mathutils.Vector]:
    """A closed side's points without the repeated closing vertex."""
    if len(side) > 1 and (side[0] - side[-1]).length < 1e-9:
        return list(side[:-1])
    return list(side)


def _segment_lengths(points: list[mathutils.Vector]) -> list[float]:
    """Length of every segment of the closed polyline, last wrapping to first."""
    n = len(points)
    return [(points[(i + 1) % n] - points[i]).length for i in range(n)]


def closest_arclength(points: list[mathutils.Vector], target: mathutils.Vector) -> float:
    """How far along the closed polyline the point nearest `target` sits."""
    n = len(points)
    best_distance = None
    best_at = 0.0
    travelled = 0.0
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        segment = (b - a).length
        if segment > 1e-12:
            factor = (target - a).dot(b - a) / (segment * segment)
            factor = min(1.0, max(0.0, factor))
        else:
            factor = 0.0
        distance = (target - a.lerp(b, factor)).length
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_at = travelled + factor * segment
        travelled += segment
    return best_at


def rotate_closed(
    points: list[mathutils.Vector], distance: float
) -> list[mathutils.Vector]:
    """The same closed polyline, starting `distance` along it.

    Resampling anchors on the first point, so rotating the input is how a
    phase is applied -- there is nothing to add to `resample_polyline_by_arclength`.
    """
    lengths = _segment_lengths(points)
    total = sum(lengths)
    if total <= 1e-12:
        return list(points)
    distance %= total

    n = len(points)
    travelled = 0.0
    for i in range(n):
        if travelled + lengths[i] >= distance - 1e-12:
            remainder = distance - travelled
            factor = remainder / lengths[i] if lengths[i] > 1e-12 else 0.0
            start = points[i].lerp(points[(i + 1) % n], factor)
            rest = [points[(i + 1 + k) % n] for k in range(n)]
            # Drop a wrapped point that lands on the new start, or the resample
            # sees a zero-length segment where the seam used to be.
            if rest and (rest[-1] - start).length < 1e-9:
                rest = rest[:-1]
            return [start] + rest
        travelled += lengths[i]
    return list(points)


def phase_align(
    outer: list[mathutils.Vector],
    inner_loop: list[mathutils.Vector],
    count: int,
    samples: int = 24,
) -> list[mathutils.Vector]:
    """Resample `inner_loop` into `count` points, each facing its outer partner.

    The phase is read off the geometry rather than searched: for each outer
    point, the arc-length of the nearest point on the inner loop says where
    that rung *wants* to land, and the offset it implies is
    `t_i - i * L / count`. Those offsets agree to within noise on a real band,
    so their circular mean is the phase -- circular because they live on a
    loop, where 0 and L are the same answer and a plain average of values
    either side of the seam lands halfway round.

    Both directions are tried: a hole winds the opposite way from the outer
    boundary, and the nearest-point map cannot tell which way round it is.
    """
    if len(inner_loop) < 3 or count < 3:
        return []

    best = None
    for candidate in (inner_loop, list(reversed(inner_loop))):
        lengths = _segment_lengths(candidate)
        total = sum(lengths)
        if total <= 1e-12:
            continue

        step = max(1, len(outer) // samples)
        accumulated = mathutils.Vector((0.0, 0.0))
        for i in range(0, len(outer), step):
            at = closest_arclength(candidate, outer[i])
            offset = (at - i * total / len(outer)) % total
            angle = 2.0 * math.pi * offset / total
            accumulated += mathutils.Vector((math.cos(angle), math.sin(angle)))

        if accumulated.length < 1e-9:
            # The offsets cancelled out: no phase is better than another, which
            # means this is not a band the map can read. Leave it at zero and
            # let the cost below decide between the two directions.
            phase = 0.0
        else:
            phase = (math.atan2(accumulated.y, accumulated.x)
                     % (2.0 * math.pi)) / (2.0 * math.pi) * total

        rotated = rotate_closed(candidate, phase)
        points = geometry.resample_polyline_by_arclength(
            rotated + [rotated[0]], count + 1)[:-1]
        cost = sum((outer[i] - points[i]).length
                   for i in range(0, len(outer), step))
        if best is None or cost < best[0]:
            best = (cost, points)

    return best[1] if best else []


def align_rings(
    outer: list[mathutils.Vector], inner: list[mathutils.Vector]
) -> tuple[list[mathutils.Vector], dict[int, int]]:
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

    def order_at(reverse: bool, offset: int, i: int) -> int:
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
    name = constants.RING

    def matches(self, num_sides: int) -> bool:
        return False  # chosen by loop count, never by side count

    def _target_edge(self, loops: list[Loop]) -> float:
        lengths = [(b - a).length
                   for sides in loops for side in sides for a, b in zip(side, side[1:])]
        return (sum(lengths) / len(lengths)) if lengths else 1.0

    def default_spans(self, loops: list[Loop]) -> dict[str, int]:
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

    def generate(
        self,
        loops: list[Loop],
        span_settings: dict[str, Any],
        bvh: "BVHTree | None" = None,
    ) -> GenerationResult:
        if len(loops) != 2:
            raise ValueError("RingGenerator expects exactly two boundary loops")

        outer_sides, inner_sides = loops[0], loops[1]
        across = max(1, int(span_settings.get("span_v", 1)))
        around = around_count(loops, span_settings.get("span_u", 1))

        outer, outer_corners, outer_alloc = ring_from_sides(outer_sides, around)
        n = len(outer)
        if n < 3:
            raise ValueError("Ring patch boundary is degenerate")

        # A hole with corners of its own has to keep them: they are untouched
        # source vertices, welded to neighbouring patches by identity. A
        # cornerless rim has no such name -- its start is wherever the
        # half-edge walk began -- so it is free to be sampled from wherever
        # makes the rungs run straight across. See the note above phase_align.
        inner_cornerless = len(inner_sides) == 1
        phased = (phase_align(outer, closed_points(inner_sides[0]), n)
                  if inner_cornerless else [])

        if phased:
            inner = phased
            inner_corners, inner_alloc = [0], [n]
            inner_position_of = {i: i for i in range(n)}
        else:
            inner, inner_corners, inner_alloc = ring_from_sides(inner_sides, around)
            if len(inner) != n:
                raise ValueError("Ring patch boundary is degenerate")
            inner, inner_position_of = align_rings(outer, inner)

        verts = []
        uvs = []
        for r in range(across + 1):
            t = r / across
            # Annulus UVs: the ring closes on itself in UV space too, so the
            # seam column isn't stretched the way a flat u=i/n layout would be.
            radius = 1.0 - 0.6 * t
            # Boundary rows are normally left exactly where the loops put them:
            # they are samples of the real boundary, and moving them would move
            # them off whatever a neighbouring patch welds to. A *phased* rim
            # is the exception. Its points no longer land on source vertices --
            # that is the whole point of the phase -- so on a curved rim every
            # one of them sits mid-chord, a sagitta inside the true surface.
            # They are not shared with anything either (their corner id was
            # dropped for the same reason), so they get the same reprojection
            # the interior does.
            reproject = 0 < r < across or (phased and r == across)
            for i in range(n):
                point = outer[i].lerp(inner[i], t)
                if reproject and bvh is not None:
                    hit = bvh.find_nearest(point)
                    if hit and hit[0] is not None:
                        point = hit[0]
                verts.append(point)

                angle = 2.0 * math.pi * i / n
                uvs.append((0.5 + 0.5 * radius * math.cos(angle),
                            0.5 + 0.5 * radius * math.sin(angle)))

        def index_of(r: int, i: int) -> int:
            return r * n + (i % n)

        faces = []
        for r in range(across):
            for i in range(n):
                faces.append((index_of(r, i), index_of(r, i + 1),
                              index_of(r + 1, i + 1), index_of(r + 1, i)))

        # Corners first of the outer loop then of the hole, matching the order
        # operators._prepare_patch collects their source vertex ids in.
        corner_local_indices = [index_of(0, c) for c in outer_corners]
        if not phased:
            corner_local_indices += [index_of(across, inner_position_of[c])
                                     for c in inner_corners]
        # A phased rim's points sit wherever the alignment put them, so none of
        # them *is* the source vertex the loop started at. The list is simply
        # left short: the caller zips it against corner_source_ids, so the
        # hole's id is dropped rather than stamped onto a point that moved --
        # which would make a later patch weld to a vertex that isn't there.
        # It welds by proximity like every other boundary point instead.

        boundary_local_indices = [index_of(0, i) for i in range(n)]
        boundary_local_indices += [index_of(across, i) for i in range(n)]

        result = GenerationResult(verts, faces, uvs, corner_local_indices, boundary_local_indices)
        # Kept for the commit path: propagating a ring's spans to its neighbours
        # is per side, and only the generator knows how it split "around" up.
        result.side_allocation = (outer_alloc, inner_alloc)
        return result
