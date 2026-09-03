"""Hand-correcting the committed retopology, in Blender's own Edit Mode.

The generators get a patch's boundary right most of the time; when they don't
-- a side whose neighbour could not be matched, two boundaries that ended up
one vertex apart, a merge that did not take -- the fix is a handful of vertex
moves and one extra edge, and every tool for that already exists in Blender.
Merge by distance, vertex snapping, knife, loop cut and connect-vertex-path are
all **Edit Mode** operators, so there is no version of this that stays in
Object Mode: an object-mode reimplementation would be a worse knife and a worse
snap, written twice.

So the session hands the viewport over instead. `Tab` from the patch-picking
phase selects `<Source>_Retop`, configures the tool settings that make manual
retopology work (vertex snapping, auto-merge at a threshold you can set),
enters Edit Mode and stops listening; `Tab` again comes back. What the addon
owns is the two ends of that round trip:

- **the setup**, so the mode is usable the moment it opens rather than after
  four trips to the snapping popover, and
- **the repair**, because Blender does not know about this addon's bookkeeping.
  A knife cut makes faces carrying no patch id and vertices carrying a *copied*
  source-vertex id, and both of those are read later on: an untagged face is
  invisible to re-editing (the patch reads as "never retopped", so a re-edit
  builds a second grid on top of it), and a vertex falsely claiming to be CAD
  corner N gets welded onto that corner by identity by the next commit that
  touches it. `mesh_build.repair_manual_edits` puts both right on the way out.

Only from the `PATCH` phase, and that is deliberate: a re-edit has the patch's
faces *out* of the result mesh with only a snapshot to put them back, and
anything written to a mesh Blender holds in Edit Mode is discarded on exit --
the patch would be gone for good. That is the same rule
`RETOP_OT_session._leave_for_other_mode` already enforces, said from the other
side.
"""
import json

import bpy

from . import mesh_build
from . import state as state_mod


# Tool settings this mode overwrites, and therefore has to put back. Read and
# written by name through getattr/setattr: `snap_elements` and friends have
# been renamed and split more than once across Blender versions (4.x added
# `snap_elements_base` and FACE_NEAREST), and an addon that hard-requires one
# spelling breaks on the next release for no gain. A name that isn't there is
# skipped both ways, so the snapshot and the restore stay symmetrical.
_SNAPSHOT_KEYS = (
    "use_snap",
    "snap_elements",
    "snap_target",
    "use_snap_self",
    "use_snap_align_rotation",
    "use_snap_backface_culling",
    "use_mesh_automerge",
    "double_threshold",
    "mesh_select_mode",
)


def _wanted_settings(
    state: "state_mod.RetopPatchState",
) -> dict[str, object]:
    """What a manual retopology pass wants, as opposed to what modelling wants.

    The two that matter:

    - VERTEX snapping with `use_snap_self` on. The whole point is dragging a
      vertex onto its twin in the *same* mesh -- the seam a failed match left --
      and Blender's default (snap to other objects only) makes exactly that
      impossible.
    - auto-merge. Merge by distance is the fix, but reaching for `M` after
      every move is the sort of step that gets forgotten once and leaves a
      crack nobody sees until the mesh is exported. With auto-merge on, a
      vertex dropped within the threshold of another simply *is* merged.

    FACE_NEAREST is added on top when `tweak_snap_surface` is on, so a vertex
    being dragged stays on the CAD surface instead of floating off it -- the
    same job reprojection does for a generated patch.
    """
    elements = {'VERTEX'}
    if state.tweak_snap_surface:
        elements.add('FACE_NEAREST')
    return {
        "use_snap": True,
        "snap_elements": elements,
        "snap_target": 'CLOSEST',
        "use_snap_self": True,
        "use_snap_align_rotation": False,
        "use_mesh_automerge": bool(state.tweak_auto_merge),
        "double_threshold": state_mod.to_blender_units(
            state, state.tweak_merge_distance),
        "mesh_select_mode": (True, False, False),
    }


def _jsonable(value: object) -> object:
    """Sets and bpy's own sequence types don't survive json.dumps."""
    if isinstance(value, (set, frozenset)):
        return {"__set__": sorted(str(item) for item in value)}
    if isinstance(value, (tuple, list)):
        return list(value)
    if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
        return list(value)  # bpy_prop_array (mesh_select_mode)
    return value


def _from_jsonable(value: object) -> object:
    if isinstance(value, dict) and "__set__" in value:
        return set(value["__set__"])
    return value


def snapshot_tool_settings(context: bpy.types.Context) -> dict[str, object]:
    """The values `_wanted_settings` is about to overwrite."""
    tool_settings = context.scene.tool_settings
    saved: dict[str, object] = {}
    for key in _SNAPSHOT_KEYS:
        if hasattr(tool_settings, key):
            saved[key] = _jsonable(getattr(tool_settings, key))
    return saved


def apply_tool_settings(
    context: bpy.types.Context, values: dict[str, object]
) -> None:
    tool_settings = context.scene.tool_settings
    for key, value in values.items():
        if not hasattr(tool_settings, key):
            continue
        try:
            setattr(tool_settings, key, _from_jsonable(value))
        except (TypeError, ValueError):
            # An enum item this Blender doesn't have (FACE_NEAREST before 4.0,
            # say). Better a mode with one fewer snap target than a session
            # that refuses to open one.
            pass


def _session_source(context: bpy.types.Context) -> bpy.types.Object | None:
    """The object whose retopology Tab should open.

    The session's own while one is entered. In the `OBJECT` phase there is none
    -- the session is between objects -- and Tab there used to fall through to
    Blender, which put the CAD *source* into Edit Mode: the one mesh nothing in
    this addon ever wants edited by hand. So the selection answers instead,
    resolved the way `operators.resolve_session_object` resolves it (pointing
    at `<X>_Retop` means X), and the active object is asked before the rest of
    the selection because that is what "the object I am looking at" means.
    """
    state = context.scene.plasticity_retop
    entered = bpy.data.objects.get(state.session_object_name)
    if entered is not None:
        return entered

    candidates = [context.view_layer.objects.active]
    candidates += [obj for obj in context.selected_objects]
    for obj in candidates:
        if obj is None:
            continue
        source = mesh_build.source_object_for_result(obj) or obj
        if bpy.data.objects.get(mesh_build.result_object_name_for(source)):
            return source
    return None


def _result_object_for_session(
    context: bpy.types.Context,
) -> tuple[bpy.types.Object | None, bpy.types.Object | None, str | None]:
    """(source, result, error). Both objects or an error, never a mix."""
    source = _session_source(context)
    if source is None:
        return None, None, "Select the object whose retopology you want to edit"
    result = bpy.data.objects.get(mesh_build.result_object_name_for(source))
    if result is None or len(result.data.polygons) == 0:
        return source, None, (f"Nothing to hand-edit yet: '{source.name}' has no "
                              f"committed patch")
    return source, result, None


def can_tweak(context: bpy.types.Context) -> str | None:
    """The reason Tab would refuse right now, or None if it would open.

    Used by the panel as well as the modal, so the button and the key give the
    same answer instead of one of them silently doing nothing.
    """
    state = context.scene.plasticity_retop
    if not state.session_active:
        return "No retop session is running"
    if state.session_phase not in ('PATCH', 'OBJECT'):
        # ADJUST owns Tab (it is U/V there) and a patch is open on the result
        # mesh: a re-edit has its faces *out* of it with only a snapshot to put
        # them back, and anything written to a mesh Blender holds in Edit Mode
        # is discarded on exit. TWEAK is already inside the trip.
        return "Commit or discard the patch first"
    if context.mode != 'OBJECT':
        return "Blender is not in Object Mode"
    _source, _result, error = _result_object_for_session(context)
    return error


def enter_tweak(context: bpy.types.Context) -> str | None:
    """Open Edit Mode on the session's result mesh. Returns an error message
    when it could not, else None (and the phase is left on 'TWEAK').

    Creates no datablock, so it is safe between undo steps: the result mesh is
    already there -- having geometry to correct is the precondition -- and
    Blender pushes its own step for the mode change.
    """
    state = context.scene.plasticity_retop
    if context.mode != 'OBJECT':
        return "Blender is not in Object Mode"

    source, result, error = _result_object_for_session(context)
    if error is not None or result is None:
        return error

    # A result mesh hidden behind Local View or an outliner eye can't be
    # entered, and "the operator failed" is a poor answer to "let me fix this
    # vertex". Per-view-layer flags only: no ID is touched.
    result.hide_viewport = False
    try:
        result.hide_set(False)
    except RuntimeError:
        pass  # not in this view layer; the select below reports it properly

    # The preview holds the last hovered patch. Empty it before opening Edit
    # Mode, so what you land in is the committed mesh and nothing else -- an
    # orange grid floating over the thing you came to fix is worse than no
    # preview at all, and the session is not adjusting anything here.
    mesh_build.clear_preview_object()

    previous_active = context.view_layer.objects.active
    state.tweak_return_object = previous_active.name if previous_active else ""

    for obj in list(context.selected_objects):
        obj.select_set(False)
    try:
        result.select_set(True)
    except RuntimeError:
        return f"'{result.name}' is not in the current view layer"
    context.view_layer.objects.active = result

    # Which object this trip is about, and where to go back to. In the OBJECT
    # phase neither is derivable afterwards: the session holds no object, and
    # `repair_manual_edits` -- the whole reason Tab is ours rather than
    # Blender's -- needs one to re-adopt the faces a knife cut left untracked.
    state.tweak_source_object = source.name
    state.tweak_return_phase = state.session_phase

    state.tweak_saved_tool_settings = json.dumps(snapshot_tool_settings(context))
    apply_tool_settings(context, _wanted_settings(state))

    # Draw the retopology over the CAD surface for the trip. Set here, on the
    # object, rather than through refresh_result_appearance: that one also
    # assigns materials, which writes to mesh data, and by the time this
    # matters Blender owns the mesh in Edit Mode. `refresh_result_appearance`
    # knows about the TWEAK phase too, so a redraw triggered mid-edit by some
    # other setting agrees with this instead of undoing it.
    if state.tweak_draw_in_front:
        result.show_in_front = True

    try:
        bpy.ops.object.mode_set(mode='EDIT')
    except RuntimeError as exc:
        restore_tool_settings(context)
        return f"Could not enter Edit Mode: {exc}"

    state.session_phase = 'TWEAK'
    return None


def restore_tool_settings(context: bpy.types.Context) -> None:
    """Put back whatever `enter_tweak` overwrote, and forget the snapshot.

    Separate from `exit_tweak` because entering can fail *after* the settings
    were applied, and leaving a user's snapping configuration rewritten by a
    mode that never opened is the rudest possible failure.
    """
    state = context.scene.plasticity_retop
    raw = state.tweak_saved_tool_settings
    state.tweak_saved_tool_settings = ""
    if not raw:
        return
    try:
        saved = json.loads(raw)
    except ValueError:
        return
    apply_tool_settings(context, saved)


def exit_tweak(context: bpy.types.Context) -> tuple[int, int]:
    """Leave Edit Mode, restore the tool settings and repair the bookkeeping
    the hand edits invalidated. Returns (faces adopted, source ids cleared).

    Safe to call when Blender has already left Edit Mode by another route --
    the mode dropdown, an undo, a script -- which is exactly why the modal
    calls it from its timer as well as from Tab: the repair has to happen once
    per round trip, whichever way the trip ended.
    """
    state = context.scene.plasticity_retop
    if context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass

    restore_tool_settings(context)

    repaired = (0, 0)
    source = (bpy.data.objects.get(state.tweak_source_object)
              or bpy.data.objects.get(state.session_object_name))
    state.tweak_source_object = ""
    if source is not None:
        repaired = mesh_build.repair_manual_edits(context, source)

    # Back to the object the session is about, so the panel keeps describing
    # the same thing and a second Tab opens the same round trip again.
    returning = bpy.data.objects.get(state.tweak_return_object) or source
    state.tweak_return_object = ""
    if returning is not None:
        try:
            returning.select_set(True)
            context.view_layer.objects.active = returning
        except RuntimeError:
            pass

    # Back to the phase the trip started from: a Tab taken in the OBJECT phase
    # was never a choice of object, so landing in PATCH would claim the session
    # had entered one.
    state.session_phase = state.tweak_return_phase or 'PATCH'
    state.tweak_return_phase = ""
    # Back in Object Mode, so this is free to touch materials again: it puts
    # `show_in_front` back under `result_see_through`, where it belongs outside
    # a hand-edit.
    mesh_build.refresh_result_appearance(context)
    return repaired
