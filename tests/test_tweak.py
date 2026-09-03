"""Run inside Blender: blender --background --python tests/test_tweak.py

Hand-editing the committed retopology in Blender's own Edit Mode (Tab).

Two halves, and they fail in opposite ways:

- **the setup**, which overwrites the user's snapping and auto-merge settings
  and therefore has to put them back on every exit, including the failed ones;
- **the repair**, which is the only reason this is more than a `mode_set`.
  Blender knows nothing about `retop_patch_face_id` or `retop_source_vid`, so a
  knife cut leaves faces no patch owns (invisible to re-editing: the patch
  reads as never retopped and a re-edit stacks a second grid on it) and
  vertices claiming to be CAD corners they are nowhere near (welded onto those
  corners by identity by the next commit that touches them).

`--background` has no Edit Mode worth entering and no undo stack, so the round
trip itself is exercised through the pieces rather than through the key: the
tool-setting snapshot/restore, `repair_manual_edits` on a mesh edited the way
the knife would edit it, and the phase/refusal rules the modal and the panel
both read.
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
# Two patches sharing an edge, both retopped -- the same shape test_delete_patch
# uses, because the interesting hand edits all live on a shared boundary.
# ---------------------------------------------------------------------------
verts = [
    (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 2.0, 0.0), (0.0, 2.0, 0.0),
    (0.0, -2.0, 0.0), (4.0, -2.0, 0.0),
]
a0, a1, a2, a3, b0, b1 = range(6)
tris_1 = [(a0, a1, a2), (a0, a2, a3)]
tris_2 = [(b0, b1, a1), (b0, a1, a0)]

mesh = bpy.data.meshes.new("TweakMesh")
mesh.from_pydata(verts, [], tris_1 + tris_2)
mesh.update()
mesh["groups"] = [0, len(tris_1) * 3, len(tris_1) * 3, len(tris_2) * 3]
mesh["face_ids"] = [1, 2]

obj = bpy.data.objects.new("TweakObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

# ---------------------------------------------------------------------------
# When Tab refuses, and why
# ---------------------------------------------------------------------------
check("no session: no hand-edit", pr.tweak.can_tweak(bpy.context) is not None,
      pr.tweak.can_tweak(bpy.context))

pr.operators.enter_session_object(bpy.context, obj)
check("the session opens on picking", state.session_phase == 'PATCH')

reason = pr.tweak.can_tweak(bpy.context)
check("nothing committed yet: refused, with a reason",
      reason is not None and "no committed patch" in reason, reason)

state.ngon_mode = False
for face_id in (1, 2):
    pr.operators.set_active_patch(bpy.context, obj, face_id)
    state.span_u = 2
    state.span_v = 2
    bpy.ops.retop.commit_patch()

result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
check("both patches committed", state.committed_patch_count == 2,
      state.committed_patch_count)
check("now it would open", pr.tweak.can_tweak(bpy.context) is None,
      pr.tweak.can_tweak(bpy.context))

# A patch open for adjustment has its faces *out* of the result mesh with only
# a snapshot to put them back, and anything written to a mesh Blender holds in
# Edit Mode is discarded on exit -- the patch would be gone for good.
pr.operators.set_active_patch(bpy.context, obj, 1)
state.session_phase = 'ADJUST'
reason = pr.tweak.can_tweak(bpy.context)
check("refused while a patch is open", reason is not None, reason)
check("and says what to do about it", reason and "commit or discard" in reason.lower(),
      reason)
bpy.ops.retop.clear_preview()
state.session_phase = 'PATCH'
pr.operators.restore_reedit_removal(bpy.context)

# ---------------------------------------------------------------------------
# The tool settings are the user's, and have to come back
# ---------------------------------------------------------------------------
tool_settings = bpy.context.scene.tool_settings
tool_settings.use_snap = False
tool_settings.use_mesh_automerge = False
tool_settings.double_threshold = 0.123
before = pr.tweak.snapshot_tool_settings(bpy.context)

state.tweak_auto_merge = True
state.tweak_merge_distance = 0.05
pr.tweak.apply_tool_settings(bpy.context, pr.tweak._wanted_settings(state))
check("snapping is on for the round trip", tool_settings.use_snap)
check("on vertices", 'VERTEX' in set(tool_settings.snap_elements),
      str(set(tool_settings.snap_elements)))
check("against the mesh being edited, or a seam can't be closed",
      tool_settings.use_snap_self)
check("auto-merge is on", tool_settings.use_mesh_automerge)
check("at the distance the panel asks for",
      abs(tool_settings.double_threshold - 0.05) < 1e-6,
      tool_settings.double_threshold)
check("vertex select mode", tuple(tool_settings.mesh_select_mode) == (True, False, False),
      tuple(tool_settings.mesh_select_mode))

# Snap to the CAD surface is optional: welding two retopo vertices together is
# easier with the surface out of the way.
state.tweak_snap_surface = False
pr.tweak.apply_tool_settings(bpy.context, pr.tweak._wanted_settings(state))
check("surface snapping can be turned off",
      'FACE_NEAREST' not in set(tool_settings.snap_elements),
      str(set(tool_settings.snap_elements)))

import json
state.tweak_saved_tool_settings = json.dumps(before)
pr.tweak.restore_tool_settings(bpy.context)
check("the settings come back exactly", not tool_settings.use_snap
      and not tool_settings.use_mesh_automerge
      and abs(tool_settings.double_threshold - 0.123) < 1e-6,
      f"{tool_settings.use_snap} / {tool_settings.use_mesh_automerge} / "
      f"{tool_settings.double_threshold}")
check("and the snapshot is spent, not replayed later",
      state.tweak_saved_tool_settings == "")

# ---------------------------------------------------------------------------
# The retopology draws in front for the length of the trip -- and only that
# ---------------------------------------------------------------------------
# In Front is a draw flag, not a lift: nothing moves, so what is on screen is
# still exactly where the topology is. That is the whole reason it is this and
# not an offset, and it is why it can be on while the surface is not.
state.result_see_through = False
state.session_phase = 'PATCH'
pr.mesh_build.refresh_result_appearance(bpy.context)
check("outside a hand-edit the result is occluded like anything else",
      not result.show_in_front)

state.tweak_draw_in_front = True
state.tweak_source_object = obj.name
state.session_phase = 'TWEAK'
pr.mesh_build.refresh_result_appearance(bpy.context)
check("during one it draws over the surface", result.show_in_front)

# A redraw triggered mid-edit by any other setting must agree with the trip
# rather than undo it, which is what routing it through the same function buys.
state.tweak_draw_in_front = False
pr.mesh_build.refresh_result_appearance(bpy.context)
check("...unless the preference says not to", not result.show_in_front)

state.tweak_draw_in_front = True
state.session_phase = 'PATCH'
state.tweak_source_object = ""
pr.mesh_build.refresh_result_appearance(bpy.context)
check("and it goes back on the way out", not result.show_in_front)

# Ending a session mid-trip must not leave them rewritten either.
state.tweak_saved_tool_settings = json.dumps(before)
tool_settings.use_snap = True
pr.operators.end_session(bpy.context)
check("ending the session restores them too", not tool_settings.use_snap)
check("and clears the snapshot", state.tweak_saved_tool_settings == "")

# ---------------------------------------------------------------------------
# The repair -- what a knife cut actually leaves behind
# ---------------------------------------------------------------------------
pr.operators.enter_session_object(bpy.context, obj)

patch_attr = result.data.attributes[pr.mesh_build.PATCH_ID_ATTR]
vid_attr = result.data.attributes[pr.mesh_build.SOURCE_VID_ATTR]

faces_before = len(result.data.polygons)
ids_before = [d.value for d in patch_attr.data]
check("every committed face carries its patch id",
      pr.mesh_build.NO_PATCH not in ids_before, sorted(set(ids_before)))

# A knife cut: the new faces carry no patch id (Blender has no idea what one
# is), so the patch they belong to reads as partly "never retopped".
untagged = [i for i, fid in enumerate(ids_before) if fid == 1][:2]
for index in untagged:
    patch_attr.data[index].value = pr.mesh_build.NO_PATCH
result.data.update()

# ... and a vertex the cut created inherits a neighbour's source-vertex id,
# i.e. claims to *be* a CAD corner it is nowhere near.
free_vert = next(
    (i for i, d in enumerate(vid_attr.data)
     if d.value == pr.mesh_build.NO_SOURCE), None)
check("there is an interior vertex to falsify", free_vert is not None)
vid_attr.data[free_vert].value = 0        # claims source vertex 0, at (0,0,0)
bogus_range = len(result.data.vertices) - 1
vid_attr.data[bogus_range].value = 9999   # not an index into anything
result.data.update()

adopted, cleared = pr.mesh_build.repair_manual_edits(bpy.context, obj)

ids_after = [d.value for d in result.data.attributes[
    pr.mesh_build.PATCH_ID_ATTR].data]
check("the untagged faces were adopted back onto their patch",
      adopted == len(untagged), f"{adopted} of {len(untagged)}")
check("and onto the right one", all(ids_after[i] == 1 for i in untagged),
      [ids_after[i] for i in untagged])
check("nothing else moved", len(result.data.polygons) == faces_before,
      len(result.data.polygons))

vids_after = [d.value for d in result.data.attributes[
    pr.mesh_build.SOURCE_VID_ATTR].data]
check("the out-of-range id is gone",
      vids_after[bogus_range] == pr.mesh_build.NO_SOURCE, vids_after[bogus_range])
check("so is the one claiming a corner it isn't at",
      vids_after[free_vert] == pr.mesh_build.NO_SOURCE, vids_after[free_vert])
check("both were counted", cleared >= 2, cleared)

# A corner that is *really* there keeps its id: a hand-nudged corner is the
# point of this mode, and stripping its identity would undo the fix on the
# next commit that touches it.
real_corners = [v for v in vids_after if v != pr.mesh_build.NO_SOURCE]
check("the genuine corner ids survive", len(real_corners) > 0, len(real_corners))
check("and no source vertex is claimed twice",
      len(real_corners) == len(set(real_corners)), sorted(real_corners))

# A trip that only moved vertices costs nothing.
again = pr.mesh_build.repair_manual_edits(bpy.context, obj)
check("repairing a clean mesh is a no-op", again == (0, 0), again)

# ---------------------------------------------------------------------------
# Tab belongs to the session in the OBJECT phase too
# ---------------------------------------------------------------------------
# Between objects the session holds none, and Tab used to fall through to
# Blender -- which put the CAD *source* into Edit Mode, the one mesh nothing
# here ever wants edited by hand. The selection answers instead.
previous_phase = state.session_phase
previous_object = state.session_object_name
state.session_phase = 'OBJECT'
state.session_object_name = ""
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
check("with an object selected, Tab opens its retopology",
      pr.tweak.can_tweak(bpy.context) is None, pr.tweak.can_tweak(bpy.context))
check("and it resolves to the source, not the result",
      pr.tweak._session_source(bpy.context) is obj,
      pr.tweak._session_source(bpy.context))

# Selecting the retopology itself means the same thing: it is the mesh being
# edited, and `<X>_Retop` names X the same way the session entry resolves it.
result_obj = bpy.data.objects[pr.mesh_build.result_object_name_for(obj)]
obj.select_set(False)
result_obj.select_set(True)
bpy.context.view_layer.objects.active = result_obj
check("selecting the retopology resolves to the same source",
      pr.tweak._session_source(bpy.context) is obj,
      pr.tweak._session_source(bpy.context))

# Nothing selected that has any retopology: refused with a reason, and the
# refusal is what the modal reports -- Tab is consumed either way, so it can
# never reach `object.editmode_toggle` while a session runs.
result_obj.select_set(False)
for other in bpy.context.selected_objects:
    other.select_set(False)
bpy.context.view_layer.objects.active = None
reason = pr.tweak.can_tweak(bpy.context)
check("with nothing to edit it refuses", reason is not None, reason)
check("and says what to select", reason and "select" in reason.lower(), reason)
check("hand_edit is a key the modal must consume even when it refuses",
      "hand_edit" in pr.operators.RETOP_OT_session._MUST_CONSUME)

bpy.context.view_layer.objects.active = obj
obj.select_set(True)
state.session_phase = previous_phase
state.session_object_name = previous_object


# ---------------------------------------------------------------------------
# Where the modal sends Tab
# ---------------------------------------------------------------------------
# Three actions share Tab, with mutually exclusive polls, and the modal has to
# resolve it the way Blender resolves a keymap: the first one whose poll
# passes. Taking the first *match* meant every Tab resolved to U/V and fell
# through to the keymap when that poll failed -- which worked by an ordering
# nothing states, and in the OBJECT phase reached Blender's own Tab.
class _Tab:
    type = 'TAB'
    value = 'PRESS'
    ctrl = shift = alt = oskey = False


check("three actions answer to Tab",
      pr.keymap.session_actions_for(_Tab()) ==
      ["span_axis", "hand_edit", "end_tweak"],
      pr.keymap.session_actions_for(_Tab()))

state.session_phase = 'PATCH'
check("while picking, Tab is the hand-edit trip",
      pr.keymap.session_action_for(_Tab()) == "hand_edit",
      pr.keymap.session_action_for(_Tab()))
state.session_phase = 'TWEAK'
check("inside the trip, Tab is the way back",
      pr.keymap.session_action_for(_Tab()) == "end_tweak",
      pr.keymap.session_action_for(_Tab()))
state.session_phase = 'ADJUST'
pr.operators.set_active_patch(bpy.context, obj, 1)
check("with a patch open, Tab is U/V and nothing else -- the one phase this "
      "must not take over",
      pr.keymap.session_action_for(_Tab()) == "span_axis",
      pr.keymap.session_action_for(_Tab()))
bpy.ops.retop.clear_preview()
pr.operators.restore_reedit_removal(bpy.context)
state.session_phase = 'PATCH'

state.session_active = False
check("with no session, no Tab action is live",
      not any(pr.keymap.action_is_live(a)
              for a in ("span_axis", "hand_edit", "end_tweak")))
state.session_active = True


check("Tab is still on the pass-through list for the panel",
      'TAB' in pr.operators.PANEL_EVENTS)
check("the phase exists", 'TWEAK' in
      {item.identifier for item in
       state.bl_rna.properties['session_phase'].enum_items})

state.session_phase = 'TWEAK'
check("the way back is available", bpy.ops.retop.end_tweak.poll())
check("and starting another trip is not", not bpy.ops.retop.tweak_mesh.poll())
state.session_phase = 'PATCH'
check("from picking, the trip is available", bpy.ops.retop.tweak_mesh.poll())
check("and the way back is not", not bpy.ops.retop.end_tweak.poll())

# The overlay must describe the phase it is actually in, and a draw handler
# that references a name that isn't there fails at the call.
state.session_phase = 'TWEAK'
binds = pr.overlay.keybinds_for(state)
check("the overlay lists the hand-edit keys",
      any(key == 'K' for key, _action in binds), binds)
check("including the way back", any(key == 'Tab' for key, _action in binds), binds)
state.session_phase = 'PATCH'
check("and Tab is advertised where it is bound",
      any(key == 'Tab' for key, _action in pr.overlay.keybinds_for(state)),
      pr.overlay.keybinds_for(state))

pr.operators.end_session(bpy.context)

# ---------------------------------------------------------------------------
# Starting a session from Edit Mode
#
# It used to run the whole entry path -- create the result mesh, create the
# preview object, push an undo step -- and only then have the modal hand the
# viewport straight back, because it does nothing outside Object Mode. Two
# datablocks created from inside an edit session for a session that never
# opened is the shape of the Ctrl+Z crash the undo invariant exists to prevent.
# ---------------------------------------------------------------------------
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
try:
    bpy.ops.object.mode_set(mode='EDIT')
except RuntimeError as exc:
    print(f"[SKIP] no Edit Mode in this build: {exc}")
else:
    check("the session refuses to start from Edit Mode",
          not bpy.ops.retop.session.poll())
    check("and nothing was created behind it",
          bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME) is None,
          "a preview object outlived end_session")
    bpy.ops.object.mode_set(mode='OBJECT')
    check("and starts again once Blender is back in Object Mode",
          bpy.ops.retop.session.poll())

# ---------------------------------------------------------------------------
# The whole round trip, taken from the OBJECT phase
# ---------------------------------------------------------------------------
# The phase it started from is the phase it has to come back to: a Tab taken
# between objects was never a choice of object, so landing in PATCH would claim
# the session had entered one. And the repair still has to run, which is the
# reason the source is remembered for the trip -- the session holds none here.
pr.operators.enter_session_object(bpy.context, obj)
pr.operators.exit_session_object(bpy.context)
check("the session is between objects", state.session_phase == 'OBJECT'
      and state.session_object_name == "", state.session_phase)

bpy.context.view_layer.objects.active = obj
obj.select_set(True)
error = pr.tweak.enter_tweak(bpy.context)
if error is not None and "Edit Mode" in error:
    print(f"[SKIP] no Edit Mode in this build: {error}")
else:
    check("Tab from the OBJECT phase opens the trip", error is None, error)
    check("on the retopology, not the CAD object",
          bpy.context.view_layer.objects.active
          is bpy.data.objects[pr.mesh_build.result_object_name_for(obj)],
          bpy.context.view_layer.objects.active)
    check("and it remembered which source the trip is about",
          state.tweak_source_object == obj.name, state.tweak_source_object)
    check("and where to go back to", state.tweak_return_phase == 'OBJECT',
          state.tweak_return_phase)

    pr.tweak.exit_tweak(bpy.context)
    check("coming back lands in the phase it left from",
          state.session_phase == 'OBJECT', state.session_phase)
    check("and spends what it remembered",
          state.tweak_source_object == "" and state.tweak_return_phase == "",
          f"{state.tweak_source_object!r} / {state.tweak_return_phase!r}")
    check("with the tool settings back", not tool_settings.use_snap,
          tool_settings.use_snap)

pr.operators.end_session(bpy.context)

pr.unregister()

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
