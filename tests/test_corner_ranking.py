"""Run inside Blender: blender --background --python tests/test_corner_ranking.py

Which corners survive, and what a patch ends up being because of it.

Three failures this covers, all of them "the surface came out wrong the moment
I picked it":

- a four-sided face whose boundary also carries a few shallow kinks -- a
  tessellated crease, a step too gentle to be a real corner -- used to come
  back with eight sides and be filled by the N-Side midpoint fan instead of a
  clean Coons grid;
- a face with exactly *one* corner produced one side, which no generator
  accepts, so the face could not be hovered or picked at all;
- and the reductions must not touch a face that genuinely has five or six
  sides, or a gentle chamfer the topology test found on purpose.

Pure boundary geometry -- no mesh, no session -- so each case is a polyline
written out by hand and read back exactly.
"""
import os
import sys
import math
import importlib

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy  # noqa: F401  (imported for parity with the rest of the suite)
import mathutils

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
sides_mod = pr.sides
generators = pr.generators

FAILURES = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


def V(x, y):
    return mathutils.Vector((x, y, 0.0))


def boundary(points):
    """A closed loop in the shape `sides.py` works in: indices plus a position
    table, exactly what a real patch boundary hands over."""
    return list(range(len(points))), {i: p for i, p in enumerate(points)}


def resolved(points, threshold=135.0, neighbours=None, method='ANGLE'):
    loop, positions = boundary(points)
    return sides_mod.resolve_corners(loop, positions, threshold, neighbours, method)


# ---------------------------------------------------------------------------
# A quad with shallow kinks: the reduction's whole reason to exist.
# ---------------------------------------------------------------------------
# A rectangle whose top edge carries a low, wide bump. Its four vertices bend
# about 31 degrees; the rectangle's own corners bend 90. Read with a threshold
# low enough to flag the bump (165 -> anything bending more than 15 degrees),
# every one of the eight vertices is a "corner".
STEP = [V(0, 0), V(20, 0), V(20, 10), V(12.5, 10), V(11.5, 10.6),
        V(8.5, 10.6), V(7.5, 10), V(0, 10)]

loop, positions = boundary(STEP)
flagged = sides_mod.detect_corners(loop, positions, 165.0)
check("the angle test flags every vertex of the stepped quad",
      len(flagged) == len(STEP), f"{len(flagged)} of {len(STEP)}")

kept = sides_mod.dominant_corners(loop, positions, flagged)
check("ranking cuts it back to the four that shape it", len(kept) == 4, kept)
check("and keeps the rectangle's own corners, not the bump's",
      kept == [0, 1, 2, 7], kept)

generator = generators.find_generator(
    len(sides_mod.split_into_sides(loop, positions, corner_indices=kept)))
check("so the patch is a Quad rather than an N-Side fan",
      generator is not None and generator.name == pr.constants.QUAD,
      generator.name if generator else "none")

# ---------------------------------------------------------------------------
# What must NOT be reduced.
# ---------------------------------------------------------------------------
def regular(n, radius=5.0):
    return [V(radius * math.cos(2 * math.pi * k / n),
              radius * math.sin(2 * math.pi * k / n)) for k in range(n)]


for n in (5, 6, 8):
    loop, positions = boundary(regular(n))
    flagged = sides_mod.detect_corners(loop, positions, 135.0)
    kept = sides_mod.dominant_corners(loop, positions, flagged)
    check(f"a regular {n}-gon keeps all {n} corners", len(kept) == n, kept)

# A rectangle with one chamfered corner: three 90s and two 45s. The 2:1 ratio
# is a cliff, but cutting there would call a four-sided face a triangle, so it
# takes a much clearer one -- see CORNER_CLIFF_TO_TRIANGLE.
CHAMFERED = [V(0, 0), V(20, 0), V(20, 8), V(18, 10), V(0, 10)]
loop, positions = boundary(CHAMFERED)
flagged = sides_mod.detect_corners(loop, positions, 140.0)
check("a chamfered corner is not ranked away",
      len(sides_mod.dominant_corners(loop, positions, flagged)) == len(flagged),
      flagged)

# A rectangle with a semicircular notch: six real corners, two of them much
# sharper than the rest. Sharper is not the same as "the others are noise".
NOTCHED = [V(0, 0), V(6, 0)]
for k in (1, 2):
    a = math.pi * (1 - k / 3)
    NOTCHED.append(V(10 - 4 * math.cos(a), 4 * math.sin(a)))
NOTCHED += [V(14, 0), V(20, 0), V(20, 10), V(0, 10)]
loop, positions = boundary(NOTCHED)
flagged = sides_mod.detect_corners(loop, positions, 135.0)
check("a notched rectangle keeps all six of its corners",
      sides_mod.dominant_corners(loop, positions, flagged) == flagged, flagged)

# A topological junction is a fact, not an inference: a gentle chamfer bends
# far less than the corners beside it and would rank last every time.
GENTLE = [V(0, 0), V(20, 0), V(20, 6), V(19, 8), V(20, 10), V(0, 10)]
loop, positions = boundary(GENTLE)
flagged = sorted(set(sides_mod.detect_corners(loop, positions, 135.0)) | {3})
check("a protected corner survives ranking that would drop it",
      3 in sides_mod.dominant_corners(loop, positions, flagged, protected={3}),
      sides_mod.dominant_corners(loop, positions, flagged, protected={3}))

# ---------------------------------------------------------------------------
# One corner is no better than none.
# ---------------------------------------------------------------------------
# A cardioid: smooth everywhere except a single cusp at its start.
CARDIOID = []
for k in range(40):
    t = 2 * math.pi * k / 40
    r = 4.0 * (1.0 - math.cos(t))
    CARDIOID.append(V(r * math.cos(t), r * math.sin(t)))

loop, positions = boundary(CARDIOID)
check("the cusp is the only corner the angle test finds",
      sides_mod.detect_corners(loop, positions, 135.0) == [0],
      sides_mod.detect_corners(loop, positions, 135.0))

corners = resolved(CARDIOID)
check("a one-corner boundary is topped up to four", len(corners) == 4, corners)
check("and the real corner is one of them", 0 in corners, corners)

split = sides_mod.split_into_sides(loop, positions, corner_indices=corners)
generator = generators.find_generator(len(split))
check("so the face can actually be picked",
      generator is not None and generator.name == pr.constants.QUAD,
      generator.name if generator else "none -- the face is unpickable")

# The top-up is anchored on the real corner, not on an arbitrary origin: a
# cusp in the middle of a side is exactly what the anchoring avoids.
check("every side starts or ends on the cusp or a spread point",
      all(side[0] in [loop[c] for c in corners] for side in split))

# A ring turns the top-up off: it pairs its two loops itself, and corners
# invented on one that don't face the other shear the band.
check("synthesis stays off when the caller says so",
      sides_mod.resolve_corners(loop, positions, 135.0, None, 'ANGLE',
                                allow_synthesis=False) == [0])

# ---------------------------------------------------------------------------
# The case that cannot be decided, and is therefore reported.
# ---------------------------------------------------------------------------
loop, positions = boundary(regular(8))
check("a coarse ring of equal turns is flagged as undecidable",
      sides_mod.corners_are_uniform(
          loop, positions, sides_mod.detect_corners(loop, positions, 135.0)))

loop, positions = boundary(STEP)
check("a boundary with real contrast is not",
      not sides_mod.corners_are_uniform(
          loop, positions, sides_mod.detect_corners(loop, positions, 165.0)))

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
