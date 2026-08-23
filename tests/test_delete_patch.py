"""Run inside Blender: blender --background --python tests/test_delete_patch.py

Deleting a committed patch for good (X during a re-edit).

Re-editing already takes the patch's faces out on pick and snapshots the result
mesh so Discard can put them back. Deleting is that same removal with the
snapshot dropped instead of restored -- so the thing worth testing is what it
must *not* take with it: the neighbours' geometry, their welds, and their
propagated spans.
"""
import os
import sys
import importlib

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy

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

state = bpy.context.scene.plasticity_retop

# ---------------------------------------------------------------------------
# Two patches sharing an edge, both retopped.
#
#   (0,2) ------------- (4,2)
#     |    patch 1        |
#   (0,0) ------------- (4,0)   <- shared
#     |    patch 2        |
#   (0,-2) ------------ (4,-2)
# ---------------------------------------------------------------------------
verts = [
    (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 2.0, 0.0), (0.0, 2.0, 0.0),
    (0.0, -2.0, 0.0), (4.0, -2.0, 0.0),
]
a0, a1, a2, a3, b0, b1 = range(6)
tris_1 = [(a0, a1, a2), (a0, a2, a3)]
tris_2 = [(b0, b1, a1), (b0, a1, a0)]

mesh = bpy.data.meshes.new("DeleteMesh")
mesh.from_pydata(verts, [], tris_1 + tris_2)
mesh.update()
mesh["groups"] = [0, len(tris_1) * 3, len(tris_1) * 3, len(tris_2) * 3]
mesh["face_ids"] = [1, 2]

obj = bpy.data.objects.new("DeleteObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
pr.operators.enter_session_object(bpy.context, obj)

state.ngon_mode = False
for face_id in (1, 2):
    pr.operators.set_active_patch(bpy.context, obj, face_id)
    state.span_u = 2
    state.span_v = 2
    bpy.ops.retop.commit_patch()

result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
faces_both = len(result.data.polygons)
verts_both = len(result.data.vertices)
check("both patches are committed", state.committed_patch_count == 2,
      state.committed_patch_count)
check("and the result holds both grids", faces_both == 8, faces_both)

registry_before = dict(pr.mesh_build.get_span_registry(result))
settings_before = dict(pr.mesh_build.get_patch_settings_table(result))
check("each patch recorded what it was built with",
      {"1", "2"} <= set(settings_before), sorted(settings_before))

# --- the operator is only offered during a re-edit ---
check("nothing to delete outside a re-edit", not bpy.ops.retop.delete_patch.poll())

pr.operators.set_active_patch(bpy.context, obj, 1)
check("picking a committed patch opens a re-edit", state.editing_committed)
check("which has already taken its faces out",
      len(result.data.polygons) < faces_both, len(result.data.polygons))
check("and now delete is available", bpy.ops.retop.delete_patch.poll())

removed = state.reedit_removed_faces
check("it says how many faces it took", removed == 4, removed)

# --- delete ---
bpy.ops.retop.delete_patch()
check("the patch is gone", len(result.data.polygons) == faces_both - removed,
      len(result.data.polygons))
check("only one patch is left", state.committed_patch_count == 1,
      state.committed_patch_count)
check("the session went back to picking", state.active_face_id == -1,
      state.active_face_id)
check("and the re-edit is closed, not left dangling",
      not state.editing_committed and not state.reedit_backup_mesh,
      f"{state.editing_committed} / {state.reedit_backup_mesh}")
check("no preview was left behind", not pr.mesh_build.has_preview())

# --- what it must NOT have taken with it ---
remaining_ids = pr.mesh_build.committed_face_ids(obj)
check("the neighbour's faces are untouched", set(remaining_ids) == {2},
      sorted(remaining_ids))

# The delete uses context='FACES', so the shared boundary vertices the
# neighbour still uses survive -- otherwise deleting one patch would tear a
# hole in the one next to it.
shared_ys = [v.co.y for v in result.data.vertices if abs(v.co.y) < 1e-6]
check("the shared boundary vertices survive, the neighbour still uses them",
      len(shared_ys) == 3, len(shared_ys))
check("the neighbour kept every face it had",
      len(result.data.polygons) == 4, len(result.data.polygons))

registry_after = pr.mesh_build.get_span_registry(result)
check("the span registry is left alone -- its entries describe shared "
      "boundaries the neighbour still owns",
      registry_after == registry_before, registry_after)

settings_after = pr.mesh_build.get_patch_settings_table(result)
check("but the deleted patch's own settings are forgotten",
      "1" not in settings_after, sorted(settings_after))
check("and the neighbour's are kept", "2" in settings_after, sorted(settings_after))

# --- the face is retoppable again, from scratch ---
name, num_sides, _propagated = pr.operators.set_active_patch(bpy.context, obj, 1)
check("the face can be retopped again", name is not None, name)
check("as a fresh patch, not a re-edit", not state.editing_committed)
bpy.ops.retop.commit_patch()
check("and committing puts it back", state.committed_patch_count == 2,
      state.committed_patch_count)

# --- deleting is undoable through the snapshot never being restored twice ---
pr.operators.set_active_patch(bpy.context, obj, 1)
snapshot = state.reedit_backup_mesh
check("a re-edit takes a snapshot", bool(snapshot), snapshot)
bpy.ops.retop.delete_patch()
check("deleting drops it rather than restoring it",
      bpy.data.meshes.get(snapshot) is None, snapshot)

pr.operators.end_session(bpy.context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
