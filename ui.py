import json
from typing import TYPE_CHECKING

import bpy

from . import constants
from . import keymap
from . import mesh_build
from . import operators
from . import sidematch
from . import version

if TYPE_CHECKING:
    from . import state as state_mod


def _section(
    layout: bpy.types.UILayout,
    state: "state_mod.RetopPatchState",
    prop_name: str,
    label: str,
    icon: str = 'NONE',
) -> bpy.types.UILayout | None:
    """Collapsible section header. Returns the body layout when open, else None."""
    box = layout.box()
    header = box.row(align=True)
    header.prop(
        state, prop_name, text="", emboss=False,
        icon='TRIA_DOWN' if getattr(state, prop_name) else 'TRIA_RIGHT',
    )
    header.label(text=label, icon=icon)
    return box if getattr(state, prop_name) else None


def _draw_session(
    layout: bpy.types.UILayout,
    context: bpy.types.Context,
    state: "state_mod.RetopPatchState",
) -> None:
    """Session control: start/stop, current phase, and where commits land."""
    box = layout.box()
    stale = state.session_active and not operators.session_is_running()

    if stale:
        # Scene says "in session" but no modal is listening (addon reloaded
        # or the modal was interrupted): clicks and Esc would do nothing.
        col = box.column()
        col.alert = True
        col.label(text="Session interrupted", icon='ERROR')
        col.label(text="The viewport is not listening anymore.")
        box.operator("retop.end_session", text="Reset Session State", icon='X')
        box.operator("retop.session", text="Start Retop Session", icon='PLAY')
        return

    if not state.session_active:
        if context.mode != 'OBJECT':
            # The operator's poll already greys the button out; without this
            # the panel offers a dead button and no reason for it.
            col = box.column(align=True)
            col.label(text=f"Leave {context.mode.replace('_', ' ').title()} to start",
                      icon='INFO')
            col.enabled = True
        box.operator("retop.session", text="Start Retop Session", icon='PLAY')
        box.label(text="Click an object, then its surfaces", icon='INFO')
        return

    if state.session_phase == 'TWEAK':
        # Before the mode check below: Blender *is* in Edit Mode here, and it
        # is there because the session put it there. Saying "paused" would be
        # exactly backwards.
        col = box.column(align=True)
        col.label(text="Hand-editing", icon='EDITMODE_HLT')
        col.label(text=f"In: {state.session_object_name}")
        col.label(text="K knife · Ctrl+R loop · J connect · G move")
        box.operator("retop.end_tweak",
                     text=f"Back to Retop ({keymap.describe('end_tweak')})",
                     icon='LOOP_BACK')
        _draw_tweak_settings(box.column(align=True), state)
        return

    if context.mode != 'OBJECT':
        # The modal hands every event back in another mode, so the session is
        # doing nothing at all until Blender returns to Object Mode.
        paused = box.column(align=True)
        paused.label(text=f"Paused — Blender is in {context.mode.replace('_', ' ').title()}",
                     icon='INFO')
        paused.label(text="Back in Object Mode, pick an object again.")
        box.operator("retop.end_session", text="Stop Session", icon='X')
        return

    phase = state.session_phase
    if phase == 'OBJECT':
        box.label(text="Pick an object", icon='EYEDROPPER')
        box.label(text="Click a Plasticity object in the viewport")
    elif phase == 'PATCH':
        box.label(text="Pick a surface", icon='RESTRICT_SELECT_OFF')
        # Offered here and nowhere else, for the same reason Tab is bound here
        # and nowhere else: a patch open for adjustment has its faces out of
        # the result mesh, and Edit Mode would discard the snapshot that puts
        # them back.
        box.operator("retop.tweak_mesh",
                     text=f"Hand-Edit Mesh ({keymap.describe('hand_edit')})",
                     icon='EDITMODE_HLT')
        box.label(text=f"In: {state.session_object_name}")
        session_obj = bpy.data.objects.get(state.session_object_name)
        if session_obj is not None:
            # Which mesh commits actually land in, and what's already in it: if
            # a retopology is visible in the viewport but this says 0 faces, it
            # belongs to a *different* result object (e.g. the source was
            # renamed/re-imported since) and can't be re-edited from here.
            result = bpy.data.objects.get(mesh_build.result_object_name_for(session_obj))
            if result is not None:
                done = state.committed_patch_count
                box.label(text=f"→ {result.name}: {len(result.data.polygons)} faces, "
                               f"{done} patch(es)", icon='OUTLINER_OB_MESH')
                if done:
                    box.label(text="Click a done patch to re-edit it", icon='FILE_REFRESH')
        box.label(text=f"{keymap.describe('back')}: leave this object")
    else:
        box.label(text="Adjust & commit", icon='TOOL_SETTINGS')
        box.label(text=f"In: {state.session_object_name}")
    box.operator("retop.end_session", text="Stop Session", icon='X')


def _draw_warnings(
    layout: bpy.types.UILayout,
    context: bpy.types.Context,
    obj: bpy.types.Object | None,
) -> None:
    """Conditions that make retopology silently wrong. Drawn on every tab: they
    only ever appear when something is actually broken.
    """
    # A result mesh whose source object is gone can't be re-edited: commits
    # for the renamed/re-imported object go to a new one, and the two show up
    # as overlapping surfaces.
    orphans = mesh_build.orphan_result_objects(context)
    if orphans:
        warn = layout.box().column(align=True)
        warn.alert = True
        warn.label(text="Retopology with no source object", icon='ERROR')
        for orphan in orphans[:4]:
            missing = orphan.name[:-len(mesh_build.RESULT_NAME_SUFFIX)]
            warn.label(text=f"{orphan.name} — '{missing}' is gone")
        warn.label(text="Rename it to <YourObject>_Retop to re-edit it.")

    # In a hand-edit the active object *is* the result mesh, on purpose. The
    # "this is the retopology of X, start a session on X" box below would be
    # answering a question nobody asked.
    if context.scene.plasticity_retop.session_phase == 'TWEAK':
        return

    if obj is None or obj.type != 'MESH' or obj.data.get("face_ids"):
        return

    # Selecting the retopology and finding "no Plasticity face data" is a
    # non-answer: it never has any, and what the user means is the object it
    # was built from. Say so, and offer that.
    source = mesh_build.source_object_for_result(obj)
    if source is not None:
        info = layout.box().column(align=True)
        info.label(text=f"Retopology of '{source.name}'", icon='OUTLINER_OB_MESH')
        info.operator("retop.session", text=f"Retop {source.name}", icon='PLAY')
        return

    # Patch data lives in the mesh itself (mesh["face_ids"]/["groups"]), written
    # at import time -- the Plasticity bridge does NOT need to stay connected
    # afterwards. A mesh without it simply can't be retopped.
    warn = layout.box().column()
    warn.alert = True
    warn.label(text=f"'{obj.name}' has no Plasticity face data", icon='ERROR')
    warn.label(text="Re-import it through the bridge.")


def _draw_active_patch(
    layout: bpy.types.UILayout, state: "state_mod.RetopPatchState"
) -> None:
    """The picked patch and its spans. Drawn above the tabs, not inside one:
    losing the span controls because you switched to the Display tab in the
    middle of an adjustment would be the panel fighting the workflow.
    """
    box = layout.box()
    if state.generator_name == constants.RING:
        box.label(text=f"Face {state.active_face_id} — Ring "
                       f"(2 loops, {state.num_sides} corners)")
    else:
        box.label(text=f"Face {state.active_face_id} — {state.generator_name} "
                       f"({state.num_sides} sides)")

    if state.generator_note:
        box.label(text=state.generator_note, icon='INFO')

    if state.corner_warning:
        warn = box.column(align=True)
        warn.alert = True
        warn.label(text="Corner detection is unsure here", icon='ERROR')
        warn.label(text=state.corner_warning)

    if state.num_loops > 2:
        # More than one hole: the band generator handles two loops, not three,
        # so only the outer boundary was used and the holes are covered over.
        warn = box.column(align=True)
        warn.alert = True
        warn.label(text=f"{state.num_loops} boundary loops — holes ignored", icon='ERROR')
        warn.label(text="Split the face in Plasticity to retop it.")

    if state.editing_committed:
        # Re-edit: the old patch has already been taken out of the result mesh,
        # and Discard puts it back untouched.
        info = box.column(align=True)
        info.label(text="Re-editing a committed patch", icon='FILE_REFRESH')
        if state.reedit_removed_faces:
            info.label(text=f"Old patch removed ({state.reedit_removed_faces} faces)")
            info.label(text="Discard restores it. Neighbours keep their spans.")
            delete = box.row(align=True)
            delete.alert = True
            delete.operator("retop.delete_patch", text="Delete Patch (X)", icon='TRASH')
        else:
            # Nothing was found to remove: committing would leave the old
            # geometry in place, overlapping the new grid.
            info.alert = True
            info.label(text="Could not find its old faces to remove", icon='ERROR')
            info.label(text="Committing will overlap the existing surface.")

    _draw_match_block(box, state)

    # N-gon is a mode, not a generator the side count selects, so it gets its
    # own toggle here rather than appearing in the list of patch types.
    mode_row = box.row(align=True)
    mode_row.enabled = state.ngon_available or state.ngon_mode
    mode_row.prop(state, "ngon_mode", text="N-gon (N)", toggle=True, icon='MESH_PLANE')
    if not state.ngon_available:
        note = box.column(align=True)
        note.label(text=f"N-gon unavailable: {state.ngon_unavailable_reason}", icon='INFO')

    if state.ngon_mode and state.ngon_available:
        box.prop(state, "ngon_angle")
        if state.num_loops == 2:
            box.label(text="Hole bridged with 2 edges (2 n-gons)", icon='MESH_TORUS')
        box.prop(state, "ngon_show_verts")
        sub_dots = box.column()
        sub_dots.enabled = state.ngon_show_verts
        sub_dots.prop(state, "ngon_vert_size")
        row = box.row(align=True)
        row.operator("retop.commit_patch",
                     text="Replace" if state.editing_committed else "Commit",
                     icon='CHECKMARK')
        row.operator("retop.clear_preview", text="Discard", icon='X')
        return

    col = box.column(align=True)
    if state.generator_name in operators.TWO_SPAN_GENERATORS:
        u_label, v_label = constants.span_labels(state.generator_name)
        col.prop(state, "span_u", text=u_label)
        col.prop(state, "span_v", text=v_label)
        row = box.row(align=True)
        row.label(text="Ctrl+wheel/keys adjust:")
        row.prop(state, "span_axis", expand=True)
    else:
        col.prop(state, "span")

    box.prop(state, "reproject")

    row = box.row(align=True)
    row.operator("retop.commit_patch",
                 text="Replace" if state.editing_committed else "Commit",
                 icon='CHECKMARK')
    row.operator("retop.clear_preview", text="Discard", icon='X')


def _draw_match_block(
    box: bpy.types.UILayout, state: "state_mod.RetopPatchState"
) -> None:
    """Matching a committed neighbour's density along a shared side."""
    references = sidematch.active_sides()
    available = [reference for reference in references if reference.available]

    row = box.row(align=True)
    row.operator("retop.toggle_match_mode",
                 text=f"Side Highlight ({keymap.describe('match_mode')})",
                 icon='SNAP_EDGE', depress=state.match_mode)
    if not references:
        return

    hovered = None
    if 0 <= state.hovered_side < len(references):
        hovered = references[state.hovered_side]
    if hovered is not None and not hovered.available:
        # Say it here as well as in the viewport: the reason is the actionable
        # half, and a status-bar warning only shows up after a failed click.
        note = box.column(align=True)
        note.alert = True
        note.label(text=f"This side: {hovered.reason}", icon='ERROR')

    if not available:
        box.label(text="No side borders a committed patch", icon='INFO')
    elif state.match_mode:
        box.label(text=f"Click a green side to match it ({len(available)} of "
                       f"{len(references)})", icon='EYEDROPPER')
    else:
        box.label(text=f"{len(available)} of {len(references)} sides could be matched",
                  icon='INFO')

    if state.match_mode:
        box.label(text="Ctrl+click follows the CAD edge instead", icon='INFO')

    pinned = _pinned_sides(state)
    if pinned:
        box.label(text=f"{len(pinned)} side(s) matched by hand", icon='CHECKMARK')

    if state.match_conflicts and state.generator_name != constants.NGON:
        # A grid has one span per *direction*, so two sides wanting different
        # counts along the same axis cannot both be honoured. Only the winner is
        # substituted; say so, since nothing in the viewport shows which lost.
        note = box.column(align=True)
        note.alert = True
        note.label(text=f"{state.match_conflicts} side(s) outvoted", icon='ERROR')
        note.label(text="A grid has one span per direction.")


def _pinned_sides(state: "state_mod.RetopPatchState") -> list[str]:
    """Flat side indices the user has matched by hand on this patch."""
    if not state.side_overrides:
        return []
    try:
        return sorted(json.loads(state.side_overrides))
    except ValueError:
        return []


def _draw_matching_settings(
    body: bpy.types.UILayout, state: "state_mod.RetopPatchState"
) -> None:
    body.prop(state, "auto_match_neighbours")
    body.label(text="Applies to every generator", icon='INFO')
    body.prop(state, "match_margin")
    body.label(text="Only sides you point at use it", icon='INFO')


def _draw_tweak_settings(
    body: bpy.types.UILayout, state: "state_mod.RetopPatchState"
) -> None:
    """How the hand-edit round trip sets Blender's tool settings up.

    Read on the way *in*, so changing one mid-edit does nothing until the next
    trip -- said in the panel rather than left to be discovered.
    """
    body.separator()
    body.label(text="Hand-Edit Setup", icon='SNAP_VERTEX')
    body.prop(state, "tweak_auto_merge")
    body.prop(state, "tweak_merge_distance")
    body.prop(state, "tweak_snap_surface")
    body.label(text="Applied when Edit Mode opens", icon='INFO')


def _draw_tab_patch(
    layout: bpy.types.UILayout, state: "state_mod.RetopPatchState"
) -> None:
    body = _section(layout, state, "show_patch_settings",
                    "Patch Settings", icon='MOD_MESHDEFORM')
    if body:
        _draw_patch_settings(body.column(), state)

    body = _section(layout, state, "show_ngon_settings", "N-gon Mode", icon='MESH_PLANE')
    if body:
        _draw_ngon_settings(body.column(), state)


def _draw_patch_settings(
    body: bpy.types.UILayout, state: "state_mod.RetopPatchState"
) -> None:
    body.label(text="Starting Resolution")
    body.row(align=True).prop(state, "resolution", expand=True)
    body.label(text="Scales the computed span count", icon='INFO')
    body.separator()
    body.label(text="Corner Detection")
    col = body.column(align=True)
    col.label(text="Grid generators:")
    col.row(align=True).prop(state, "corner_method_spans", expand=True)
    col.separator()
    col.label(text="N-gon mode:")
    col.row(align=True).prop(state, "corner_method_ngon", expand=True)
    if 'TOPOLOGY' in (state.corner_method_spans, state.corner_method_ngon):
        body.label(text="Falls back to angle if no junction", icon='INFO')
    sub_angle = body.column()
    sub_angle.enabled = 'ANGLE' in (state.corner_method_spans, state.corner_method_ngon) \
        or 'BOTH' in (state.corner_method_spans, state.corner_method_ngon)
    sub_angle.prop(state, "corner_angle_threshold")
    body.prop(state, "small_side_tolerance")
    body.prop(state, "boundary_weld_distance")


def _draw_ngon_settings(
    body: bpy.types.UILayout, state: "state_mod.RetopPatchState"
) -> None:
    body.prop(state, "ngon_mode", text="N-gon by default")
    body.prop(state, "ngon_angle")
    body.prop(state, "ngon_planar_tolerance")
    body.separator()
    body.prop(state, "ngon_show_verts")
    sub_dots = body.column()
    sub_dots.enabled = state.ngon_show_verts
    sub_dots.prop(state, "ngon_vert_size")
    body.separator()
    body.label(text="N toggles it during a session", icon='INFO')
    body.label(text="Flat faces only; one hole is bridged", icon='INFO')


def _draw_tab_picker(
    layout: bpy.types.UILayout, state: "state_mod.RetopPatchState"
) -> None:
    body = layout.box().column()
    body.label(text="Picker Settings", icon='RESTRICT_SELECT_OFF')
    body.separator()
    body.prop(state, "length_unit")
    body.separator()
    body.label(text="Matching", icon='SNAP_EDGE')
    _draw_matching_settings(body, state)
    body.separator()
    body.prop(state, "pick_depth_tolerance")
    body.prop(state, "pick_max_distance")
    # Filed here rather than under Patch: this is the manual half of matching
    # -- what you reach for when a side could not be matched automatically.
    _draw_tweak_settings(body, state)


def _draw_tab_display(
    layout: bpy.types.UILayout,
    state: "state_mod.RetopPatchState",
    obj: bpy.types.Object | None,
) -> None:
    body = _section(layout, state, "show_preview_appearance",
                    "Preview Appearance", icon='SHADING_RENDERED')
    if body:
        body.prop(state, "preview_color")
        body.prop(state, "preview_alpha", slider=True)
        body.prop(state, "preview_offset", text="Extra Offset")
        note = body.column()
        note.label(text="Follows Result Offset; adds to it", icon='INFO')
        note.enabled = False

    result_obj = None
    if obj is not None and obj.type == 'MESH':
        result_obj = bpy.data.objects.get(mesh_build.result_object_name_for(obj))
    body = _section(layout, state, "show_result_appearance",
                    "Result Appearance", icon='SHADING_SOLID')
    if body:
        if result_obj is not None:
            body.label(text=result_obj.name, icon='OUTLINER_OB_MESH')
        body.prop(state, "result_color")
        body.prop(state, "result_alpha", slider=True)
        body.prop(state, "result_offset")
        body.separator()
        body.prop(state, "result_see_through")
        body.prop(state, "result_show_wire")
        sub_wire = body.column()
        sub_wire.label(text="Shown while a session runs", icon='INFO')
        sub_wire.enabled = state.result_show_wire
        sub_wire.prop(state, "result_wire_opacity", slider=True)
        # Blender has no per-object wireframe opacity: this drives the
        # viewport's own overlay setting, so say so rather than let it look
        # like a per-object one.
        sub_wire.label(text="Viewport overlay: affects all wireframes", icon='INFO')
        body.separator()
        body.prop(state, "highlight_all_results")
        sub = body.row()
        sub.enabled = state.highlight_all_results
        sub.prop(state, "inactive_result_alpha", slider=True)

    _draw_cad_display(layout, state)

    box = layout.box().column()
    box.label(text="Keybind Overlay", icon='EVENT_A')
    box.prop(state, "overlay_scale")

    box = layout.box().column()
    box.label(text="Isolate  ( / )", icon='ZOOM_SELECTED')
    box.prop(state, "local_view_include_retop")
    if state.local_view_include_retop:
        box.label(text="Isolating also shows <Object>_Retop", icon='INFO')


def _draw_cad_display(
    layout: bpy.types.UILayout, state: "state_mod.RetopPatchState"
) -> None:
    """The Plasticity structure drawn over the source surface.

    Its own block rather than a line inside Preview Appearance: this describes
    the *CAD model*, not the retopology, and it is the one display you turn on
    before picking anything.
    """
    box = layout.box().column()
    box.label(text="Plasticity Structure", icon='MOD_WIREFRAME')
    box.separator()

    box.prop(state, "show_cad_edges", text="CAD Edges (E)", toggle=False)
    sub_edges = box.column(align=True)
    sub_edges.enabled = state.show_cad_edges
    sub_edges.prop(state, "cad_edge_color", text="")
    sub_edges.prop(state, "cad_edge_width")
    sub_edges.prop(state, "show_brep_vertices")

    box.separator()
    box.prop(state, "show_surface_flow", text="Surface Flow (Ctrl+E)")
    sub_flow = box.column(align=True)
    sub_flow.enabled = state.show_surface_flow
    sub_flow.prop(state, "flow_color", text="")
    sub_flow.prop(state, "flow_density")
    # Say what it is, plainly: the bridge carries no surface parameters, so
    # these are not Plasticity's isoparms and should not be read as them.
    sub_flow.label(text="Derived from each face's boundary,", icon='INFO')
    sub_flow.label(text="not Plasticity's own isoparms.")

    box.separator()
    box.prop(state, "cad_display_xray")
    if not state.cad_display_xray:
        box.label(text="B-rep dots still draw on top", icon='INFO')

    box.separator()
    box.label(text="Show for:")
    box.row(align=True).prop(state, "cad_display_scope", expand=True)
    box.label(text="Drawn while a session runs", icon='INFO')


def _draw_mirror(
    layout: bpy.types.UILayout,
    context: bpy.types.Context,
    state: "state_mod.RetopPatchState",
) -> None:
    """Symmetry on the committed mesh.

    Which axes are on is read off the Mirror modifier rather than a scene
    property: they belong to one object. So this block describes whatever
    object the session (or the selection) currently resolves to, and says which
    one that is.
    """
    body = layout.box().column()
    body.label(text="Mirror", icon='MOD_MIRROR')
    body.separator()

    source, result = mesh_build.mirror_target(context)
    if result is None:
        body.label(text="Nothing committed to mirror yet", icon='INFO')
        if source is not None:
            body.label(text=f"Would apply to: {source.name}")
        return

    body.label(text=f"On: {result.name}")
    axes = mesh_build.mirror_axes(result)
    row = body.row(align=True)
    for axis, enabled in zip(mesh_build.MIRROR_AXES, axes):
        # depress, not a checkbox: these are operator buttons, and the pressed
        # look is the only way to show state on one.
        row.operator("retop.mirror_axis", text=axis, depress=enabled).axis = axis
    body.label(text=f"{keymap.describe('mirror')}, then X / Y / Z", icon='EVENT_A')

    if not any(axes):
        return

    body.separator()
    body.prop(state, "mirror_clip")
    body.prop(state, "mirror_merge_distance")
    # The one thing worth a line: the mirrored half is a modifier, so it can't
    # be picked or re-edited until it is applied.
    body.label(text="Mirrored half is a modifier", icon='INFO')
    body.operator("retop.apply_mirror", text="Apply Mirror", icon='CHECKMARK')


def _draw_tab_output(
    layout: bpy.types.UILayout,
    context: bpy.types.Context,
    state: "state_mod.RetopPatchState",
) -> None:
    _draw_mirror(layout, context, state)

    body = layout.box().column()
    body.label(text="Shading", icon='SHADING_SOLID')
    body.separator()
    body.prop(state, "result_shade_smooth")
    sub_sharp = body.column()
    sub_sharp.enabled = state.result_shade_smooth
    sub_sharp.prop(state, "sharp_edge_angle")
    sub_sharp.label(text="Creases patch borders only", icon='INFO')

    body = layout.box().column()
    body.label(text="Collections", icon='OUTLINER_COLLECTION')
    body.separator()
    body.prop(state, "mirror_source_collections")
    if state.mirror_source_collections:
        body.label(text="Mirrors the path below Inbox", icon='INFO')


def _draw_tab_keys(
    layout: bpy.types.UILayout, state: "state_mod.RetopPatchState"
) -> None:
    """Where the keys are, not the keys themselves.

    The keys are real KeyMapItems, so the widget that edits them already exists: Blender's
    own rows, on the addon's preferences page. This tab points at it and then
    lists only what is *not* remappable, which is the part no editor would
    show.
    """
    box = layout.box().column(align=True)
    box.label(text="Keybinds", icon='EVENT_A')
    box.separator()
    box.operator("retop.open_keymap_prefs", text="Edit Keybinds…",
                 icon='PREFERENCES')
    box.label(text="Also: Preferences > Keymap > Add-ons")
    box.separator()
    # Which keys are live when is the first thing anyone asks after a key of
    # theirs stops working, so it is said here rather than only in the manual.
    box.label(text="Keys are live only during a session", icon='INFO')
    box.label(text="Outside one they fall through to Blender")
    box.label(text="and to other addons (Hard Ops' Alt+X)")


def _draw_tab_system(layout: bpy.types.UILayout) -> None:
    body = layout.box().column()
    body.label(text="System", icon='PREFERENCES')
    body.separator()
    body.label(text=f"Version {version.ADDON_VERSION}")
    body.label(text=f"Build {version.BUILD_ID}")
    body.separator()
    # "Reload Addon Only" first: plain Reload Scripts can silently half-fail
    # when another installed addon errors during its own reload.
    body.operator("retop.reload_addon", text="Reload Addon Only", icon='FILE_REFRESH')
    body.operator("script.reload", text="Reload Scripts", icon='BLENDER')


class VIEW3D_PT_retop(bpy.types.Panel):
    bl_label = "Retop"
    bl_idname = "VIEW3D_PT_retop"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Retop"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        state = context.scene.plasticity_retop
        obj = context.active_object

        # Version stays visible on every tab: it's the only reliable way to
        # tell whether a deploy/reload actually took.
        layout.label(text=f"v{version.ADDON_VERSION}  ·  build {version.BUILD_ID}",
                     icon='EXPERIMENTAL')

        # ... and this is the other half of that: the line above is what Python
        # holds in memory, which a deploy does not change. Without saying so,
        # running yesterday's code looks exactly like a broken feature -- and
        # the tracebacks it produces point at line numbers that don't match the
        # file you're reading.
        stale = version.stale_load()
        if stale:
            warn = layout.box().column(align=True)
            warn.alert = True
            warn.label(text="Running older code than is deployed", icon='ERROR')
            warn.label(text=f"On disk: v{stale[0]} · build {stale[1]}")
            warn.operator("retop.reload_addon", text="Reload Addon Only",
                          icon='FILE_REFRESH')
            warn.label(text="If this stays, restart Blender.")

        # --- always on: what the session is doing right now ---
        _draw_session(layout, context, state)
        _draw_warnings(layout, context, obj)
        # The active patch never moves into a tab: losing the span controls
        # because you switched tabs mid-adjustment would fight the workflow.
        if state.active_face_id != -1:
            _draw_active_patch(layout, state)

        # --- settings, one tab at a time ---
        layout.separator()
        row = layout.row(align=True)
        row.scale_x = 1.4
        row.scale_y = 1.4
        row.prop(state, "ui_tab", expand=True, icon_only=True)

        tab = state.ui_tab
        if tab == 'PATCH':
            _draw_tab_patch(layout, state)
        elif tab == 'PICKER':
            _draw_tab_picker(layout, state)
        elif tab == 'DISPLAY':
            _draw_tab_display(layout, state, obj)
        elif tab == 'OUTPUT':
            _draw_tab_output(layout, context, state)
        elif tab == 'KEYS':
            _draw_tab_keys(layout, state)
        elif tab == 'SYSTEM':
            _draw_tab_system(layout)


CLASSES = (VIEW3D_PT_retop,)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
