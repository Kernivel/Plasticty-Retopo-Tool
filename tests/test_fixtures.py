"""Run inside Blender: blender --background --python tests/test_fixtures.py

Retopologize real bridge output and pin what comes out.

Every other test in this suite builds its mesh from the same mental model as
the code, which means none of them can catch "the bridge emits X and we
assumed Y". These fixtures were made in Plasticity and imported through the
bridge, so they are the only place that assumption is actually tested. See
tests/fixtures/README.md for what each shape is for.

Three kinds of assertion, deliberately separated:

- **invariants** -- true of any correct retopology, whatever the tuning
  constants say. A planar face must be reproduced exactly; nothing may come
  out non-manifold. These are the ones worth being strict about.
- **golden values** -- what the pipeline happens to do today. They exist to
  make a change *visible*, not because the numbers are sacred: a tweak to
  CORNER_CLIFF that silently re-routes every bevel is the failure this
  catches. Update them deliberately when a change is intended.
- **known gaps** -- things that are wrong today and recorded as wrong. These
  fail when they start *working*, so that fixing one forces the expectations
  here to be updated rather than leaving a test that quietly asserts a bug.

Deviation figures are a percentage of each object's bounding-box diagonal,
measured across face interiors -- never at vertices, which the generators put
on the surface by construction. The measurement code is imported from
scripts/benchmark.py so the suite and the by-hand tool cannot drift apart.
"""
import os
import sys

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))
sys.path.insert(0, os.path.join(_ADDON_DIR, "scripts"))

import bpy

FIXTURE = os.path.join(_ADDON_DIR, "tests", "fixtures", "TestCases.blend")

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


def known_gap(name, still_broken, extra=""):
    """Record something that is wrong today, and fail when it stops being."""
    if still_broken:
        print(f"[GAP ] {name} -- still open, as recorded {extra}")
        return
    print(f"[FAIL] {name} -- THIS NOW WORKS. Update the expectations in "
          f"tests/test_fixtures.py (and tests/fixtures/README.md).")
    FAILURES.append(f"{name} (fixed -- expectations are stale)")


if not os.path.isfile(FIXTURE):
    print(f"[FAIL] fixture missing: {FIXTURE}")
    sys.exit(1)

# Load the fixture ourselves rather than have run_tests.py pass it on the
# command line: the runner invokes every test the same way, and a test that
# needed special treatment would be a test nobody remembers to run.
bpy.ops.wm.open_mainfile(filepath=FIXTURE)

import importlib

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
import benchmark  # scripts/benchmark.py -- measurement helpers only

try:
    pr.unregister()
except Exception:
    pass
pr.register()


# ===========================================================================
# Golden values, at MID resolution. Regenerate deliberately, never casually:
# a fixture re-exported from Plasticity re-tessellates and moves every one of
# these, at which point a regression is indistinguishable from a re-export.
# ===========================================================================

RESOLUTION = 'MID'

EXPECTED = {
    "Cube Bevel Edges": dict(
        source_tris=108, patches=9, result_verts=32, result_faces=29,
        # Rounded edges: the faces flanking a bevel stay Quad, the corner
        # patches where three bevels meet come out Triangle.
        faces=[
            (49747, "Quad", 4, 1), (49749, "Quad", 4, 1),
            (49750, "Quad", 4, 1), (49762, "Triangle", 3, 1),
            (49764, "Quad", 4, 1), (49767, "Triangle", 3, 1),
            (62046, "Quad", 4, 1), (62069, "Quad", 4, 1),
            (62087, "Quad", 4, 1),
        ],
        max_deviation_pct=4.2,   # chordal sag across the bevels at MID
        open_edges=14,
    ),
    "Cube Chamfer Edges": dict(
        source_tris=20, patches=9, result_verts=18, result_faces=13,
        # Every face is planar, so deviation must be exactly zero. Faces 8834
        # and 8845 are the two pentagons -- see the known gap below.
        faces=[
            (8834, "Quad", 4, 1), (8835, "Quad", 4, 1),
            (8836, "Quad", 4, 1), (8839, "Quad", 4, 1),
            (8843, "Quad", 4, 1), (8845, "N-Side", 5, 1),
            (49495, "Quad", 4, 1), (49519, "Quad", 4, 1),
            (49538, "Quad", 4, 1),
        ],
        max_deviation_pct=0.0,
        open_edges=18,
    ),
    "Cylinder": dict(
        source_tris=204, patches=3, result_verts=725, result_faces=646,
        # The wall is the Ring (two rim loops); the caps are cornerless discs
        # that get four synthesised corners and are filled as Quads.
        faces=[
            (64323, "Quad", 4, 1), (64340, "Quad", 4, 1),
            (64344, "Ring", 2, 2),
        ],
        max_deviation_pct=0.20,
        open_edges=154,
    ),
    "Plate": dict(
        source_tris=398, patches=5, result_verts=447, result_faces=332,
        faces=[
            (65917, "Ring", 2, 2), (65934, "Quad", 4, 1),
            (65938, "Ring", 2, 2), (66608, "Quad", 4, 1),
            (66873, "Ring", 2, 2),
        ],
        max_deviation_pct=0.27,
        open_edges=226,
    ),
    "Shape with holes": dict(
        source_tris=412, patches=17, result_verts=271, result_faces=194,
        # 149331 and 149487 are the top and bottom faces, five boundary loops
        # each. Only the outer one survives -- see the known gap below.
        faces=[
            (149331, "Quad", 4, 5), (149487, "Quad", 4, 5),
            (149557, "Quad", 4, 1), (149561, "Quad", 4, 1),
            (149565, "Quad", 4, 1), (149569, "Quad", 4, 1),
            (149573, "Quad", 4, 1), (149577, "Quad", 4, 1),
            (149581, "Quad", 4, 1), (149585, "Quad", 4, 1),
            (149589, "Quad", 4, 1), (149593, "Ring", 2, 2),
            (149597, "Ring", 2, 2), (149601, "Quad", 4, 1),
            (149603, "Quad", 4, 1), (149605, "Quad", 4, 1),
            (149607, "Quad", 4, 1),
        ],
        max_deviation_pct=11.7,  # dominated by the paved-over holes
        open_edges=150,
    ),
    "Sphere": dict(
        source_tris=4970, patches=1, result_verts=0, result_faces=0,
        faces=[(67324, None, None, 0)],
        max_deviation_pct=None, open_edges=None,
    ),
    "Torus": dict(
        source_tris=5490, patches=1, result_verts=0, result_faces=0,
        faces=[(71055, None, None, 0)],
        max_deviation_pct=None, open_edges=None,
    ),
}

# Faces whose every polygon is coplanar, so the retopology has to reproduce
# them to floating-point exactness at any span. The sharpest assertion here.
PLANAR_OBJECTS = {"Cube Chamfer Edges"}

# What "exactly" can mean against float32 vertex storage. See the check below.
PLANAR_EXACT_PCT = 1e-3


# ===========================================================================
# Run
# ===========================================================================

context = bpy.context
present = {obj.name for obj in bpy.data.objects
           if obj.type == 'MESH' and obj.data.get("face_ids")}
check("the fixture holds every expected object",
      set(EXPECTED) <= present, sorted(set(EXPECTED) - present))

results = {}
for name in sorted(EXPECTED):
    obj = bpy.data.objects.get(name)
    if obj is None:
        continue
    records = benchmark.retopologize(context, obj, RESOLUTION)
    results[name] = records

for name in sorted(EXPECTED):
    expected = EXPECTED[name]
    obj = bpy.data.objects.get(name)
    records = results.get(name)
    if obj is None or records is None:
        continue
    print(f"\n--- {name}")

    check(f"{name}: source triangle count is unchanged",
          len(obj.data.polygons) == expected["source_tris"],
          f"{len(obj.data.polygons)} vs {expected['source_tris']}")
    check(f"{name}: patch count", len(records) == expected["patches"],
          f"{len(records)} vs {expected['patches']}")

    got = sorted((r["face_id"], r["generator"], r["sides"], r["loops"])
                 for r in records)
    want = sorted(expected["faces"])
    if got != want:
        differing = [(g, w) for g, w in zip(got, want) if g != w]
        check(f"{name}: every face resolved as recorded", False,
              f"first differences {differing[:4]}")
    else:
        check(f"{name}: every face resolved as recorded", True,
              f"{len(want)} face(s)")

    result_obj = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
    faces = len(result_obj.data.polygons) if result_obj else 0
    verts = len(result_obj.data.vertices) if result_obj else 0
    check(f"{name}: result mesh size",
          (verts, faces) == (expected["result_verts"], expected["result_faces"]),
          f"{verts}v/{faces}f vs {expected['result_verts']}v/"
          f"{expected['result_faces']}f")

    if not faces:
        continue

    # --- invariants ---------------------------------------------------
    state = context.scene.plasticity_retop
    weld = pr.state.to_blender_units(state, state.boundary_weld_distance)
    topology = benchmark.topology_report(result_obj, weld)
    check(f"{name}: nothing is non-manifold",
          topology["non_manifold"] == 0, topology["non_manifold"])
    check(f"{name}: no coincident vertex pair failed to weld",
          topology["unwelded"] == 0, topology["unwelded"])
    check(f"{name}: no wire edges", topology["wire"] == 0, topology["wire"])

    interior, corners = benchmark.deviation_samples(obj, result_obj)
    scale = benchmark.bbox_diagonal(obj)
    worst = 100.0 * max(interior, default=0.0) / scale
    worst_vertex = 100.0 * max(corners, default=0.0) / scale

    check(f"{name}: every vertex sits on the CAD surface",
          worst_vertex < 1e-3, f"max {worst_vertex:.6f}%")

    if name in PLANAR_OBJECTS:
        # A flat face carries no chordal error at any span, so anything above
        # float noise means the fill is not on the surface it claims.
        #
        # Not literally zero: Blender stores vertices as float32, so a point
        # interpolated across a unit-sized face and then measured against a
        # BVH lands ~1e-6 units off whatever it should be. The measured value
        # is 4.6e-5%; the smallest *real* error in this fixture set is the
        # cylinder's 0.15%, so this threshold sits two orders above the noise
        # and three below anything meaningful.
        check(f"{name}: a planar object is reproduced exactly (to float32)",
              worst < PLANAR_EXACT_PCT, f"max {worst:.9f}% "
              f"vs {PLANAR_EXACT_PCT}%")
    else:
        check(f"{name}: deviation within the recorded ceiling",
              worst <= expected["max_deviation_pct"],
              f"max {worst:.4f}% vs ceiling {expected['max_deviation_pct']}%")

    # --- golden ---------------------------------------------------------
    #
    # Order-dependent and a worst case: this test commits in face_id order,
    # and auto-matching can only match a neighbour that is *already*
    # committed, so a patch baked early can never weld to one baked later.
    # Pinned anyway -- the iteration order is deterministic, so a change here
    # is a real change in behaviour.
    check(f"{name}: open boundary edge count",
          topology["open_edges"] == expected["open_edges"],
          f"{topology['open_edges']} vs {expected['open_edges']}")


# ===========================================================================
# Known gaps. Each fails when it starts working.
# ===========================================================================

print("\n--- known gaps")

for name in ("Sphere", "Torus"):
    records = results.get(name, [])
    unusable = [r for r in records if r["generator"] is None]
    known_gap(
        f"{name}: a closed periodic face cannot be retopologized",
        len(unusable) == len(records) and bool(records),
        "-- one CAD face, no boundary loop at all, so prepare_patch "
        "returns None and the patch is silently unpickable")

holed = [r for r in results.get("Shape with holes", []) if r["loops"] > 2]
known_gap(
    "Shape with holes: faces past two boundary loops are paved over",
    len(holed) == 2,
    f"-- faces {[r['face_id'] for r in holed]} have "
    f"{[r['loops'] for r in holed]} loops; only the outer one is filled, "
    "which is what the 8.98% deviation max measures")

chamfer = {r["face_id"]: r for r in results.get("Cube Chamfer Edges", [])}
pentagons = [chamfer.get(8834), chamfer.get(8845)]
if all(pentagons):
    known_gap(
        "Cube Chamfer: two symmetric pentagons resolve to different generators",
        pentagons[0]["generator"] != pentagons[1]["generator"],
        f"-- face 8834 -> {pentagons[0]['generator']}, "
        f"face 8845 -> {pentagons[1]['generator']}; both are 3 polys with one "
        "5-vertex boundary loop, so dominant_corners is tipping either side "
        "of CORNER_CLIFF on float noise")

pr.operators.end_session(context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
