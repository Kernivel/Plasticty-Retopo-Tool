"""Retopologize every patch of a bridge-imported .blend and measure the result.

    blender TestCases.blend --background --python scripts/benchmark.py
    blender TestCases.blend --background --python scripts/benchmark.py -- --resolution HIGH
    blender TestCases.blend --background --python scripts/benchmark.py -- --object Cylinder

Reports four things per object, because they fail in different ways:

- **selection** -- which patches produced a preview at all. A patch no
  generator accepts is silently unpickable in the viewport, so it has to be
  counted here rather than inferred from a low face count.
- **deviation** -- how far the retopology sits off the CAD surface. Sampled
  across each face's *interior*, never at its vertices: interior vertices are
  put on the surface by construction (the generators reproject through a BVH),
  so a vertex-only figure reads ~0 and proves nothing. The real error is the
  chordal sag between them.
- **topology** -- non-manifold edges, open boundary edges, and boundary
  vertices that should have welded and didn't. On a fully retopologized closed
  solid the open-edge count is the single number that says whether span
  propagation and boundary welding actually worked end to end.
- **cell quality** -- aspect ratio, skew and planarity, reported as
  percentiles and worst cases. Means hide the failure mode, which is a handful
  of degenerate cells from a fan.

Deviation is read from the result object's *base* mesh, like commit is: the
result carries a Displace modifier for the cosmetic offset, and evaluating it
would measure a surface nobody commits.
"""
import argparse
import importlib
import math
import os
import sys

import bmesh
import bpy
import mathutils

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

pr = importlib.import_module(os.path.basename(_ADDON_DIR))


# --- small statistics helpers (no numpy dependency) -------------------------

def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def rms(values):
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


def bbox_diagonal(obj):
    corners = [mathutils.Vector(c) for c in obj.bound_box]
    lo = mathutils.Vector((min(c[i] for c in corners) for i in range(3)))
    hi = mathutils.Vector((max(c[i] for c in corners) for i in range(3)))
    return (hi - lo).length or 1.0


# --- deviation --------------------------------------------------------------

def barycentric_samples(order):
    """Interior barycentric weights of a triangle, excluding its corners.

    The corners are where the generators already pinned the surface; what is
    being measured is everything between them.
    """
    weights = []
    for i in range(order + 1):
        for j in range(order + 1 - i):
            k = order - i - j
            if i == order or j == order or k == order:
                continue  # a corner
            weights.append((i / order, j / order, k / order))
    return weights or [(1 / 3, 1 / 3, 1 / 3)]


SAMPLE_WEIGHTS = barycentric_samples(4)


def deviation_samples(source_obj, result_obj):
    """Distance from points across the result's faces to the source surface,
    in source-local units."""
    src_mesh = source_obj.data
    if not src_mesh.polygons or not result_obj.data.polygons:
        return [], []

    bvh, _tri_poly = pr.geometry.build_bvh_with_polygon_map(src_mesh)
    to_source = source_obj.matrix_world.inverted() @ result_obj.matrix_world

    mesh = result_obj.data
    coords = [to_source @ v.co for v in mesh.vertices]

    interior = []
    corners = []
    for poly in mesh.polygons:
        loop = list(poly.vertices)
        for vi in loop:
            hit = bvh.find_nearest(coords[vi])
            if hit and hit[0] is not None:
                corners.append((coords[vi] - hit[0]).length)
        # fan-triangulate, then sample each triangle's interior
        for t in range(1, len(loop) - 1):
            a, b, c = coords[loop[0]], coords[loop[t]], coords[loop[t + 1]]
            for wa, wb, wc in SAMPLE_WEIGHTS:
                point = a * wa + b * wb + c * wc
                hit = bvh.find_nearest(point)
                if hit and hit[0] is not None:
                    interior.append((point - hit[0]).length)
    return interior, corners


def flipped_faces(source_obj, result_obj):
    """How many result faces point the opposite way from the CAD surface.

    A retopology that is inside out is invisible in solid shading and obvious
    the moment anything is exported or shaded -- and a generator can flip a
    whole patch without changing a single count, so nothing else measured here
    would notice. That is what happened when a matched rim started leading a
    band: 1610 of 2139 faces on Plate And Cylinder turned over, with the vertex
    and face counts, the deviation and the open-edge count all unchanged.

    Compared against the nearest source polygon rather than a global "outward":
    a CAD import is a shell whose faces already carry the right orientation,
    and there is no other definition of right here.
    """
    if not source_obj.data.polygons or not result_obj.data.polygons:
        return 0
    bvh, tri_poly = pr.geometry.build_bvh_with_polygon_map(source_obj.data)
    to_source = source_obj.matrix_world.inverted() @ result_obj.matrix_world
    rotation = to_source.to_3x3()

    flipped = 0
    for poly in result_obj.data.polygons:
        hit = bvh.find_nearest(to_source @ poly.center)
        if not hit or hit[0] is None:
            continue
        source_poly = source_obj.data.polygons[tri_poly[hit[2]]]
        if (rotation @ poly.normal).dot(source_poly.normal) < 0.0:
            flipped += 1
    return flipped


# --- topology and cell quality ---------------------------------------------

def topology_report(result_obj, weld_distance):
    mesh = result_obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()

    non_manifold = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
    open_edges = sum(1 for e in bm.edges if e.is_boundary)
    wire = sum(1 for e in bm.edges if e.is_wire)

    sizes = {}
    for face in bm.faces:
        sizes[len(face.verts)] = sizes.get(len(face.verts), 0) + 1

    # Poles: interior vertices whose valence isn't 4. A quad retopology's
    # usability is largely how few of these there are and where they sit.
    poles = sum(1 for v in bm.verts
                if not v.is_boundary and len(v.link_edges) != 4)

    # Vertices that sit on top of each other but never welded -- the failure
    # the boundary weld exists to prevent, invisible in the viewport.
    unwelded = 0
    if weld_distance > 0.0:
        size = max(weld_distance, 1e-9)
        buckets = {}
        for v in bm.verts:
            key = (int(v.co.x / size), int(v.co.y / size), int(v.co.z / size))
            buckets.setdefault(key, []).append(v)
        seen = set()
        for key, bucket in buckets.items():
            neighbourhood = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        neighbourhood += buckets.get((key[0] + dx, key[1] + dy,
                                                      key[2] + dz), [])
            for v in bucket:
                for other in neighbourhood:
                    if other.index <= v.index:
                        continue
                    if (other.co - v.co).length <= weld_distance:
                        pair = (v.index, other.index)
                        if pair not in seen:
                            seen.add(pair)
                            unwelded += 1
    bm.free()
    return {
        "faces": len(mesh.polygons), "verts": len(mesh.vertices),
        "non_manifold": non_manifold, "open_edges": open_edges, "wire": wire,
        "sizes": sizes, "poles": poles, "unwelded": unwelded,
    }


def quality_report(result_obj):
    """Aspect ratio, skew from 90 degrees, and out-of-plane warp per quad."""
    mesh = result_obj.data
    aspects, skews, warps, edge_lengths = [], [], [], []

    for poly in mesh.polygons:
        loop = [mesh.vertices[i].co for i in poly.vertices]
        n = len(loop)
        lengths = [(loop[(i + 1) % n] - loop[i]).length for i in range(n)]
        edge_lengths += [length for length in lengths if length > 1e-12]
        if min(lengths, default=0.0) < 1e-12:
            continue
        aspects.append(max(lengths) / min(lengths))

        for i in range(n):
            before = loop[(i - 1) % n] - loop[i]
            after = loop[(i + 1) % n] - loop[i]
            if before.length < 1e-12 or after.length < 1e-12:
                continue
            angle = math.degrees(before.angle(after, 0.0))
            skews.append(abs(angle - (90.0 if n == 4 else 180.0 * (n - 2) / n)))

        if n == 4:
            # How far the 4th corner sits off the plane of the other three,
            # relative to the cell's own size.
            normal = (loop[1] - loop[0]).cross(loop[2] - loop[0])
            if normal.length > 1e-12:
                normal.normalize()
                warps.append(abs((loop[3] - loop[0]).dot(normal)) / max(lengths))

    return {"aspect": aspects, "skew": skews, "warp": warps,
            "edges": edge_lengths}


# --- driving the addon ------------------------------------------------------

def retopologize(context, obj, resolution):
    """Commit every patch of `obj`. Returns per-patch records."""
    state = context.scene.plasticity_retop
    state.resolution = resolution

    context.view_layer.objects.active = obj
    obj.select_set(True)
    pr.operators.enter_session_object(context, obj)

    analysis = pr.patch_data.analyse(obj.data)
    face_ids = list(dict.fromkeys(analysis.face_ids))
    records = []
    for face_id in face_ids:
        # Read the loop count from the mesh, not from `state`: a pick that
        # fails leaves state.num_loops describing the *previous* patch, so
        # reading it back would report a stale number as this patch's shape.
        patch = analysis.patches.get(face_id)
        loops = len(patch.boundary_loops) if patch is not None else 0

        generator, sides, _propagated = pr.operators.set_active_patch(
            context, obj, face_id)
        record = {"face_id": face_id, "generator": generator, "sides": sides,
                  "loops": loops, "committed": False,
                  "note": state.generator_note or "",
                  "warning": state.corner_warning or ""}
        if generator is not None and pr.mesh_build.has_preview():
            result = bpy.ops.retop.commit_patch()
            record["committed"] = result == {'FINISHED'}
            record["spans"] = (state.span_u, state.span_v, state.span)
        records.append(record)

    pr.operators.exit_session_object(context)
    return records


def report(obj, records, resolution):
    print("=" * 78)
    print(f"{obj.name}   ({len(obj.data.polygons)} source tris, "
          f"{len(records)} CAD faces, resolution {resolution})")
    print("=" * 78)

    failed = [r for r in records if r["generator"] is None]
    uncommitted = [r for r in records if r["generator"] is not None
                   and not r["committed"]]

    by_generator = {}
    for record in records:
        name = record["generator"] or "-- NOT SELECTABLE --"
        by_generator.setdefault(name, []).append(record)

    print("\n  selection")
    for name, group in sorted(by_generator.items(), key=lambda kv: -len(kv[1])):
        loops = sorted({r["loops"] for r in group})
        sides = sorted({r["sides"] for r in group if r["sides"] is not None})
        print(f"    {name:24s} {len(group):3d} patch(es)   "
              f"sides={sides} loops={loops}")
    if failed:
        print(f"    !! {len(failed)} patch(es) produced no preview: "
              f"{[r['face_id'] for r in failed]}")
    if uncommitted:
        print(f"    !! {len(uncommitted)} generated but failed to commit")

    # Past two loops the pipeline keeps only the outer boundary, so the holes
    # are paved over. That shows up in the deviation figures as a large max
    # against an unremarkable p95, and is worth naming rather than leaving to
    # be inferred.
    cornerless = [r for r in records if r["loops"] == 0]
    if cornerless:
        print(f"    !! {len(cornerless)} patch(es) have NO boundary loop at all "
              f"(a closed periodic face): {[r['face_id'] for r in cornerless]}")
    paved = [r for r in records if r["loops"] > 2]
    if paved:
        print(f"    !! {len(paved)} patch(es) have >2 boundary loops, so every "
              f"hole but the outer boundary is paved over:")
        for record in paved:
            print(f"         face {record['face_id']}: {record['loops']} loops")

    for record in records:
        if record["note"]:
            print(f"    note  (face {record['face_id']}): {record['note']}")
        if record["warning"]:
            print(f"    warn  (face {record['face_id']}): {record['warning']}")

    result_obj = bpy.data.objects.get(
        pr.mesh_build.result_object_name_for(obj))
    if result_obj is None or not result_obj.data.polygons:
        print("\n  no retopology was produced -- nothing to measure\n")
        return

    scale = bbox_diagonal(obj)
    interior, corners = deviation_samples(obj, result_obj)

    print(f"\n  deviation  (as % of the {scale:.4g}-unit bbox diagonal)")
    for label, values in (("face interiors", interior), ("vertices", corners)):
        if not values:
            continue
        print(f"    {label:14s} "
              f"mean {100 * (sum(values) / len(values)) / scale:7.4f}%   "
              f"rms {100 * rms(values) / scale:7.4f}%   "
              f"p95 {100 * percentile(values, 0.95) / scale:7.4f}%   "
              f"max {100 * max(values) / scale:7.4f}%")

    state = bpy.context.scene.plasticity_retop
    weld = pr.state.to_blender_units(state, state.boundary_weld_distance)
    topology = topology_report(result_obj, weld)
    print(f"\n  topology")
    print(f"    {topology['verts']} verts, {topology['faces']} faces, "
          f"sizes {topology['sizes']}")
    print(f"    open boundary edges : {topology['open_edges']}")
    print(f"    non-manifold edges  : {topology['non_manifold']}")
    print(f"    unwelded coincident : {topology['unwelded']}")
    print(f"    faces facing inward : {flipped_faces(obj, result_obj)}")
    print(f"    interior poles      : {topology['poles']}")

    quality = quality_report(result_obj)
    print(f"\n  cell quality  (percentiles, then worst)")
    for label, values, unit in (("aspect ratio", quality["aspect"], "x"),
                                ("skew from ideal", quality["skew"], " deg"),
                                ("quad warp", quality["warp"], "")):
        if not values:
            continue
        print(f"    {label:16s} p50 {percentile(values, 0.5):6.2f}{unit}  "
              f"p95 {percentile(values, 0.95):6.2f}{unit}  "
              f"max {max(values):6.2f}{unit}")
    edges = quality["edges"]
    if edges:
        mean = sum(edges) / len(edges)
        spread = math.sqrt(sum((e - mean) ** 2 for e in edges) / len(edges))
        print(f"    {'edge length':16s} mean {mean:.4g}  "
              f"cv {spread / mean:.3f}  min {min(edges):.4g}  max {max(edges):.4g}")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolution", default='MID')
    parser.add_argument("--object", default=None,
                        help="only this object (substring match)")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parser.parse_args(argv)

    try:
        pr.unregister()
    except Exception:
        pass
    pr.register()

    context = bpy.context
    targets = [obj for obj in sorted(bpy.data.objects, key=lambda o: o.name)
               if obj.type == 'MESH' and obj.data.get("face_ids")
               and (args.object is None or args.object.lower() in obj.name.lower())]
    if not targets:
        print("No bridge-imported meshes found (no 'face_ids' custom property).")
        return

    for obj in targets:
        records = retopologize(context, obj, args.resolution)
        report(obj, records, args.resolution)

    pr.operators.end_session(context)


if __name__ == "__main__":
    # Guarded so tests/test_fixtures.py can import the measurement helpers
    # rather than keep a second copy of them: the numbers the suite asserts on
    # and the numbers you read by hand then come from the same code.
    main()
