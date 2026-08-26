"""Regenerate the EXPECTED table in tests/test_fixtures.py.

    blender tests/fixtures/TestCases.blend --background --python scripts/gen_expectations.py

Prints the table to stdout; paste it over the one in the test. It exists
because the goldens are keyed by Plasticity face id, and a re-export of the
fixture renumbers every one of them -- so "the fixture changed" and "the code
regressed" would otherwise be indistinguishable, and the only way to tell them
apart is to regenerate deliberately and read the diff.

Read that diff, don't just accept it. Generator and side count per face are
the entries that should stay put across a re-export of unchanged shapes;
vertex and face counts are order-sensitive (see the note in
tests/fixtures/README.md) and can move for reasons that are not regressions.
"""
import importlib
import math
import os
import sys

import bpy

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))
sys.path.insert(0, os.path.join(_ADDON_DIR, "scripts"))

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
import benchmark

RESOLUTION = 'MID'


def ceiling(measured: float) -> float:
    """A deviation ceiling with headroom, rounded to something a human types."""
    if measured <= 1e-7:
        return 0.0
    target = measured * 1.3
    exponent = math.floor(math.log10(target))
    return round(math.ceil(target / (10 ** exponent) * 10) / 10 * (10 ** exponent),
                 max(0, -exponent + 2))


def main() -> None:
    try:
        pr.unregister()
    except Exception:
        pass
    pr.register()

    context = bpy.context
    state = context.scene.plasticity_retop

    for obj in sorted(bpy.data.objects, key=lambda o: o.name):
        if obj.type != 'MESH' or not obj.data.get("face_ids"):
            continue
        records = benchmark.retopologize(context, obj, RESOLUTION)
        result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
        verts = len(result.data.vertices) if result else 0
        faces = len(result.data.polygons) if result else 0

        if faces:
            interior, _corners = benchmark.deviation_samples(obj, result)
            worst = 100.0 * max(interior, default=0.0) / benchmark.bbox_diagonal(obj)
            weld = pr.state.to_blender_units(state, state.boundary_weld_distance)
            topology = benchmark.topology_report(result, weld)
            dev = repr(ceiling(worst))
            open_edges = topology["open_edges"]
            measured = f"  # measured {worst:.4f}%"
        else:
            dev, open_edges, measured = "None", "None", ""

        print(f'    "{obj.name}": dict(')
        print(f'        source_tris={len(obj.data.polygons)}, patches={len(records)},')
        print(f'        result_verts={verts}, result_faces={faces},')
        print(f'        faces=[')
        for record in sorted(records, key=lambda r: r["face_id"]):
            gen = f'"{record["generator"]}"' if record["generator"] else "None"
            print(f'            ({record["face_id"]}, {gen}, '
                  f'{record["sides"]}, {record["loops"]}),')
        print(f'        ],')
        print(f'        max_deviation_pct={dev},{measured}')
        print(f'        open_edges={open_edges},')
        print(f'    ),')

    pr.operators.end_session(context)


if __name__ == "__main__":
    main()
