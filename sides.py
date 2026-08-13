"""Corner detection and side-splitting for a patch boundary loop."""
import math


def _angle_at(prev_co, co, next_co):
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


def detect_corners(loop, positions, angle_threshold=135.0):
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


def split_into_sides(loop, positions, angle_threshold=135.0, manual_corner_indices=None):
    """Split a closed boundary loop into sides at corner vertices.

    Returns a list of sides; each side is a list of vertex indices from one
    corner up to and including the next corner (so consecutive sides share
    their corner vertex, as expected for a boundary polygon).

    `manual_corner_indices`, if given, are indices into `loop` that are forced
    to be corners regardless of the angle test (used for manual corner
    placement as described in the tool's N-Side workflow).
    """
    n = len(loop)
    if n < 2:
        return [list(loop)]

    corner_positions = set(detect_corners(loop, positions, angle_threshold))
    if manual_corner_indices:
        corner_positions.update(manual_corner_indices)

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


def merge_small_sides(index_sides, positions, tolerance):
    """Merge boundary sides shorter than `tolerance` into their next
    neighbor, repeatedly, until none remain below the threshold (or only a
    minimal 3-sided patch is left). Operates on vertex-index sides, as
    returned by split_into_sides.
    """
    if tolerance <= 0 or len(index_sides) <= 3:
        return index_sides

    sides = [list(s) for s in index_sides]

    def length(s):
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


def side_lengths(sides, positions):
    """Arc length of each side, useful to decide default span counts."""
    lengths = []
    for side in sides:
        total = 0.0
        for a, b in zip(side, side[1:]):
            total += (positions[b] - positions[a]).length
        lengths.append(total)
    return lengths
