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
  catches. Regenerate with scripts/gen_expectations.py and read the diff;
  never hand-edit. Note that the vertex and face counts are **order
  sensitive** -- this test commits in the fixture's own face order, and span
  propagation seeds everything downstream from whichever patch commits first,
  so the same shapes in a different order legitimately produce a different
  count. Generator and side count per face are the entries that should hold
  steady.
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
# Golden values, at MID resolution.
#
# Regenerate with scripts/gen_expectations.py, never by hand. The face ids are
# Plasticity's own, and a re-export renumbers every one of them even when the
# geometry is untouched -- which is exactly what happened when the placement
# variants were added, and is why a stale table makes "the fixture changed"
# indistinguishable from "the code regressed".
# ===========================================================================

RESOLUTION = 'MID'

EXPECTED = {
    "Carved Rounded Slot": dict(
        source_tris=156, patches=11,
        result_verts=172, result_faces=131,
        faces=[
            (69564, "Quad", 4, 1),
            (69565, "Quad", 4, 1),
            (69566, "Quad", 4, 1),
            (69569, "Ring", 5, 2),
            (69570, "Quad", 4, 1),
            (69575, "Quad", 4, 1),
            (69577, "Quad", 4, 1),
            (69579, "Quad", 4, 1),
            (69581, "Quad", 4, 1),
            (69583, "Quad", 4, 1),
            (69604, "Quad", 4, 1),
        ],
        max_deviation_pct=0.09,  # measured 0.0690%
        open_edges=90,
    ),
    "Cone": dict(
        source_tris=188, patches=2,
        result_verts=682, result_faces=612,
        faces=[
            (69229, "Quad", 4, 1),
            (69234, "Quad", 4, 1),
        ],
        max_deviation_pct=19.0,  # measured 13.8728%
        open_edges=140,
    ),
    "Cube Bevel Edges": dict(
        source_tris=168, patches=9,
        result_verts=762, result_faces=721,
        faces=[
            (68052, "Quad", 4, 1),
            (68053, "Quad", 4, 1),
            (68056, "Quad", 4, 1),
            (68057, "Quad", 4, 1),
            (68061, "Triangle", 3, 1),
            (68063, "Quad", 4, 1),
            (68065, "Quad", 4, 1),
            (68067, "Triangle", 3, 1),
            (68068, "Quad", 4, 1),
        ],
        max_deviation_pct=0.38,  # measured 0.2910%
        open_edges=105,
    ),
    "Cube Chamfer Edges": dict(
        source_tris=20, patches=9,
        result_verts=44, result_faces=36,
        faces=[
            (67894, "Quad", 4, 1),
            (67895, "Quad", 4, 1),
            (67896, "Quad", 4, 1),
            (67898, "Quad", 4, 1),
            (67899, "Quad", 4, 1),
            (67905, "Quad", 4, 1),
            (67911, "Quad", 4, 1),
            (67913, "Quad", 4, 1),
            (67916, "N-Side", 5, 1),
        ],
        max_deviation_pct=9.6e-05,  # measured 0.0001%
        open_edges=32,
    ),
    "Cylinder": dict(
        source_tris=320, patches=3,
        result_verts=1592, result_faces=1590,
        faces=[
            (68087, "Quad", 4, 1),
            (68088, "Quad", 4, 1),
            (68091, "Ring", 2, 2),
        ],
        max_deviation_pct=0.079,  # measured 0.0602%
        open_edges=0,
    ),
    "Flat Loop": dict(
        source_tris=622, patches=4,
        result_verts=352, result_faces=236,
        faces=[
            (73730, "Ring", 2, 2),
            (73747, "Ring", 2, 2),
            (73751, "Ring", 2, 2),
            (76294, "Ring", 2, 2),
        ],
        max_deviation_pct=0.096,  # measured 0.0737%
        open_edges=232,
    ),
    "Loopsided Chamfers Cube": dict(
        source_tris=28, patches=14,
        result_verts=34, result_faces=32,
        faces=[
            (69174, "Quad", 4, 1),
            (69175, "Quad", 4, 1),
            (69181, "Quad", 4, 1),
            (69184, "Quad", 4, 1),
            (69187, "Quad", 4, 1),
            (69190, "Quad", 4, 1),
            (69193, "Quad", 4, 1),
            (69196, "Quad", 4, 1),
            (69199, "Quad", 4, 1),
            (69200, "Quad", 4, 1),
            (69203, "Quad", 4, 1),
            (69204, "Quad", 4, 1),
            (69208, "Quad", 4, 1),
            (69210, "Quad", 4, 1),
        ],
        max_deviation_pct=0.00018,  # measured 0.0001%
        open_edges=0,
    ),
    "Plate": dict(
        source_tris=622, patches=5,
        result_verts=775, result_faces=657,
        faces=[
            (68118, "Quad", 4, 1),
            (68119, "Ring", 2, 2),
            (68122, "Ring", 2, 2),
            (68123, "Quad", 4, 1),
            (68127, "Ring", 2, 2),
        ],
        max_deviation_pct=0.11,  # measured 0.0770%
        open_edges=232,
    ),
    "Plate And Cylinder": dict(
        source_tris=2803, patches=14,
        result_verts=2229, result_faces=2139,
        faces=[
            (69329, "Ring", 2, 2),
            (69330, "Quad", 4, 1),
            (69333, "Quad", 4, 1),
            (69334, "Quad", 4, 1),
            (69339, "Ring", 5, 2),
            (69340, "Quad", 4, 1),
            (69341, "Quad", 4, 1),
            (69371, "Ring", 8, 2),
            (69372, "Quad", 4, 1),
            (69373, "Quad", 4, 1),
            (69379, "Quad", 4, 1),
            (69381, "Quad", 4, 1),
            (69385, "Quad", 4, 1),
            (69432, "Ring", 2, 2),
        ],
        max_deviation_pct=0.19,  # measured 0.1399%
        open_edges=184,
    ),
    "Shape with holes": dict(
        source_tris=616, patches=17,
        result_verts=569, result_faces=454,
        faces=[
            (68373, "Quad", 4, 5),
            (68374, "Quad", 4, 5),
            (68377, "Quad", 4, 1),
            (68378, "Quad", 4, 1),
            (68382, "Quad", 4, 1),
            (68384, "Quad", 4, 1),
            (68386, "Quad", 4, 1),
            (68388, "Quad", 4, 1),
            (68390, "Ring", 2, 2),
            (68392, "Ring", 2, 2),
            (68394, "Quad", 4, 1),
            (68396, "Quad", 4, 1),
            (68398, "Quad", 4, 1),
            (68399, "Quad", 4, 1),
            (68400, "Quad", 4, 1),
            (68404, "Quad", 4, 1),
            (68406, "Quad", 4, 1),
        ],
        max_deviation_pct=12.0,  # measured 8.9746%
        open_edges=226,
    ),
    "Sphere": dict(
        source_tris=12320, patches=1,
        result_verts=0, result_faces=0,
        faces=[
            (68149, None, None, 0),
        ],
        max_deviation_pct=None,
        open_edges=None,
    ),
    "Square Plate Small Hole": dict(
        source_tris=28, patches=11,
        result_verts=16, result_faces=14,
        faces=[
            (68590, "Quad", 4, 1),
            (68591, "Quad", 4, 1),
            (68592, "Quad", 4, 1),
            (68595, "Quad", 4, 1),
            (68596, "Quad", 4, 1),
            (68601, "Quad", 4, 1),
            (68603, "Quad", 4, 1),
            (68605, "Quad", 4, 1),
            (68607, "Quad", 4, 1),
            (68609, "Quad", 4, 1),
            (68611, "Ring", 8, 2),
        ],
        max_deviation_pct=9.4e-05,  # measured 0.0001%
        open_edges=0,
    ),
    "Square Plate Small Hole Far Away": dict(
        source_tris=28, patches=11,
        result_verts=16, result_faces=14,
        faces=[
            (68944, "Quad", 4, 1),
            (68945, "Quad", 4, 1),
            (68946, "Quad", 4, 1),
            (68949, "Quad", 4, 1),
            (68950, "Quad", 4, 1),
            (68955, "Quad", 4, 1),
            (68957, "Quad", 4, 1),
            (68959, "Quad", 4, 1),
            (68961, "Quad", 4, 1),
            (68963, "Quad", 4, 1),
            (68965, "Ring", 8, 2),
        ],
        max_deviation_pct=0.00088,  # measured 0.0007%
        open_edges=0,
    ),
    "Square Plate Small Hole Scaled Down": dict(
        source_tris=28, patches=11,
        result_verts=12, result_faces=10,
        faces=[
            (68767, "Quad", 4, 1),
            (68768, "Quad", 4, 1),
            (68769, "Quad", 4, 1),
            (68772, "Quad", 4, 1),
            (68773, "Quad", 4, 1),
            (68778, "Quad", 4, 1),
            (68780, "Quad", 4, 1),
            (68782, "Quad", 4, 1),
            (68784, "Quad", 4, 1),
            (68786, "Quad", 4, 1),
            (68788, "Ring", 8, 2),
        ],
        max_deviation_pct=0.086,  # measured 0.0661%
        open_edges=0,
    ),
    "Torus": dict(
        source_tris=27126, patches=1,
        result_verts=0, result_faces=0,
        faces=[
            (68161, None, None, 0),
        ],
        max_deviation_pct=None,
        open_edges=None,
    ),
}

# Faces whose every polygon is coplanar, so the retopology has to reproduce
# them to floating-point exactness at any span. The sharpest assertion here.
#
# "Square Plate Small Hole Far Away" is deliberately *not* in this set even
# though it is the same flat shape as the one at the origin: at coordinates
# around 100 its float32 noise measures ~7x what the same part shows at the
# origin (0.0007% against 0.0001%), which is the entire point of having it. It
# gets a recorded ceiling instead, and the placement gap below carries the
# rest of the story.
PLANAR_OBJECTS = {
    "Cube Chamfer Edges",
    "Loopsided Chamfers Cube",
    "Square Plate Small Hole",
}

# What "exactly" can mean against float32 vertex storage. See the check below.
PLANAR_EXACT_PCT = 1e-3

# One CAD shape, three placements: at the origin, out at (50, 100, 20), and
# scaled to a hundredth. See the known gap at the bottom.
PLACEMENT_VARIANTS = (
    "Square Plate Small Hole",
    "Square Plate Small Hole Far Away",
    "Square Plate Small Hole Scaled Down",
)


# ===========================================================================
# Run
# ===========================================================================

context = bpy.context
present = {obj.name for obj in bpy.data.objects
           if obj.type == 'MESH' and obj.data.get("face_ids")}
check("the fixture holds every expected object",
      set(EXPECTED) <= present, sorted(set(EXPECTED) - present))
# The other direction matters just as much: a shape added to the .blend
# that nobody wrote an expectation for is a shape nothing is testing.
check("and the test knows about every object in the fixture",
      present <= set(EXPECTED), sorted(present - set(EXPECTED)))

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

    # Loose enough to cover the far-from-origin variant, whose float32
    # noise at coordinate ~100 is several times what the same shape shows
    # at the origin. Still four orders below any real chordal error.
    check(f"{name}: every vertex sits on the CAD surface",
          worst_vertex < 1e-2, f"max {worst_vertex:.6f}%")

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

# The pentagons of the chamfered cube, found by *shape* rather than by id: a
# re-export renumbers every face id but does not move a vertex, so anything
# keyed to an id here would silently stop testing what it names.
chamfer_obj = bpy.data.objects.get("Cube Chamfer Edges")
if chamfer_obj is not None:
    analysis = pr.patch_data.analyse(chamfer_obj.data)
    by_id = {r["face_id"]: r for r in results.get("Cube Chamfer Edges", [])}
    pentagons = sorted(
        face_id for face_id, patch in analysis.patches.items()
        if len(patch.boundary_loops) == 1 and len(patch.boundary_loops[0]) == 5)
    generators = [by_id[f]["generator"] for f in pentagons if f in by_id]
    known_gap(
        "Cube Chamfer: symmetric pentagons resolve to different generators",
        len(generators) >= 2 and len(set(generators)) > 1,
        f"-- faces {pentagons} -> {generators}; each is a single 5-vertex "
        "boundary loop, so dominant_corners is tipping either side of "
        "CORNER_CLIFF on float noise")

# The headline finding from the three placement variants.
sizes = {name: (EXPECTED[name]["result_verts"], EXPECTED[name]["result_faces"])
         for name in PLACEMENT_VARIANTS if name in EXPECTED}
known_gap(
    "One shape at three placements gives three different retopologies",
    len(set(sizes.values())) > 1,
    f"-- {sizes}. Same CAD shape, and the generators and side counts do agree "
    "across all three; it is the density that moves. Neither absolute "
    "tolerance is scaled to the part: boundary_weld_distance defaults to 1e-4 "
    "in metres, and patch_data's weld epsilon is a hard-coded 1e-5, so a part "
    "at coordinate ~100 and a part 0.01 across are measured with the same "
    "yardstick as one of unit size. Scaling the weld distance to the part "
    "recovers some of it but not all, so there is a second cause still open")

# A plate whose hole is small is not a band, but its faces come back as Rings
# anyway -- the case CLAUDE.md calls the disaster: every quad stretched from
# the outline to the hole.
rings = [r for r in results.get("Square Plate Small Hole", [])
         if r["generator"] == "Ring"]
known_gap(
    "Square Plate Small Hole: a small hole is still filled as a band",
    bool(rings),
    f"-- face(s) {[r['face_id'] for r in rings]} came back Ring, which the "
    "benchmark reports as an aspect ratio around 400x")

# A cone's lateral face runs to a point. The apex is a singularity no quad
# grid represents, and the deviation says so.
cone = EXPECTED.get("Cone")
known_gap(
    "Cone: the apex is approximated badly",
    bool(cone) and cone["max_deviation_pct"] > 5.0,
    f"-- deviation ceiling {cone['max_deviation_pct'] if cone else '?'}%, "
    "against 0.2% for the cylinder beside it; the lateral face is a "
    "cornerless loop closing on a point, filled as a Quad")

pr.operators.end_session(context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
