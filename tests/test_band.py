"""Run inside Blender: blender --background --python tests/test_band.py

Two boundary loops is a topological annulus; it is not necessarily a *band*.

The Ring generator gives both loops the same number of points, because every
quad it makes runs straight from one to the other. On a washer, a tube wall or
a fillet running round a boss that is exactly right. On a 200x100 plate with a
5mm hole it is a disaster: either the hole gets a hundred points or the plate's
outline gets twelve, and every quad is stretched the width of the plate. This
covers the test that separates the two, on boundaries written out by hand.
"""
import os
import sys
import math
import importlib

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy  # noqa: F401
import mathutils

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
ring = pr.generators.ring

FAILURES = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


def V(x, y, z=0.0):
    return mathutils.Vector((x, y, z))


def circle(radius, count=40, cx=0.0, cy=0.0, z=0.0):
    """One closed side, the shape a cornerless loop reaches a generator in."""
    return [[V(cx + radius * math.cos(2 * math.pi * k / count),
              cy + radius * math.sin(2 * math.pi * k / count), z)
             for k in range(count + 1)]]


def rectangle(width, height, count=48, x0=0.0, y0=0.0):
    points = []
    for k in range(count + 1):
        t = 4.0 * k / count
        if t < 1:
            points.append(V(x0 + t * width, y0))
        elif t < 2:
            points.append(V(x0 + width, y0 + (t - 1) * height))
        elif t < 3:
            points.append(V(x0 + width - (t - 2) * width, y0 + height))
        else:
            points.append(V(x0, y0 + height - (t - 3) * height))
    return [points]


# --- genuine bands ---------------------------------------------------------
check("a washer is a band", ring.is_band([circle(10), circle(6)]))
check("a narrow fillet ring is a band", ring.is_band([circle(10), circle(9.2)]))
check("a tube wall is a band -- its two rims sit at different heights",
      ring.is_band([circle(10, z=0.0), circle(10, z=4.0)]))
check("a plate with a slot nearly as big as itself is a band",
      ring.is_band([rectangle(200, 100), rectangle(160, 60, x0=20, y0=20)]))
check("and so is a square plate with a large round hole",
      ring.is_band([rectangle(100, 100), circle(30, 32, cx=50, cy=50)]))

# --- annuli that are not bands --------------------------------------------
check("a long plate with a small hole is not",
      not ring.is_band([rectangle(200, 100), circle(2.5, 20, cx=100, cy=50)]))
check("nor is a square plate with a pinhole",
      not ring.is_band([rectangle(100, 100), circle(1.0, 16, cx=50, cy=50)]))
check("a hole pushed off to one side is not, however big",
      not ring.is_band([rectangle(200, 100), circle(20, 32, cx=30, cy=50)]))

# --- what the test refuses to answer --------------------------------------
check("a single loop is not a band", not ring.is_band([circle(10)]))
check("three loops are not either",
      not ring.is_band([circle(10), circle(6), circle(3)]))

# --- the gap sampling itself ----------------------------------------------
gaps = ring.band_gaps([circle(10), circle(6)])
check("a washer's gap is the same all the way round",
      gaps and max(gaps) - min(gaps) < 0.2, f"{min(gaps):.2f}..{max(gaps):.2f}")

gaps = ring.band_gaps([rectangle(200, 100), circle(20, 32, cx=30, cy=50)])
check("an off-centre hole leaves a gap that varies wildly",
      gaps and max(gaps) > min(gaps) * ring.BAND_GAP_SPREAD,
      f"{min(gaps):.1f}..{max(gaps):.1f}")

# A centred pinhole leaves an *even* gap -- the plate is symmetric -- so the
# gap test alone would call it a band. The perimeter ratio is what catches it:
# a boundary forty times longer than the hole cannot share its point count.
plate, hole = rectangle(200, 100), circle(2.5, 20, cx=100, cy=50)
gaps = ring.band_gaps([plate, hole])
check("a centred pinhole's gap is even enough to pass the gap test",
      gaps and max(gaps) <= min(gaps) * ring.BAND_GAP_SPREAD,
      f"{min(gaps):.1f}..{max(gaps):.1f}")
outer = sum(ring.polyline_length(side) for side in plate)
inner = sum(ring.polyline_length(side) for side in hole)
check("and the perimeter ratio is what refuses it",
      outer > inner * ring.BAND_PERIMETER_RATIO, f"{outer:.0f} vs {inner:.0f}")

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
