"""Run inside Blender: blender --background --python tests/test_ring_straightness.py

A band's rungs must run *straight across* it, not at a slight angle.

Every quad of a ring runs from outer[i] to inner[i], so how the two loops are
indexed against each other is the shape of the quads. Both loops are resampled
by arc length from their own arbitrary start, and `align_rings` then searches
whole-index offsets to pair them up -- which can only ever get within half a
step. On an annulus that residue is not noise: it is the *same* small rotation
on every rung, so the whole band comes out visibly sheared. Half a step of 64
points is about 2.8 degrees, which is exactly what "each edge has a slight
angle" looks like on screen.

So this measures the angle between each rung and the local radial direction,
and refuses anything but a fraction of a degree. A concentric annulus is the
right shape to measure it on: there the correct answer is exactly radial, so
any deviation is the generator's and nothing else's.

The other half is what the fix must not cost. A phased rim no longer starts on
the source vertex it was walked from, so its corner id has to be dropped rather
than stamped onto a point that moved -- and a hole that has *real* corners must
not be phased at all, since those are welded to neighbours by identity.
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


def circle(radius, count, phase=0.0, z=0.0):
    """`count` points round a circle, starting at `phase` radians."""
    return [mathutils.Vector((radius * math.cos(phase + 2 * math.pi * i / count),
                              radius * math.sin(phase + 2 * math.pi * i / count),
                              z))
            for i in range(count)]


def closed_side(points):
    """One cornerless side, the way split_into_sides hands a rim over."""
    return [list(points) + [points[0]]]


def rung_deviations(result, around, across):
    """Angle, in degrees, between each rung and the radial direction it should
    lie along. Measured on the outer row, where the rung starts.
    """
    deviations = []
    for i in range(around):
        outer = result.verts[i]
        inner = result.verts[across * around + i]
        rung = inner - outer
        if rung.length < 1e-9:
            continue
        radial = mathutils.Vector((outer.x, outer.y, 0.0))
        if radial.length < 1e-9:
            continue
        # The rung points inward, the radial outward: 180 degrees apart when
        # perfectly straight, so measure against the inward radial.
        cosine = rung.normalized().dot(-radial.normalized())
        deviations.append(math.degrees(math.acos(min(1.0, max(-1.0, cosine)))))
    return deviations


# ---------------------------------------------------------------------------
# The shape from the report: a flat annulus, both rims cornerless.
#
# The two loops are deliberately given different point counts and different
# start angles -- that is what a bridge export looks like, and a start angle
# they happened to share would hide the whole bug.
# ---------------------------------------------------------------------------
OUTER_R, INNER_R = 2.0, 1.6
loops = [
    closed_side(circle(OUTER_R, 96, phase=0.0)),
    closed_side(circle(INNER_R, 71, phase=0.7)),
]

check("the annulus reads as a band", ring.is_band(loops))

generator = ring.RingGenerator()
AROUND, ACROSS = 64, 2
result = generator.generate(loops, {"span_u": AROUND, "span_v": ACROSS})

around = ring.around_count(loops, AROUND)
check("it built the ring at the span asked for", around == AROUND, around)
check("with a full grid of quads",
      len(result.verts) == around * (ACROSS + 1)
      and len(result.faces) == around * ACROSS,
      f"{len(result.verts)}v / {len(result.faces)}f")

deviations = rung_deviations(result, around, ACROSS)
worst = max(deviations)
mean = sum(deviations) / len(deviations)
# A tenth of a degree is far below anything visible, and far below the half a
# step (2.8 degrees at 64 points) the whole-index search leaves behind.
check("every rung runs straight across the band", worst < 0.1,
      f"worst {worst:.4f}deg, mean {mean:.4f}deg")

# The give-away that this was a *shear* and not scatter: the old failure put
# the same angle on every rung. Asserting the spread separately means a fix
# that merely averaged the error out could not pass.
spread = max(deviations) - min(deviations)
check("and they are not merely wrong by the same amount", spread < 0.1,
      f"spread {spread:.4f}deg")

# The start angles differ by 0.7 rad; nothing may depend on them agreeing.
for offset in (0.0, 0.35, 1.9, 3.0):
    shifted = [closed_side(circle(OUTER_R, 96, phase=0.0)),
               closed_side(circle(INNER_R, 71, phase=offset))]
    shifted_result = generator.generate(shifted, {"span_u": AROUND, "span_v": ACROSS})
    shifted_worst = max(rung_deviations(shifted_result, around, ACROSS))
    check(f"straight whatever the hole's start angle ({offset} rad)",
          shifted_worst < 0.1, f"{shifted_worst:.4f}deg")

# A hole wound the other way is the normal case for a face with a hole in it,
# and it must not come out twisted or inside out.
reversed_inner = list(reversed(circle(INNER_R, 71, phase=0.7)))
reversed_loops = [closed_side(circle(OUTER_R, 96)), closed_side(reversed_inner)]
reversed_result = generator.generate(reversed_loops, {"span_u": AROUND, "span_v": ACROSS})
check("a hole wound the other way is straight too",
      max(rung_deviations(reversed_result, around, ACROSS)) < 0.1,
      f"{max(rung_deviations(reversed_result, around, ACROSS)):.4f}deg")

# ---------------------------------------------------------------------------
# What the fix is not allowed to cost
# ---------------------------------------------------------------------------
# A phased rim is sampled from wherever the alignment put it, so index 0 is no
# longer the source vertex the loop was walked from. Its corner id must be
# dropped, not stamped onto a point that moved -- the caller zips the two
# lists, so a short list is how the hole's id gets left out.
check("a phased rim gives up the outer corner only",
      len(result.corner_local_indices) == 1, result.corner_local_indices)
check("and that one is still on the outer row",
      result.corner_local_indices[0] < around, result.corner_local_indices)

# A hole with real corners is a different matter: those are B-rep vertices,
# welded to neighbours by identity, so it must NOT be phased however skewed
# that leaves the band.
inner_points = circle(INNER_R, 72, phase=0.7)
cornered_inner = [inner_points[:19] + [inner_points[18]],
                  inner_points[18:37] + [inner_points[36]],
                  inner_points[36:55] + [inner_points[54]],
                  inner_points[54:] + [inner_points[0]]]
cornered = [closed_side(circle(OUTER_R, 96)), cornered_inner]
cornered_result = generator.generate(cornered, {"span_u": AROUND, "span_v": ACROSS})
check("a hole with corners keeps every one of them",
      len(cornered_result.corner_local_indices) == 1 + len(cornered_inner),
      cornered_result.corner_local_indices)
check("and they sit on the inner row",
      all(index >= around * ACROSS
          for index in cornered_result.corner_local_indices[1:]),
      cornered_result.corner_local_indices)

# ---------------------------------------------------------------------------
# The pieces, so a failure above says which one moved
# ---------------------------------------------------------------------------
square = [mathutils.Vector((0, 0, 0)), mathutils.Vector((2, 0, 0)),
          mathutils.Vector((2, 2, 0)), mathutils.Vector((0, 2, 0))]
check("arc-length round a closed polyline",
      abs(ring.closest_arclength(square, mathutils.Vector((2, 1, 0))) - 3.0) < 1e-6,
      ring.closest_arclength(square, mathutils.Vector((2, 1, 0))))
check("and it clamps to the ends of a segment",
      abs(ring.closest_arclength(square, mathutils.Vector((3, -1, 0))) - 2.0) < 1e-6,
      ring.closest_arclength(square, mathutils.Vector((3, -1, 0))))

rotated = ring.rotate_closed(square, 3.0)
check("rotating a closed polyline starts it where asked",
      (rotated[0] - mathutils.Vector((2, 1, 0))).length < 1e-6, rotated[0])
check("and keeps its length",
      abs(sum(ring._segment_lengths(rotated))
          - sum(ring._segment_lengths(square))) < 1e-6)
check("rotating by nothing changes nothing",
      all((a - b).length < 1e-9
          for a, b in zip(ring.rotate_closed(square, 0.0), square)))

check("closed_points drops the repeated closing vertex",
      len(ring.closed_points(square + [square[0]])) == 4)
check("and leaves an already-open list alone",
      len(ring.closed_points(square)) == 4)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
