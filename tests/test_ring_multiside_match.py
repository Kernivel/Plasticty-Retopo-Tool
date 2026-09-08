"""Run inside Blender: blender --background --python tests/test_ring_multiside_match.py

Matching one side of a rim that is cut into several.

`test_ring_match.py` covers the common rim: one cornerless side, matched whole.
There the loop's total and the match's count are the same number, so nothing
distinguishes "this loop carries a neighbour's vertices" from "this *side*
does" -- which is why the difference went unnoticed until a rim arrived cut
into several sides, by isoparms or by a corner the angle test found.

On such a rim only some sides hold the neighbour's points and the rest are
still the CAD tessellation, and the band's allocation used to redistribute the
loop's whole total by *length*: the matched side was handed back a count its
neighbour never asked for, its vertices were resampled off the ones they were
supposed to land on, and the weld it existed to make came apart. That is the
reported "les spans se perdent".

Three things are pinned here, and the second is what makes the first mean
anything:

- a matched side comes out of `generate` vertex for vertex;
- without the per-side counts -- the old behaviour -- it does *not*, so the
  check above is measuring the fix rather than an accident of the geometry;
- the unmatched sides keep their own counts, and both rims still come out with
  exactly the same number of points, which is the band's hard invariant.
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


def on_circle(angle, radius=1.0, z=0.0):
    return mathutils.Vector((radius * math.cos(angle), radius * math.sin(angle), z))


def arc(start, end, count, radius=1.0, z=0.0):
    """`count` segments of a circle, as count+1 points."""
    return [on_circle(start + (end - start) * i / count, radius, z)
            for i in range(count + 1)]


def worst_offset(points, targets):
    """Furthest any of `targets` is from the nearest of `points`."""
    return max(min((p - t).length for p in points) for t in targets)


# ---------------------------------------------------------------------------
# A flat annulus whose outer rim is cut into four sides, one of them matched.
# ---------------------------------------------------------------------------
# The three unmatched sides carry a dense CAD tessellation (24 segments each).
# Side 1 has been handed a committed neighbour's own vertices: 8 segments, and
# deliberately *unevenly* spaced, so that any resample at all moves every
# interior point of it. Even spacing would let a re-allocation to some other
# count land back on top of them by luck, and the test would pass without the
# fix.
QUARTER = math.pi / 2
DENSE = 24
MATCHED_SEGMENTS = 8

# An uneven walk across the second quarter: the parameter is squared, so the
# points bunch towards the start the way a neighbour committed as an n-gon
# puts its points where the boundary curves.
matched_side = [on_circle(QUARTER + QUARTER * (i / MATCHED_SEGMENTS) ** 2)
                for i in range(MATCHED_SEGMENTS + 1)]

outer_sides = [
    arc(0.0, QUARTER, DENSE),
    matched_side,
    arc(2 * QUARTER, 3 * QUARTER, DENSE),
    arc(3 * QUARTER, 4 * QUARTER, DENSE),
]
# One cornerless inner rim, wound the opposite way like a real hole.
inner_rim = [on_circle(-2 * math.pi * i / 96, radius=0.5) for i in range(96)]
inner_sides = [inner_rim + [inner_rim[0]]]

ACROSS = 2
AROUND = DENSE * 3 + MATCHED_SEGMENTS   # 80

generator = ring.RingGenerator()
loops = [outer_sides, inner_sides]

settings = {"span_u": AROUND, "span_v": ACROSS, "locked_loops": [0],
            "matched_sides": {0: {1: MATCHED_SEGMENTS}}}
result = generator.generate(loops, settings)

n = ring.loop_point_count(outer_sides, {1: MATCHED_SEGMENTS})
check("the loop's total counts the match per side, not the CAD tessellation",
      n == AROUND, f"{n} vs {AROUND}")

check("the band is built at that total",
      len(result.verts) == n * (ACROSS + 1),
      f"{len(result.verts)} vs {n * (ACROSS + 1)}")

outer_row = result.verts[:n]
check("the matched side's vertices come out exactly",
      worst_offset(outer_row, matched_side) < 1e-9,
      f"{worst_offset(outer_row, matched_side):.3e}")

# --- and the same thing without the per-side counts, or nothing is proven ----
#
# This is the code as it stood: the loop was locked, so its total was right,
# but the allocation shared that total out by length and side 1 -- a quarter of
# the circle -- was handed a quarter of the points instead of its neighbour's
# eight.
was = generator.generate(
    loops, {"span_u": AROUND, "span_v": ACROSS, "locked_loops": [0]})
old_offset = worst_offset(was.verts[:n], matched_side)
check("without them the match really was thrown away",
      old_offset > 1e-3, f"{old_offset:.4f}")

# --- the unmatched sides are untouched, and the rims still agree -------------
_points, corners, alloc = ring.ring_from_sides(
    outer_sides, AROUND, {1: MATCHED_SEGMENTS})
check("the matched side gets exactly its own count",
      alloc[1] == MATCHED_SEGMENTS, alloc)
check("the unmatched sides keep theirs",
      [alloc[i] for i in (0, 2, 3)] == [DENSE, DENSE, DENSE], alloc)
check("and the loop still totals what the band asked for",
      sum(alloc) == AROUND, sum(alloc))

# Both rims must come out with the same point count or the rungs cannot pair.
rows = [result.verts[r * n:(r + 1) * n] for r in range(ACROSS + 1)]
check("every row of the band has the same width",
      all(len(row) == n for row in rows), [len(row) for row in rows])

# ---------------------------------------------------------------------------
# Two matched sides on one rim
# ---------------------------------------------------------------------------
# The reason the allocation takes a whole map rather than one side: a rim
# running against two finished patches has two of its sides carrying vertices,
# and honouring one while resampling the other is the same crack, half-fixed.
second = [on_circle(2 * QUARTER + QUARTER * (i / 6) ** 1.5) for i in range(7)]
two_sides = list(outer_sides)
two_sides[2] = second
two_around = ring.loop_point_count(two_sides, {1: MATCHED_SEGMENTS, 2: 6})
two = generator.generate(
    [two_sides, inner_sides],
    {"span_u": two_around, "span_v": ACROSS, "locked_loops": [0],
     "matched_sides": {0: {1: MATCHED_SEGMENTS, 2: 6}}})
row = two.verts[:two_around]
check("two matched sides on one rim both come out exactly",
      worst_offset(row, matched_side) < 1e-9
      and worst_offset(row, second) < 1e-9,
      f"{worst_offset(row, matched_side):.3e} / {worst_offset(row, second):.3e}")

# ---------------------------------------------------------------------------
# A pin set that cannot fit is dropped whole
# ---------------------------------------------------------------------------
# Keeping part of it would hand some of the loop a neighbour's vertices and
# resample the rest to a number nobody asked for -- the half-welded crack the
# allocation exists to prevent -- and the loop's total is not negotiable, since
# both rims of a band must come out with the same count.
cramped = ring.allocate_segments([1.0, 1.0, 1.0], 6, {0: 20})
check("an impossible pin is dropped rather than half-honoured",
      sum(cramped) == 6 and 20 not in cramped, cramped)

# A rim of one side is the case that already worked, and must keep working:
# there the pin and the loop total are the same number.
single = ring.allocate_segments([4.0], 31, {0: 31})
check("a single-side rim is unaffected", single == [31], single)


print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
