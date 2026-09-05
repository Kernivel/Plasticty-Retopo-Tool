"""Corner detection and side-splitting for a patch boundary loop.

Two ways to find corners, because neither alone is right:

- **angle**: the vertex where the boundary polyline turns sharper than a
  threshold. Purely geometric, so it is fooled by anything gentle -- a 30
  degree chamfer reads as a smooth stretch and gets swallowed into the middle
  of a side.
- **synthesised**: a boundary with no corner at all -- a disc, a circular
  pocket floor, any face bounded by one closed curve -- gets four, evenly
  spaced by arc length. Not a refinement: without them such a face has a single
  side, `find_generator` has nothing that takes one (Wedge 2, Triangle 3,
  Quad 4, N-Side 5+), generation returns None and the face simply cannot be
  hovered or picked at all. Four is what makes it a Quad, i.e. a Coons grid on
  the disc.
- **topology**: the vertex where the *neighbouring patch changes*
  (`patch_data.boundary_neighbours_for_loop`). That is a genuine B-rep vertex,
  the junction between two CAD edges, and it does not care how gentle the turn
  is. It misses the opposite case: a face whose whole boundary runs against one
  single neighbour has no such junction at all, however square it looks.

So the default is the union of both. `state.corner_method` switches.
"""
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Annotations only -- this module stays free of Blender imports so it can
    # be exercised on plain point tables.
    import mathutils

# A closed boundary loop, as vertex indices, plus the table those index into.
Loop = list[int]
Positions = dict[int, "mathutils.Vector"]
# A side is the run of vertex indices from one corner up to and including the
# next; consecutive sides share their corner.
Side = list[int]


def _angle_at(
    prev_co: "mathutils.Vector", co: "mathutils.Vector", next_co: "mathutils.Vector"
) -> float:
    """Interior turning angle (degrees) of the boundary polyline at `co`.

    180 degrees means dead straight, smaller values mean a sharper corner.
    """
    v_in = co - prev_co
    v_out = next_co - co
    if v_in.length < 1e-9 or v_out.length < 1e-9:
        return 180.0
    v_in = v_in.normalized()
    v_out = v_out.normalized()
    dot = max(-1.0, min(1.0, v_in.dot(v_out)))
    deviation = math.degrees(math.acos(dot))  # 0 = straight, 180 = full reversal
    return 180.0 - deviation


def detect_corners(
    loop: Loop, positions: Positions, angle_threshold: float = 135.0
) -> list[int]:
    """Return the indices (into `loop`) of the vertices considered corners.

    `positions` maps vertex index -> mathutils.Vector (world/object space).
    A vertex is a corner if the boundary polyline turns sharper than
    `angle_threshold` degrees there.
    """
    n = len(loop)
    corners = []
    for i in range(n):
        prev_v = loop[(i - 1) % n]
        cur_v = loop[i]
        next_v = loop[(i + 1) % n]
        angle = _angle_at(positions[prev_v], positions[cur_v], positions[next_v])
        if angle < angle_threshold:
            corners.append(i)
    return corners


def detect_topological_corners(
    loop: Loop, neighbour_ids: list[int | None] | None
) -> list[int]:
    """Indices (into `loop`) where the patch on the other side changes.

    `neighbour_ids[i]` is the face across segment loop[i] -> loop[i+1], so the
    vertex loop[i] is a junction when the segment arriving at it and the
    segment leaving it face different patches.
    """
    count = len(loop)
    if not neighbour_ids or len(neighbour_ids) != count:
        return []
    return [i for i in range(count)
            if neighbour_ids[(i - 1) % count] != neighbour_ids[i]]


def deviations(loop: Loop, positions: Positions) -> list[float]:
    """How far the boundary bends at each vertex, in degrees.

    0 is dead straight, 90 is a square corner. The complement of `_angle_at`,
    and the quantity everything about corner *strength* is measured in.
    """
    n = len(loop)
    return [180.0 - _angle_at(positions[loop[(i - 1) % n]],
                              positions[loop[i]],
                              positions[loop[(i + 1) % n]])
            for i in range(n)]


# A corner list is reduced only where the ranking shows a genuine *cliff*: the
# candidates sorted by how much they bend fall off by at least this factor from
# one to the next. A ratio rather than an absolute limit, because that is the
# only thing that separates the two cases -- on a real polygon every corner
# bends about as much as the others and there is no cliff anywhere, while a
# curve sampled into corners sits well below the real ones and the drop is
# unmistakable.
CORNER_CLIFF = 1.5
# Cutting all the way down to a triangle is a much bigger claim than cutting to
# a quad -- it says one whole corner of what looked like a four-sided face was
# imaginary -- so it takes a far clearer cliff. Without the distinction, a
# rectangle with one chamfered corner (three 90s and two 45s) came out as a
# triangle on a 2:1 ratio.
CORNER_CLIFF_TO_TRIANGLE = 2.5
# Reducing below this would start inventing shapes rather than removing noise:
# three sides is the fewest any grid generator wants from a corner list.
MIN_DOMINANT_CORNERS = 3


def dominant_corners(
    loop: Loop,
    positions: Positions,
    corners: list[int],
    protected: "set[int] | tuple[int, ...]" = (),
) -> list[int]:
    """Drop the corners that are only noise, when the patch has too many.

    A face comes back with more than four sides for two very different
    reasons, and they need opposite treatment. Either it genuinely has them --
    a hexagonal boss, a five-sided transition -- and every side matters; or the
    angle test caught the tessellation of something smooth alongside the real
    corners, and those extra sides are what turn a quad into an N-Side fan of
    triangles converging on a made-up centre point.

    Telling them apart is a question of *contrast*, not of any absolute angle:
    see CORNER_CLIFF. A boundary with no cliff in it is handed back untouched,
    which is what keeps a real hexagon six-sided.

    `protected` corners are exempt and take no part in the ranking. Those are
    the *topological* ones: a junction between two CAD edges is a fact the mesh
    states outright, not an inference from how sharply something bends, and a
    gentle chamfer's junction bends barely at all -- dropping it for being
    shallow is precisely the bug the topology test was added to fix. Only what
    the angle test guessed at is up for reduction.

    Only ever runs on five or more candidates: at four the answer is already a
    quad, and there is nothing a reduction could improve.
    """
    if len(corners) <= 4:
        return list(corners)

    turn = deviations(loop, positions)
    exempt = set(protected)
    ranked = sorted((index for index in corners if index not in exempt),
                    key=lambda index: turn[index], reverse=True)
    if not ranked:
        return list(corners)

    # `keep` is how many of the ranked candidates survive, so the cliff it
    # names sits between ranked[keep - 1] and ranked[keep] -- both have to
    # exist. Tried nearest-to-four first, and the wider cut before the
    # narrower one on a tie: a quad is the outcome a grid generator handles
    # best, and it is what an over-split patch was supposed to be.
    order = sorted(
        (keep for keep in range(1, len(ranked))
         if keep + len(exempt) >= MIN_DOMINANT_CORNERS),
        key=lambda keep: (abs(keep + len(exempt) - 4), -(keep + len(exempt))))

    cut = None
    best_ratio = 0.0
    for keep in order:
        total_kept = keep + len(exempt)
        needed = CORNER_CLIFF_TO_TRIANGLE if total_kept <= 3 else CORNER_CLIFF
        above = turn[ranked[keep - 1]]
        below = turn[ranked[keep]]
        ratio = above / below if below > 1e-9 else float("inf")
        # Strictly greater, so the earlier candidate in `order` wins a tie.
        if ratio >= needed and ratio > best_ratio:
            best_ratio = ratio
            cut = keep

    if cut is None:
        return list(corners)  # no cliff: every candidate is as real as the rest
    return sorted(exempt | set(ranked[:cut]))


# How much the boundary's turn may vary from one vertex to the next and still
# count as "the same everywhere". Loose enough to absorb the jitter of a
# tessellated circle, far tighter than the gap between a square corner and the
# shallow kink beside it.
UNIFORM_TURN_SPREAD = 1.6


def corners_are_uniform(loop: Loop, positions: Positions, corners: list[int]) -> bool:
    """True when the flagged corners are indistinguishable from the rest of the
    boundary -- every vertex bending about the same amount.

    That is what a coarsely tessellated circle looks like: an eight-segment
    bore turns 45 degrees at every vertex, exactly the default threshold, so
    every one of them reads as a corner and the face becomes an eight-sided
    N-Side fan. It is also, unavoidably, what a real octagon looks like -- the
    two are the same polyline. So this only *reports*: the panel says the
    threshold is doing nothing useful on this patch and lets you raise it,
    rather than guessing which of the two it is and rounding a real octagon
    off in the half of the cases it guesses wrong.
    """
    if len(corners) < 5 or len(corners) < len(loop):
        return False
    turn = sorted(deviations(loop, positions))
    if not turn or turn[-1] <= 1e-6:
        return False
    # Spread measured between two quantiles rather than peak-over-median: the
    # set this has to reject is *bimodal* -- four square corners and four
    # shallow kinks -- and its median sits on whichever mode happens to hold
    # the middle, which made a boundary with obvious contrast read as flat.
    last = len(turn) - 1
    low = turn[int(0.1 * last)]
    high = turn[int(0.9 * last)]
    return high < max(low, 1e-9) * UNIFORM_TURN_SPREAD


FALLBACK_CORNER_COUNT = 4


# The scale the shape of a cornerless boundary is judged at, as a share of its
# perimeter. Small enough to separate a strip's two ends, large enough to see
# past the tessellation: a rounded end spreads its turn over dozens of vertices,
# none of which is a corner on its own.
SHAPE_WINDOW = 0.06
# A boundary whose turn is this uniform has no shape to find -- a circle. Below
# it, the peaks mean something; above it, they are just the mesher's noise.
SHAPE_CONTRAST = 1.35
# Peaks nearer than this along the perimeter are the same feature seen twice.
SHAPE_SEPARATION = 0.12


def _cumulative_lengths(
    loop: Loop, positions: Positions
) -> tuple[list[float], float]:
    """Arc length at each vertex, plus the total, walking the closed loop."""
    n = len(loop)
    cumulative = [0.0]
    for i in range(n):
        cumulative.append(
            cumulative[-1] + (positions[loop[(i + 1) % n]] - positions[loop[i]]).length)
    return cumulative, cumulative[-1]


def _index_at_offset(
    cumulative: list[float], total: float, index: int, offset: float
) -> int:
    """The vertex roughly `offset` of arc length away from `index`."""
    n = len(cumulative) - 1
    target = (cumulative[index] + offset) % total
    return min(range(n), key=lambda i: min(abs(cumulative[i] - target),
                                           total - abs(cumulative[i] - target)))


def shape_turns(loop: Loop, positions: Positions) -> list[float]:
    """How much the boundary turns at each vertex, measured over SHAPE_WINDOW.

    Not the turn *at* the vertex: on a tessellated boundary that is dominated
    by how finely the mesher sampled it. Measured between the directions a
    window before and a window after, it reads the shape instead -- flat along
    a straight run, small on a gentle arc, large where a strip caps off.
    """
    n = len(loop)
    cumulative, total = _cumulative_lengths(loop, positions)
    if total < 1e-12 or n < 4:
        return [0.0] * n

    window = total * SHAPE_WINDOW
    turns = []
    for i in range(n):
        before = positions[loop[_index_at_offset(cumulative, total, i, -window)]]
        here = positions[loop[i]]
        after = positions[loop[_index_at_offset(cumulative, total, i, window)]]
        turns.append(180.0 - _angle_at(before, here, after))
    return turns


def shape_corners(loop: Loop, positions: Positions) -> list[int]:
    """Corners recovered from the boundary's *shape*, or [] if it has none.

    A cornerless loop is not the same as a featureless one. A long strip that
    curves back on itself has no vertex sharp enough for the angle test, but it
    plainly has two ends -- and splitting it anywhere else is what turned it
    into a fan: quarter-perimeter corners land in the middle of its long sides,
    so the "quad" fed to the Coons patch is half a side and half an end.

    Returns however many it finds, up to four, which is what decides the
    generator: two ends make a Wedge (a grid running along the strip), three a
    Triangle, four a Quad. A circle has no peaks at all and gets [].
    """
    n = len(loop)
    turns = shape_turns(loop, positions)
    if not any(turns):
        return []

    strongest = max(turns)
    average = sum(turns) / n
    # A boundary that turns the same everywhere is a circle: any peak in it is
    # noise, and picking one would be picking a direction at random.
    if strongest < 1.0 or strongest < average * SHAPE_CONTRAST:
        return []

    cumulative, total = _cumulative_lengths(loop, positions)
    separation = total * SHAPE_SEPARATION

    def far_enough(candidate: int, chosen: list[int]) -> bool:
        for other in chosen:
            gap = abs(cumulative[candidate] - cumulative[other])
            if min(gap, total - gap) < separation:
                return False
        return True

    window = total * SHAPE_WINDOW

    def is_local_max(index: int) -> bool:
        """A feature is where the turn *peaks*, not merely where it is high.

        Without this the tangency between a strip's straight side and its cap
        gets picked too: it is half as sharp as the cap itself but still well
        above the flat run, and far enough away to survive the separation
        rule. It is not a peak -- the turn keeps rising past it into the cap.
        """
        here = turns[index]
        step = index
        while True:
            step = (step + 1) % n
            gap = abs(cumulative[step] - cumulative[index])
            if min(gap, total - gap) > window or step == index:
                break
            if turns[step] > here + 1e-9:
                return False
        step = index
        while True:
            step = (step - 1) % n
            gap = abs(cumulative[step] - cumulative[index])
            if min(gap, total - gap) > window or step == index:
                break
            if turns[step] > here + 1e-9:
                return False
        return True

    chosen = []
    for index in sorted(range(n), key=lambda i: turns[i], reverse=True):
        if turns[index] < strongest * 0.4:
            break  # everything below this is the flat part of the boundary
        if is_local_max(index) and far_enough(index, chosen):
            chosen.append(index)
        if len(chosen) == FALLBACK_CORNER_COUNT:
            break

    # One corner cannot split a loop into sides, so it is no better than none.
    return sorted(chosen) if len(chosen) >= 2 else []


def synthesise_corners(
    loop: Loop, positions: Positions, count: int = FALLBACK_CORNER_COUNT
) -> list[int]:
    """Corners for a boundary that has none to detect. See the detail form."""
    return synthesise_corners_detail(loop, positions, count)[0]


def synthesise_corners_detail(
    loop: Loop, positions: Positions, count: int = FALLBACK_CORNER_COUNT
) -> tuple[list[int], bool]:
    """(corners, whether they are *arbitrary*) for a boundary with none.

    The shape is asked first (`shape_corners`): a strip, a slot, a rounded
    rectangle all have ends even when no single vertex is sharp. Only a
    boundary with no shape either -- a circle -- falls back to `count` points
    spread evenly by arc length. Arc length rather than index spacing: a
    tessellated circle is not sampled uniformly, so every `n // 4`th vertex
    would bunch the corners wherever the mesher happened to be dense.

    That last case is the only one reported as **arbitrary**, and the flag
    matters downstream. A shape corner is a fact about the boundary -- the end
    of a strip is where it is, and moving it would destroy the very feature it
    marks. A quarter point on a circle is a fact about nothing at all: it says
    only that the loop had to be cut somewhere to have sides, and every
    rotation of the four is as good as every other. `sidematch` uses that
    licence to cut them where a committed neighbour already put its vertices,
    which is the difference between a disc that welds to the ring around it and
    one that cannot (see `_recut_arbitrary_loop`).
    """
    n = len(loop)
    if n <= count:
        return list(range(n)), False

    from_shape = shape_corners(loop, positions)
    if from_shape:
        return from_shape, False

    cumulative, total = _cumulative_lengths(loop, positions)
    if total < 1e-12:
        return list(range(count)), True

    corners = []
    for k in range(count):
        target = total * k / count
        index = min(range(n), key=lambda i: abs(cumulative[i] - target))
        if index not in corners:
            corners.append(index)
    return sorted(corners), True


def complete_corners(
    loop: Loop,
    positions: Positions,
    corners: list[int],
    count: int = FALLBACK_CORNER_COUNT,
) -> list[int]:
    """Add corners until the loop has enough of them to be split into sides.

    One corner is no better than none: `split_into_sides` returns a single side
    running all the way round, `find_generator` has nothing that takes one
    (Wedge 2, Triangle 3, Quad 4, N-Side 5+), generation returns None, and the
    face silently cannot be hovered or picked at all. That is a real shape
    though -- a teardrop, a cone cap cut by one seam, a fillet ending in a
    single point -- so the corner it does have is *kept*, and the missing ones
    are spread by arc length starting from it. Anchoring them on the real
    corner is the whole point: spread from an arbitrary origin instead, and the
    one feature the face actually has lands in the middle of a side.
    """
    n = len(loop)
    if n <= count:
        return list(range(n))
    if len(corners) >= count:
        return sorted(corners)

    cumulative, total = _cumulative_lengths(loop, positions)
    if total < 1e-12:
        return sorted(set(corners) | set(range(count)))

    anchor = cumulative[corners[0]] if corners else 0.0
    chosen = list(corners)
    for k in range(1, count):
        target = (anchor + total * k / count) % total
        index = min(range(n),
                    key=lambda i: min(abs(cumulative[i] - target),
                                      total - abs(cumulative[i] - target)))
        if index not in chosen:
            chosen.append(index)
    return sorted(chosen)


def resolve_corners(
    loop: Loop,
    positions: Positions,
    angle_threshold: float = 135.0,
    neighbour_ids: list[int | None] | None = None,
    method: str = 'BOTH',
    allow_synthesis: bool = True,
) -> list[int]:
    """Corner indices for `loop`. See `resolve_corners_detail`."""
    return resolve_corners_detail(loop, positions, angle_threshold,
                                  neighbour_ids, method, allow_synthesis)[0]


def resolve_corners_detail(
    loop: Loop,
    positions: Positions,
    angle_threshold: float = 135.0,
    neighbour_ids: list[int | None] | None = None,
    method: str = 'BOTH',
    allow_synthesis: bool = True,
) -> tuple[list[int], bool]:
    """(corner indices, whether they are arbitrary) under the chosen method.

    The second value is True only when *nothing* was detected and the corners
    are the four quarter points of a circle -- see `synthesise_corners_detail`
    for why that case is worth telling apart from every other.

    'TOPOLOGY' falls back to the angle test when the boundary has no junction
    at all -- with no corners a patch is one single side, which every
    span-based generator would have to treat as an unusable 1-sided patch.
    Silently retopologising it wrong is worse than ignoring the setting here.

    And when *neither* test finds anything -- a disc, a circular pocket floor,
    any face bounded by one closed curve -- four are synthesised. Without them
    the face has one side, no generator accepts one, and it can't be picked at
    all; see synthesise_corners.

    `allow_synthesis` is what a **ring** turns off. A band between two circles
    reaches the Ring generator directly, never `find_generator`, so a cornerless
    loop gives it no trouble -- and inventing four corners on each of its two
    loops actively hurts: `ring.ring_from_sides` allocates points per side, so
    two loops whose synthesised corners don't face each other get their points
    paired across a shear instead of straight across the band.
    """
    angle_corners = set(detect_corners(loop, positions, angle_threshold))
    topo_corners = set(detect_topological_corners(loop, neighbour_ids))

    if method == 'ANGLE':
        corners = sorted(angle_corners)
    elif method == 'TOPOLOGY':
        # Explicitly asked for junctions: hand back exactly the junctions,
        # unranked. Reducing them here would be overruling the setting.
        return _fill_out(loop, positions, sorted(topo_corners) or sorted(angle_corners),
                         allow_synthesis)
    else:
        corners = sorted(angle_corners | topo_corners)

    corners = dominant_corners(loop, positions, corners, protected=topo_corners)
    return _fill_out(loop, positions, corners, allow_synthesis)


def _fill_out(
    loop: Loop, positions: Positions, corners: list[int], allow_synthesis: bool
) -> tuple[list[int], bool]:
    """Corners as resolved, topped up to a usable count when allowed.

    Fewer than two corners means fewer than two sides, and no generator takes
    one. `allow_synthesis` is what a **ring** turns off: a band between two
    circles reaches the Ring generator directly, so a cornerless loop gives it
    no trouble -- and inventing corners on each of its two loops actively
    hurts, since `ring.ring_from_sides` allocates points per side and two loops
    whose invented corners don't face each other get their points paired across
    a shear instead of straight across the band.
    """
    if len(corners) >= 2 or not allow_synthesis:
        return corners, False
    if corners:
        # One real corner kept and the rest spread from it: the shape's one
        # feature is still on a side boundary, so these are not arbitrary.
        return complete_corners(loop, positions, corners), False
    return synthesise_corners_detail(loop, positions)


def split_into_sides(
    loop: Loop,
    positions: Positions,
    angle_threshold: float = 135.0,
    corner_indices: list[int] | None = None,
) -> list[Side]:
    """Split a closed boundary loop into sides at corner vertices.

    Returns a list of sides; each side is a list of vertex indices from one
    corner up to and including the next corner (so consecutive sides share
    their corner vertex, as expected for a boundary polygon).

    `corner_indices`, if given, replaces the angle test entirely -- that is how
    the addon feeds in a set resolved by `resolve_corners`. The bare
    `angle_threshold` path is the standalone one, used by the tests.
    """
    n = len(loop)
    if n < 2:
        return [list(loop)]

    if corner_indices is None:
        corner_positions = set(detect_corners(loop, positions, angle_threshold))
    else:
        corner_positions = set(corner_indices)

    corner_positions = sorted(corner_positions)

    if not corner_positions:
        # No corner found (e.g. a full circle boundary): treat the whole loop
        # as a single side with an arbitrary start.
        return [loop + [loop[0]]]

    sides = []
    for k in range(len(corner_positions)):
        start_i = corner_positions[k]
        end_i = corner_positions[(k + 1) % len(corner_positions)]
        side = []
        i = start_i
        while True:
            side.append(loop[i])
            if i == end_i:
                break
            i = (i + 1) % n
        sides.append(side)

    return sides


def merge_small_sides(
    index_sides: list[Side], positions: Positions, tolerance: float
) -> list[Side]:
    """Merge boundary sides shorter than `tolerance` into their next
    neighbor, repeatedly, until none remain below the threshold (or only a
    minimal 3-sided patch is left). Operates on vertex-index sides, as
    returned by split_into_sides.
    """
    if tolerance <= 0 or len(index_sides) <= 3:
        return index_sides

    sides = [list(s) for s in index_sides]

    def length(s: Side) -> float:
        return sum((positions[b] - positions[a]).length for a, b in zip(s, s[1:]))

    while len(sides) > 3:
        lengths = [length(s) for s in sides]
        i = min(range(len(sides)), key=lambda k: lengths[k])
        if lengths[i] >= tolerance:
            break
        n = len(sides)
        nxt = (i + 1) % n
        merged = sides[i][:-1] + sides[nxt]
        new_sides = []
        for k in range(n):
            if k == i:
                continue
            new_sides.append(merged if k == nxt else sides[k])
        sides = new_sides

    return sides
