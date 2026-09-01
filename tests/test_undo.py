"""Run inside Blender: blender --background --python tests/test_undo.py

Ctrl+Z during a session must peel off the last patch, not the whole session.

The session pushes undo steps by hand (see operators.push_undo). It used to
push only three: entering an object, opening a re-edit, ending the session --
so from anywhere mid-session the nearest step below was "Retop: enter <obj>",
and one Ctrl+Z went to the file state *before* the session: every committed
patch gone at once. Each change to the result mesh now gets its own step.

There is no undo stack in --background, so what is checked here is that the
push happens, exactly once per change, and that Blender is not also pushing one
of its own (an operator with OPTYPE_UNDO plus an explicit push = two identical
states on the stack, i.e. a Ctrl+Z that appears to do nothing).
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

# --- record every undo step the session asks for -------------------------
_real_push_undo = pr.operators.push_undo
PUSHED = []


def _recording_push_undo(message):
    PUSHED.append(message)


pr.operators.push_undo = _recording_push_undo


def steps():
    """The messages pushed since the last call."""
    taken = list(PUSHED)
    PUSHED.clear()
    return taken


# ---------------------------------------------------------------------------
# Two patches sharing an edge (same shape as test_delete_patch).
# ---------------------------------------------------------------------------
verts = [
    (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 2.0, 0.0), (0.0, 2.0, 0.0),
    (0.0, -2.0, 0.0), (4.0, -2.0, 0.0),
]
a0, a1, a2, a3, b0, b1 = range(6)
tris_1 = [(a0, a1, a2), (a0, a2, a3)]
tris_2 = [(b0, b1, a1), (b0, a1, a0)]

mesh = bpy.data.meshes.new("UndoMesh")
mesh.from_pydata(verts, [], tris_1 + tris_2)
mesh.update()
mesh["groups"] = [0, len(tris_1) * 3, len(tris_1) * 3, len(tris_2) * 3]
mesh["face_ids"] = [1, 2]

obj = bpy.data.objects.new("UndoObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

# ---------------------------------------------------------------------------
# One step per structural moment, and one per committed patch.
# ---------------------------------------------------------------------------
pr.operators.enter_session_object(bpy.context, obj)
check("entering an object is a step of its own", len(steps()) == 1)

state.ngon_mode = False
for face_id in (1, 2):
    pr.operators.set_active_patch(bpy.context, obj, face_id)
    check(f"picking uncommitted patch {face_id} pushes nothing", steps() == [],
          "picking creates no datablock and changes no mesh")
    state.span_u = 2
    state.span_v = 2
    bpy.ops.retop.commit_patch()
    pushed = steps()
    check(f"committing patch {face_id} pushes exactly one step", len(pushed) == 1,
          str(pushed))

result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
check("both patches are committed", state.committed_patch_count == 2,
      state.committed_patch_count)

# Blender pushes its own step for an operator flagged OPTYPE_UNDO, but only
# when it is run from the UI -- the session modal calls these through bpy.ops,
# which is exactly where the step was missing. They push by hand instead, so
# the flag has to be off or the two would stack up.
for op in (pr.operators.RETOP_OT_commit_patch,
           pr.operators.RETOP_OT_delete_patch,
           pr.operators.RETOP_OT_clear_preview):
    check(f"{op.bl_idname} pushes its own step rather than flagging UNDO",
          'UNDO' not in op.bl_options, str(op.bl_options))

# ---------------------------------------------------------------------------
# A re-edit: opening it, and both ways out of it.
# ---------------------------------------------------------------------------
pr.operators.set_active_patch(bpy.context, obj, 1)
check("opening a re-edit is a step of its own", len(steps()) == 1,
      "it removes faces and creates the snapshot datablock")

bpy.ops.retop.clear_preview()
check("discarding a re-edit pushes a step", len(steps()) == 1,
      "it puts the faces back and frees the snapshot")
check("and the patch came back", state.committed_patch_count == 2,
      state.committed_patch_count)

pr.operators.set_active_patch(bpy.context, obj, 1)
steps()
bpy.ops.retop.commit_patch()
check("re-committing a patch pushes exactly one step", len(steps()) == 1)

pr.operators.set_active_patch(bpy.context, obj, 1)
steps()
bpy.ops.retop.delete_patch()
check("deleting a patch pushes exactly one step", len(steps()) == 1)
check("the patch is gone", state.committed_patch_count == 1,
      state.committed_patch_count)

# A discard with nothing to restore changed no datablock at all: a step there
# is a Ctrl+Z that does nothing.
# Patch 1 was just deleted, so picking it again is a fresh patch, not a re-edit.
pr.operators.set_active_patch(bpy.context, obj, 1)
steps()
check("picking the deleted patch reopens it fresh", not state.editing_committed)
bpy.ops.retop.clear_preview()
check("discarding a plain preview pushes nothing", steps() == [], str(PUSHED))

# ---------------------------------------------------------------------------
# The handler that runs after the step, and the reconciliation it defers.
# ---------------------------------------------------------------------------
pr.operators.set_active_patch(bpy.context, obj, 1)
steps()
pr.operators._undo_needs_reconcile = False
pr.operators._on_undo_redo(bpy.context.scene)
check("the undo handler asks the modal to catch up",
      pr.operators._undo_needs_reconcile,
      "the preview it leaves behind belongs to a patch that is no longer open")
check("but pushes nothing itself", steps() == [], str(PUSHED))

# Ending a session *because* of an undo must not push: that would truncate the
# redo branch the user just made available.
pr.operators.end_session(bpy.context, push=False)
check("end_session(push=False) leaves the redo branch alone", steps() == [],
      str(PUSHED))

# --- redo -----------------------------------------------------------------
#
# Ctrl+Shift+Z is symmetric with Ctrl+Z here and needs nothing of its own: the
# steps are Blender's, so redo replays them. What it does need is the same
# reconciliation, because a redo invalidates the session's idea of the world
# exactly as an undo does -- the preview still holds a patch, the hover still
# names a face on a mesh that just changed underneath it. Hence the *same*
# handler on both lists.
handler_lists = {
    "undo_post": [h.__name__ for h in bpy.app.handlers.undo_post],
    "redo_post": [h.__name__ for h in bpy.app.handlers.redo_post],
}
check("the handler runs after a redo too, not just an undo",
      "_on_undo_redo" in handler_lists["redo_post"], handler_lists)
check("and exactly once on each list -- a reload must not stack duplicates",
      handler_lists["undo_post"].count("_on_undo_redo") == 1
      and handler_lists["redo_post"].count("_on_undo_redo") == 1,
      handler_lists)

# And the redo path must not push either: a push is what truncates the branch,
# so pushing from the handler would make one Ctrl+Shift+Z the last one possible.
pr.operators.enter_session_object(bpy.context, obj)
pr.operators.set_active_patch(bpy.context, obj, 1)
steps()
pr.operators._on_undo_redo(bpy.context.scene)
check("reconciling after a redo pushes nothing", steps() == [], str(PUSHED))
check("and drops the active patch, whose mesh state has just been replaced",
      state.active_face_id == -1, state.active_face_id)
pr.operators.end_session(bpy.context)
steps()

pr.operators.enter_session_object(bpy.context, obj)
steps()
pr.operators.end_session(bpy.context)
check("ending a session normally still pushes", len(steps()) == 1)

pr.operators.push_undo = _real_push_undo
pr.unregister()

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
