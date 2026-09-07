"""Run inside Blender: blender --background --python tests/test_partial_match.py

A neighbour that covers only part of a side.

The case from the report: a bore's rim -- one long cornerless loop -- bordered
by a single small committed patch that touches a fraction of it. Matching used
to refuse outright ("neighbour only covers part of this loop"), because a
partial cover cannot be matched by *count*: the count lands between the
neighbour's vertices everywhere except by luck, which is the half-cell offset
the coverage rule exists to prevent.

Reproducing the neighbour's own vertices where it reaches, and filling the rest
at its spacing, has no offset to leave -- the shared arc is exact and the
remainder borders nothing. This pins that, and pins the two things that make it
safe: the fill lands on the side's own polyline (not on a chord across it), and
an open side keeps its corners, which are welded by identity.
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


try:
    pr.unregister()
except Exception:
    pass
pr.register()

V = mathutils.Vector

# ===========================================================================
# A closed side: a circle, with a neighbour along one eighth of it
# ===========================================================================
# The side as the CAD drew it -- 64 segments round a unit circle, closed the
# way `resolve_side_points` closes a cornerless loop (loop + [loop[0]]).
STEPS = 64
circle = [V((math.cos(2 * math.pi * i / STEPS), math.sin(2 * math.pi * i / STEPS), 0.0))
          for i in range(STEPS)]
circle.append(circle[0].copy())

# The neighbour: five vertices at its own spacing, over an eighth of the rim,
# and *not* at the CAD tessellation's phase -- a committed patch puts its
# points where its own generator put them.
NEIGHBOUR = 5
arc = [V((math.cos(0.31 + 0.11 * i), math.sin(0.31 + 0.11 * i), 0.0))
       for i in range(NEIGHBOUR)]

tolerance = 0.02
strict, reason = pr.mesh_build.match_side_to_points(arc, circle, tolerance,
                                                   merge=tolerance)
check("a neighbour covering an eighth of a rim is refused without partial",
      strict is None, f"{strict and len(strict)} / {reason}")
check("and says why, so the refusal is actionable",
      "part of this loop" in reason, reason)

matched, reason = pr.mesh_build.match_side_to_points(arc, circle, tolerance,
                                                     merge=tolerance,
                                                     partial=True)
check("with partial it matches", matched is not None, reason)

if matched is not None:
    check("the result closes on itself, like any cornerless side",
          (matched[0] - matched[-1]).length < 1e-9,
          (matched[0] - matched[-1]).length)

    # Every one of the neighbour's vertices has to be *in* the result, at the
    # position the neighbour put it. That is the whole point: a count would
    # have given the same number of vertices in the wrong places.
    kept = 0
    for point in arc:
        if any((point - other).length < 1e-9 for other in matched):
            kept += 1
    check("every vertex of the neighbour is reproduced exactly",
          kept == NEIGHBOUR, f"{kept} of {NEIGHBOUR}")

    # The fill has to sit on the rim, not on a chord across it: the rim is a
    # circle of radius 1, so anything off it shows up immediately.
    worst = max(abs(point.length - 1.0) for point in matched)
    check("and the filled points sit on the side's own curve",
          worst < 0.01, worst)

    # Spacing: the fill carries the neighbour's own, so the steps stay even
    # all the way round rather than jumping where the match ends.
    steps = [(b - a).length for a, b in zip(matched, matched[1:])]
    check("the fill carries the neighbour's spacing round the rest",
          max(steps) < 2.0 * min(steps), f"{min(steps):.4f}..{max(steps):.4f}")
    # ...and the count is the rim's, not the neighbour's: 5 vertices over an
    # eighth is about 40 round the whole thing.
    check("so the side comes back with a whole rim's worth of segments",
          25 <= len(matched) - 1 <= 80, len(matched) - 1)

# ===========================================================================
# An open side: the corners are not the match's to move
# ===========================================================================
line = [V((x / 10.0, 0.0, 0.0)) for x in range(11)]     # 0 .. 1, 10 segments
middle = [V((0.42, 0.0, 0.0)), V((0.52, 0.0, 0.0)), V((0.62, 0.0, 0.0))]

strict, reason = pr.mesh_build.match_side_to_points(middle, line, tolerance,
                                                    merge=tolerance)
check("a neighbour in the middle of an open side is refused without partial",
      strict is None, f"{strict and len(strict)} / {reason}")

matched, reason = pr.mesh_build.match_side_to_points(middle, line, tolerance,
                                                     merge=tolerance,
                                                     partial=True)
check("with partial it matches", matched is not None, reason)
if matched is not None:
    check("the side's own start is kept exactly -- it is a corner, welded by "
          "identity", (matched[0] - line[0]).length < 1e-9, matched[0])
    check("and so is its end", (matched[-1] - line[-1]).length < 1e-9, matched[-1])
    kept = sum(1 for point in middle
               if any((point - other).length < 1e-9 for other in matched))
    check("the neighbour's vertices are reproduced exactly", kept == 3, kept)
    check("the points run along the side in order",
          all(a.x < b.x + 1e-9 for a, b in zip(matched, matched[1:])),
          [round(p.x, 3) for p in matched])
    steps = [(b - a).length for a, b in zip(matched, matched[1:])]
    check("at the neighbour's spacing throughout",
          max(steps) < 2.0 * min(steps), f"{min(steps):.4f}..{max(steps):.4f}")

# A fully covered side is untouched by any of this: the strict answer and the
# partial one have to agree wherever the strict one exists, or turning partial
# on would quietly re-space every side that already matched.
full = [V((x / 5.0, 0.0, 0.0)) for x in range(6)]
strict, _reason = pr.mesh_build.match_side_to_points(full, line, tolerance,
                                                     merge=tolerance)
loose, _reason = pr.mesh_build.match_side_to_points(full, line, tolerance,
                                                    merge=tolerance, partial=True)
check("a fully covered side matches the same way with partial on or off",
      strict is not None and loose is not None and len(strict) == len(loose),
      f"{strict and len(strict)} vs {loose and len(loose)}")

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
