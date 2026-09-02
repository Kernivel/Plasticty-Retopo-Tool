"""Run inside Blender: blender --background --python tests/test_ring_match.py

A band has to *use* the retopology already committed against its rims.

Matching hands a side the neighbour's own committed vertices, and every other
generator reproduces them because `resample_polyline_by_arclength` returns the
points it was given when the count already matches. A ring did not, for two
reasons that both look like "the addon ignores what is already there":

- it always led with `loops[0]` and phase-*resampled* the other rim onto it, so
  a match landing on that other rim was thrown away and the two rings came back
  half a step apart. Which rim is which is decided by extent
  (`patch_data.sort_loops_outer_first`), and on a tube the two rims have the
  same extent -- so the same match worked or didn't for no reason visible on
  screen. That is the "inconsistent" half of the report.
- both rims drove one span key, so the second was dropped as a collision even
  when it wanted the very same count. A ring's rungs run outer[i] -> inner[i],
  so the two rims are not in competition the way a quad's opposite sides are:
  they can both be reproduced as long as they agree, and `_honours` is what
  checks that they do.

Measured on the generator, where the answer is exact: a locked rim's points
have to come out of `generate` unchanged, whichever loop it is.
"""
import os
import sys
import importlib
import math

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy
import mathutils

pr = importlib.import_module(os.path.basename(_ADDON_DIR))

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


ring = pr.generators.ring
sidematch = pr.sidematch
constants = pr.constants


def circle(radius, count, phase=0.0, z=0.0):
    return [mathutils.Vector((radius * math.cos(phase + 2 * math.pi * i / count),
                              radius * math.sin(phase + 2 * math.pi * i / count),
                              z))
            for i in range(count)]


def closed_side(points):
    """One cornerless side, the way `resolve_side_points` hands a rim over."""
    return [list(points) + [points[0]]]


def worst_offset(points, targets):
    """Furthest any of `targets` is from the nearest of `points`."""
    return max(min((p - t).length for p in points) for t in targets)


# ---------------------------------------------------------------------------
# A tube: two cornerless rims, one of them carrying a neighbour's vertices.
#
# The committed rim is deliberately given a phase no arc-length resample would
# land on (0.31 rad, 24 points against the CAD rim's 96) -- if the generator
# resamples it at all, every point moves and the check below fails by half a
# step, which is exactly the crack in the report.
# ---------------------------------------------------------------------------
AROUND, ACROSS = 24, 3
committed = circle(1.0, AROUND, phase=0.31, z=1.0)
free_rim = circle(1.0, 96, phase=0.0, z=0.0)

generator = ring.RingGenerator()

for locked_index in (0, 1):
    loops = [closed_side(free_rim), closed_side(free_rim)]
    loops[locked_index] = closed_side(committed)
    result = generator.generate(
        loops,
        {"span_u": AROUND, "span_v": ACROSS, "locked_loops": [locked_index]})

    n = ring.around_count(loops, AROUND)
    check(f"loop {locked_index} locked: the band is built at the match's count",
          n == AROUND, n)

    row = (result.verts[:n] if locked_index == 0
           else result.verts[ACROSS * n:ACROSS * n + n])
    check(f"loop {locked_index} locked: its row is the committed vertices, exactly",
          worst_offset(row, committed) < 1e-9, worst_offset(row, committed))

    # And the free rim is still phased onto it, or the fix would have traded
    # one visible failure for another: the rungs must run straight across.
    other = (result.verts[ACROSS * n:ACROSS * n + n] if locked_index == 0
             else result.verts[:n])
    # On a tube "straight across" means axial: the two ends of a rung sit at
    # the same angle round the axis. Measured that way rather than as a
    # direction, because the rung itself is almost pure z and its tiny radial
    # component says nothing.
    worst = 0.0
    for i in range(n):
        delta = math.atan2(other[i].y, other[i].x) - math.atan2(row[i].y, row[i].x)
        delta = (delta + math.pi) % (2 * math.pi) - math.pi
        worst = max(worst, abs(math.degrees(delta)))
    check(f"loop {locked_index} locked: the rungs still run straight across",
          worst < 0.5, f"{worst:.4f}deg")

# A locked rim is not the source vertex its loop started at either, so it gives
# up its corner id the same way a phased one does -- but in place, not by
# shortening the list. The outer id would otherwise be stamped onto the hole.
loops = [closed_side(free_rim), closed_side(committed)]
result = generator.generate(loops, {"span_u": AROUND, "span_v": ACROSS,
                                    "locked_loops": [1]})
check("a phased outer rim still reports one corner slot per loop",
      len(result.corner_local_indices) == 2, result.corner_local_indices)
check("and the phased one is NO_CORNER, not a vertex that moved",
      result.corner_local_indices[0] == ring.NO_CORNER,
      result.corner_local_indices)

# Nothing locked is the old path, unchanged.
plain = generator.generate([closed_side(free_rim), closed_side(committed)],
                           {"span_u": AROUND, "span_v": ACROSS})
check("with nothing locked the band is still built",
      len(plain.verts) == AROUND * (ACROSS + 1), len(plain.verts))

# ---------------------------------------------------------------------------
# The span keys: a ring's two rims must not knock each other out
# ---------------------------------------------------------------------------
def reference(index, loop):
    return sidematch.SideReference(
        index=index, loop=loop, in_loop=0, points=[], match_points=None,
        neighbours=[])


outer_side = reference(0, 0)
inner_side = reference(1, 1)
check("a ring keys its two rims separately",
      sidematch.span_key_for(constants.RING, outer_side)
      != sidematch.span_key_for(constants.RING, inner_side),
      (sidematch.span_key_for(constants.RING, outer_side),
       sidematch.span_key_for(constants.RING, inner_side)))
check("and both still drive the 'around' span",
      {sidematch.span_base(sidematch.span_key_for(constants.RING, s))
       for s in (outer_side, inner_side)} == {"span_u"})

# A quad's opposite sides genuinely are one span, and must keep colliding.
quad_a = sidematch.SideReference(index=0, loop=0, in_loop=0, points=[],
                                 match_points=None, neighbours=[])
quad_c = sidematch.SideReference(index=2, loop=0, in_loop=2, points=[],
                                 match_points=None, neighbours=[])
check("a quad's opposite sides still share one span",
      sidematch.span_key_for(constants.QUAD, quad_a)
      == sidematch.span_key_for(constants.QUAD, quad_c))
check("span_base leaves an unqualified key alone",
      sidematch.span_base("span_v") == "span_v")

# Two rims wanting different counts still cannot both be honoured: the band has
# one point count. `_honours` is what drops the loser, once the span is
# resolved -- and it has to read the *base* key, or a ring's qualified one
# never matched the resolved spans and every ring match was silently dropped.
points = [mathutils.Vector((float(i), 0.0, 0.0)) for i in range(5)]
check("a ring match is honoured when the span reproduces it",
      sidematch._honours("span_u@1", points, {"span_u": 4}))
check("and dropped when it does not",
      not sidematch._honours("span_u@1", points, {"span_u": 7}))

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
