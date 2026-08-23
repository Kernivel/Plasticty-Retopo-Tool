import json

import bpy

from . import constants
from . import mesh_build
from . import operators
from . import sidematch
from . import version


def _section(layout, state, prop_name, label, icon='NONE'):
    """Collapsible section header. Returns the body layout when open, else None."""
    box = layout.box()
    header = box.row(align=True)
    header.prop(
        state, prop_name, text="", emboss=False,
        icon='TRIA_DOWN' if getattr(state, prop_name) else 'TRIA_RIGHT',
    )
    header.label(text=label, icon=icon)
    return box if getattr(state, prop_name) else None


def _draw_session(layout, context, state):
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
        box.operator("retop.session", text="Start Retop Session", icon='PLAY')
        box.label(text="Click an object, then its surfaces", icon='INFO')
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
        box.label(text="Esc: leave this object")
    else:
        box.label(text="Adjust & commit", icon='TOOL_SETTINGS')
        box.label(text=f"In: {state.session_object_name}")
    box.operator("retop.end_session", text="Stop Session", icon='X')


def _draw_warnings(layout, context, obj):
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


def _draw_active_patch(layout, state):
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


def _draw_match_block(box, state):
    """Matching a committed neighbour's density along a shared side."""
    references = sidematch.active_sides()
    available = [reference for reference in references if reference.available]

    row = box.row(align=True)
    row.operator("retop.match_neighbour",
                 text="Side Highlight (M)", icon='SNAP_EDGE',
                 depress=state.match_mode)
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


def _pinned_sides(state):
    """Flat side indices the user has matched by hand on this patch."""
    if not state.side_overrides:
        return []
    try:
        return sorted(json.loads(state.side_overrides))
    except ValueError:
        return []


def _draw_matching_settings(body, state):
    body.prop(state, "auto_match_neighbours")
    body.label(text="Applies to every generator", icon='INFO')
    body.prop(state, "match_margin")
    body.label(text="Only sides you point at use it", icon='INFO')


def _draw_tab_patch(layout, state):
    body = _section(layout, state, "show_patch_settings",
                    "Patch Settings", icon='MOD_MESHDEFORM')
    if body:
        _draw_patch_settings(body.column(), state)

    body = _section(layout, state, "show_ngon_settings", "N-gon Mode", icon='MESH_PLANE')
    if body:
        _draw_ngon_settings(body.column(), state)


def _draw_patch_settings(body, state):
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


def _draw_ngon_settings(body, state):
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


def _draw_tab_picker(layout, state):
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


def _draw_tab_display(layout, state, obj):
    body = _section(layout, state, "show_preview_appearance",
                    "Preview Appearance", icon='SHADING_RENDERED')
    if body:
        body.prop(state, "preview_color")
        body.prop(state, "preview_alpha", slider=True)
        body.prop(state, "preview_offset")

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


def _draw_cad_display(layout, state):
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
    box.label(text="Show for:")
    box.row(align=True).prop(state, "cad_display_scope", expand=True)
    box.label(text="Drawn while a session runs", icon='INFO')


def _draw_tab_output(layout, state):
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


def _draw_tab_keys(layout):
    body = layout.box().column(align=True)
    body.label(text="Keybinds", icon='EVENT_A')
    body.separator()
    for phase_label, binds in (
        ("Pick an object", [("Click", "Enter object"), ("Esc", "End session")]),
        ("Pick a surface", [("Click", "Pick surface (again = re-edit)"),
                            ("Esc", "Leave object")]),
        ("Adjust & commit", [
            ("Ctrl+Scroll", "Span +/-"),
            ("0-9", "Type span directly"),
            ("Backspace", "Edit typed span"),
            ("Scroll", "Zoom (unchanged)"),
            ("Tab", "U/V direction (quad/wedge)"),
            ("N", "N-gon mode on/off"),
            ("M", "Side highlight on/off"),
            ("Click", "Match the side under the cursor"),
            ("Ctrl+Click", "Match the CAD edge instead"),
            ("X", "Delete the patch (re-edit only)"),
            ("Right click", "Commit"),
            ("Enter", "Commit"),
            ("Esc", "Clear typing, then discard"),
        ]),
        ("Anytime", [
            ("Slash", "Isolate, retopology included"),
            ("Alt+X", "Retopo through meshes on/off"),
            ("E", "Plasticity edges on/off"),
            ("Ctrl+E", "Surface flow on/off"),
        ]),
    ):
        body.label(text=phase_label + ":")
        for key, action in binds:
            row = body.row()
            row.label(text=f"      {key}")
            row.label(text=action)
        body.separator()


def _draw_tab_system(layout):
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

    def draw(self, context):
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
            _draw_tab_output(layout, state)
        elif tab == 'KEYS':
            _draw_tab_keys(layout)
        elif tab == 'SYSTEM':
            _draw_tab_system(layout)


CLASSES = (VIEW3D_PT_retop,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
