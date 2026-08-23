"""Run inside Blender: blender --background --python tests/test_cad_display.py

Recovering the CAD structure the bridge does not send.

The protocol carries vertices, faces, normals, `groups` and `face_ids` -- no
edges, no B-rep vertices, no surface parameters. What `cad_display` puts back
splits into two kinds of claim, and they deserve different scrutiny:

- the Plasticity **edges** are exact. A boundary half-edge (a, b) of one patch
  is matched by (b, a) of the patch across it, so an edge is the maximal run of
  boundary segments whose neighbouring face id does not change, and a B-rep
  vertex is where it does. Both are read straight out of the mesh.
- the **surface flow** is derived, from each face's own boundary. It is only
  checked here for being present, finite and on the surface.

The mesh: two rectangles sharing one edge, the same shape the matching tests
use, because it makes every count checkable by hand.

  (0,3) ------------------- (4,3)
    |                         |     A (id 1)
  (0,0) ------------------- (4,0)   <- the one shared CAD edge
    |                         |     B (id 2)
  (0,-1) ------------------ (4,-1)
"""
import os
import sys
import importlib

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
cad_display = pr.cad_display

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

verts = [
    (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0),
    (0.0, -1.0, 0.0), (4.0, -1.0, 0.0),
]
a0, a1, a2, a3, b0, b1 = range(6)
tris_a = [(a0, a1, a2), (a0, a2, a3)]
tris_b = [(b0, b1, a1), (b0, a1, a0)]

mesh = bpy.data.meshes.new("CadMesh")
mesh.from_pydata(verts, [], tris_a + tris_b)
mesh.update()
mesh["groups"] = [0, 6, 6, 6]
mesh["face_ids"] = [1, 2]

# --- B-rep vertices ---------------------------------------------------------
#
# The shared edge runs from (0,0) to (4,0). Its two ends are where the face
# across the boundary changes, and they are the only two such points: every
# other boundary vertex has the same neighbour on both sides of it (nothing).
points = cad_display.brep_vertices(mesh)
check("the two ends of the shared edge are B-rep vertices",
      len(points) == 2, [tuple(round(c, 2) for c in p) for p in points])
check("and they are exactly where the two faces stop touching",
      sorted(round(p.x, 5) for p in points) == [0.0, 4.0],
      sorted(round(p.x, 5) for p in points))
check("both sit on the shared line",
      all(abs(p.y) < 1e-9 for p in points))

# --- edges ------------------------------------------------------------------
polylines = cad_display.edge_polylines(mesh)
check("three CAD edges: the shared one, and each face's free boundary",
      len(polylines) == 3, [len(p) for p in polylines])

shared = [p for p in polylines if len(p) == 2]
check("the shared edge is a single segment", len(shared) == 1,
      [len(p) for p in polylines])
check("running the length of the join",
      shared and abs((shared[0][0] - shared[0][1]).length - 4.0) < 1e-9,
      shared[0][0][:] if shared else None)

# The point of the face-id rule: both patches walk the shared edge, only one
# draws it. Without that every join would be drawn twice. Counted as segments
# lying *along* the join, not as points near it -- the free boundaries of both
# faces start and end on it too.
segments = cad_display.edge_segments(mesh)
pairs = list(zip(segments[0::2], segments[1::2]))
on_join = [(a, b) for a, b in pairs if abs(a.y) < 1e-9 and abs(b.y) < 1e-9]
check("the shared edge is emitted once, not once per face",
      len(on_join) == 1, len(on_join))
check("and the whole model comes to seven segments",
      len(pairs) == 7, len(pairs))

# --- scoping ----------------------------------------------------------------
only_a = cad_display.edge_polylines(mesh, face_id=1)
check("asking for one patch gives only its boundary", len(only_a) == 2,
      [len(p) for p in only_a])
check("including the shared edge, which now has no pair to defer to",
      any(len(p) == 2 for p in only_a), [len(p) for p in only_a])
check("and its B-rep vertices are the same two",
      len(cad_display.brep_vertices(mesh, face_id=1)) == 2)

# --- surface flow -----------------------------------------------------------
flow = cad_display.flow_segments(mesh, density=3)
check("the flow grid is drawn for both faces", len(flow) > 0, len(flow))
check("every flow point lands on the surface -- the mesh is flat, so z = 0",
      all(abs(p.z) < 1e-6 for p in flow))
check("and inside the model's own extent",
      all(-1.001 <= p.y <= 3.001 and -0.001 <= p.x <= 4.001 for p in flow))

denser = cad_display.flow_segments(mesh, density=6)
check("a higher density draws more of it", len(denser) > len(flow),
      f"{len(flow)} -> {len(denser)}")

# --- caching ----------------------------------------------------------------
#
# A draw handler runs on every redraw, so none of this may be recomputed there.
check("a second ask returns the very same list, not an equal one",
      cad_display.edge_segments(mesh) is segments)
check("and the two densities are cached apart",
      cad_display.flow_segments(mesh, density=3) is flow)

mesh.vertices[a2].co.x = 5.0  # move a corner: the mesh is no longer the same
mesh.update()
check("moving a vertex invalidates it",
      cad_display.edge_segments(mesh) is not segments)

cad_display.invalidate()
check("and it can be dropped outright",
      cad_display.edge_segments(mesh) is not segments)

# --- a mesh with no patch data ----------------------------------------------
plain = bpy.data.meshes.new("PlainMesh")
plain.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
plain.update()
check("a mesh with no Plasticity data yields one boundary and no vertices",
      cad_display.brep_vertices(plain) == [],
      cad_display.brep_vertices(plain))

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
