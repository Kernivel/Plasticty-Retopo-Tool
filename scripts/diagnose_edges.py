"""Why a patch's boundary in Blender doesn't match the CAD face in Plasticity.

    blender YourFile.blend --background --factory-startup --python scripts/diagnose_edges.py
    blender YourFile.blend --background --factory-startup --python scripts/diagnose_edges.py -- --object Body --face 1234

`--factory-startup` is not optional: without it every installed addon loads,
and one of them has been seen saving the file over itself on quit.

Nothing here writes to the file. It reports the three things that can make a
recovered boundary disagree with the one Plasticity drew:

**The weld missed.** Patch borders are duplicated by the bridge, so a border
half-edge only finds its opposite once the two copies are merged. The epsilon
is 1e-5 *absolute*: on a part whose coordinates run to hundreds of units that
is the same order as the float32 ulp, and the two independently rounded copies
of a shared vertex miss each other. The segment then reports "no face across
me", which reads as a junction -- a phantom B-rep vertex -- and the junction
count is what picks the generator. NEAR MISSES below counts pairs that sit
just outside the epsilon; any at all is this failure.

**The tessellations disagree.** Two faces meeting along a CAD edge normally
share its polyline vertex for vertex. If the mesher put different vertices on
the two sides, no amount of welding pairs them and the whole edge reads as an
open boundary. That shows as UNMATCHED covering a long run rather than
scattered segments.

**The weld reached across a real edge.** The epsilon is capped by the mesh's
own shortest edge for that reason -- welding the two ends of an edge destroys
the triangle carrying it and unbalances the patch's directed boundary, so the
loop walk dies and the fragment is dropped. SHORTEST EDGE below says whether
the cap is biting, i.e. whether this part has features at the epsilon.

**The boundary pinches.** A vertex with two outgoing boundary half-edges -- a
face touching itself at a point -- is walked correctly now, but it is still
worth seeing: it means the face is not a simple disc.

For each suspicious face it prints the junctions, the run lengths between them
and the neighbouring face id per run, so a run of length 1 or 2 -- the tell for
a flickering neighbour -- is visible next to the id it flickered to.
"""
import argparse
import importlib
import math
import os
import sys

import bpy
from mathutils.kdtree import KDTree

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
patch_data = pr.patch_data
sides_mod = pr.sides

EPSILON = 1e-5
# How far past the epsilon a pair still counts as "meant to be the same point",
# reported in bands rather than as one count: a dense tessellation puts
# genuinely distinct vertices a few thousandths apart, so a single generous
# radius reports the mesher's own spacing as evidence. Only the first band --
# pairs sitting just outside the epsilon -- is a weld that missed.
NEAR_BANDS = (10.0, 100.0, 1000.0)
# A run of boundary segments this short between two junctions is not a CAD
# edge, it is a neighbour that flickered -- but only on a loop long enough for
# a run to mean anything. A four-vertex quad borders four faces in four runs
# of one, and that is simply what it is.
SHORT_RUN = 2
MIN_LOOP_FOR_SHORT_RUN = 8


def plasticity_objects(scene):
    for obj in scene.objects:
        if obj.type != 'MESH':
            continue
        if obj.data.get("face_ids") and obj.data.get("groups"):
            yield obj


def coordinate_scale(mesh):
    """The largest coordinate magnitude, and the float32 spacing there."""
    biggest = 0.0
    for v in mesh.vertices:
        biggest = max(biggest, abs(v.co.x), abs(v.co.y), abs(v.co.z))
    if biggest <= 0.0:
        return 0.0, 0.0
    exponent = math.floor(math.log2(biggest))
    return biggest, 2.0 ** (exponent - 23)


def near_misses(mesh, weld_map):
    """Pairs of vertices that are close but were not welded together.

    Only weld candidates take part -- the same set `build_weld_map` considers --
    so an interior vertex sitting near another one is not reported, because it
    was never a candidate for merging in the first place.
    """
    candidates = patch_data.weld_candidates(mesh)
    considered = (list(range(len(mesh.vertices))) if candidates is None
                  else [int(i) for i in candidates])
    if len(considered) < 2:
        return [], len(considered)

    kd = KDTree(len(considered))
    for i in considered:
        kd.insert(mesh.vertices[i].co, i)
    kd.balance()

    found = []
    for i in considered:
        radius = EPSILON * NEAR_BANDS[-1]
        for _co, j, dist in kd.find_range(mesh.vertices[i].co, radius):
            if j <= i or dist <= EPSILON:
                continue
            if weld_map[i] == weld_map[j]:
                continue
            found.append((dist, i, j))
    found.sort()
    return found, len(considered)


def loop_report(loop, neighbours):
    """Junctions of one loop plus the run length and neighbour id after each."""
    junctions = sides_mod.detect_topological_corners(loop, neighbours)
    count = len(loop)
    unmatched = sum(1 for n in neighbours if n is None)
    runs = []
    if junctions:
        for k, start in enumerate(junctions):
            end = junctions[(k + 1) % len(junctions)]
            length = (end - start) % count or count
            runs.append((length, neighbours[start]))
    return junctions, runs, unmatched


def pinched_vertices(mesh, analysis):
    """Boundary vertices where `compute_boundary_loops` had to drop a half-edge."""
    weld_map = analysis.weld_map
    out = []
    for patch in analysis.patches.values():
        present = set()
        for poly_idx in patch.poly_indices:
            verts = [weld_map[vi] for vi in mesh.polygons[poly_idx].vertices]
            n = len(verts)
            for i in range(n):
                a, b = verts[i], verts[(i + 1) % n]
                if a != b:
                    present.add((a, b))
        counts = {}
        for (a, b) in present:
            if (b, a) not in present:
                counts[a] = counts.get(a, 0) + 1
        out.extend(v for v, c in counts.items() if c > 1)
    return sorted(set(out))


def report_object(obj, only_face=None):
    mesh = obj.data
    print("\n=== %s (%d verts, %d polys) ===" % (
        obj.name, len(mesh.vertices), len(mesh.polygons)))

    biggest, ulp = coordinate_scale(mesh)
    print("largest coordinate %.4g  float32 ulp there %.3g  weld epsilon %g"
          % (biggest, ulp, EPSILON))
    if ulp > EPSILON * 0.1:
        print("  ** the epsilon is within an order of magnitude of the ulp: two "
              "copies of a shared vertex can legitimately miss each other")

    shortest = patch_data.shortest_edge(mesh)
    capped = min(EPSILON, shortest * 0.5)
    print("SHORTEST EDGE %.3g -> weld epsilon capped to %.3g%s"
          % (shortest, capped, "" if capped >= EPSILON else "  ** the cap is biting"))

    analysis = patch_data.analyse(mesh)
    collapsed = sum(
        1
        for poly in mesh.polygons
        for i in range(len(poly.vertices))
        if analysis.weld_map[poly.vertices[i]]
        == analysis.weld_map[poly.vertices[(i + 1) % len(poly.vertices)]])
    if collapsed:
        print("  ** %d polygon corners collapsed by the weld -- real edges "
              "destroyed, so some boundary walks will die" % collapsed)

    misses, n_candidates = near_misses(mesh, analysis.weld_map)
    print("weld candidates %d" % n_candidates)
    low = EPSILON
    for factor in NEAR_BANDS:
        high = EPSILON * factor
        band = [m for m in misses if low < m[0] <= high]
        label = "NEAR MISSES" if factor == NEAR_BANDS[0] else "           "
        print("  %s %5d unwelded pairs in (%g, %g]" % (label, len(band), low, high))
        low = high
    tight = [m for m in misses if m[0] <= EPSILON * NEAR_BANDS[0]]
    if tight:
        print("  ** pairs this close are one point the weld failed to merge")
        for dist, i, j in tight[:10]:
            print("     %.3e  v%d v%d  %s"
                  % (dist, i, j, tuple(round(c, 6) for c in mesh.vertices[i].co)))
        if len(tight) > 10:
            print("     ... %d more" % (len(tight) - 10))

    suspicious = 0
    for face_id, patch in sorted(analysis.patches.items()):
        if only_face is not None and face_id != only_face:
            continue
        for k, (loop, neighbours) in enumerate(
                zip(patch.boundary_loops, patch.boundary_neighbours)):
            junctions, runs, unmatched = loop_report(loop, neighbours)
            short = ([r for r in runs if r[0] <= SHORT_RUN]
                     if len(loop) >= MIN_LOOP_FOR_SHORT_RUN else [])
            # One CAD face borders another along one edge, so a neighbour id
            # showing up in two separate runs of the same loop is that border
            # broken into pieces by something that is not a B-rep vertex.
            seen = {}
            for _length, other in runs:
                if other is not None:
                    seen[other] = seen.get(other, 0) + 1
            split = sorted(other for other, n in seen.items() if n > 1)
            if only_face is None and not short and not unmatched and not split:
                continue
            suspicious += 1
            print("\nface %d loop %d: %d verts, %d junctions, %d segments with "
                  "no face across them"
                  % (face_id, k, len(loop), len(junctions), unmatched))
            print("  runs (length, neighbour face id): "
                  + ", ".join("(%d, %s)" % (length, other) for length, other in runs))
            if short:
                print("  ** %d run(s) of <= %d segments -- a neighbour that "
                      "flickered, not a CAD edge" % (len(short), SHORT_RUN))
            if split:
                print("  ** face id(s) %s appear in more than one run -- one "
                      "shared border broken into pieces" % (split,))
            if unmatched:
                print("  ** %d of %d segments unmatched: either a genuine open "
                      "boundary, or the weld missed" % (unmatched, len(loop)))

    pinched = pinched_vertices(mesh, analysis)
    if pinched:
        print("\n** %d boundary vertices carry more than one outgoing half-edge; "
              "the loop walk keeps one: %s" % (len(pinched), pinched[:10]))

    if only_face is None and not suspicious:
        print("\nno face shows a short run or an unmatched segment")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--object", default=None)
    parser.add_argument("--face", type=int, default=None,
                        help="report this face id even if nothing looks wrong")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parser.parse_args(argv)

    targets = [o for o in plasticity_objects(bpy.context.scene)
               if args.object is None or o.name == args.object]
    if not targets:
        print("no Plasticity mesh found"
              + (" named %s" % args.object if args.object else ""))
        return

    for obj in targets:
        report_object(obj, args.face)


main()
