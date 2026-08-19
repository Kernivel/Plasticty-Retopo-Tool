import bpy

from . import mesh_build
from . import operators
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

        header = layout.row()
        header.label(text=f"v{version.ADDON_VERSION}  ·  build {version.BUILD_ID}", icon='EXPERIMENTAL')

        # --- session ---
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
        elif not state.session_active:
            box.operator("retop.session", text="Start Retop Session", icon='PLAY')
            box.label(text="Click an object, then its surfaces", icon='INFO')
        else:
            phase = state.session_phase
            if phase == 'OBJECT':
                box.label(text="Pick an object", icon='EYEDROPPER')
                box.label(text="Click a Plasticity object in the viewport")
            elif phase == 'PATCH':
                box.label(text="Pick a surface", icon='RESTRICT_SELECT_OFF')
                box.label(text=f"In: {state.session_object_name}")
                session_obj = bpy.data.objects.get(state.session_object_name)
                if session_obj is not None:
                    # Which mesh commits actually land in, and what's already in
                    # it: if a retopology is visible in the viewport but this
                    # says 0 faces, it belongs to a *different* result object
                    # (e.g. the source was renamed/re-imported since) and can't
                    # be re-edited from here.
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

        # Patch data lives in the mesh itself (mesh["face_ids"]/["groups"]),
        # written at import time -- the Plasticity bridge does NOT need to stay
        # connected afterwards. A mesh without it simply can't be retopped.
        if obj is not None and obj.type == 'MESH' and not obj.data.get("face_ids"):
            warn = layout.box().column()
            warn.alert = True
            warn.label(text=f"'{obj.name}' has no Plasticity face data", icon='ERROR')
            warn.label(text="Re-import it through the bridge.")

        if state.active_face_id != -1:
            box = layout.box()
            if state.generator_name == "Ring":
                box.label(text=f"Face {state.active_face_id} — Ring "
                               f"(2 loops, {state.num_sides} corners)")
            else:
                box.label(text=f"Face {state.active_face_id} — {state.generator_name} "
                               f"({state.num_sides} sides)")

            if state.num_loops > 2:
                # More than one hole: the band generator handles two loops, not
                # three, so only the outer boundary was used and the holes are
                # simply covered over.
                warn = box.column(align=True)
                warn.alert = True
                warn.label(text=f"{state.num_loops} boundary loops — holes ignored", icon='ERROR')
                warn.label(text="Split the face in Plasticity to retop it.")

            if state.editing_committed:
                # Re-edit: the old patch has already been taken out of the
                # result mesh, and Discard puts it back untouched.
                info = box.column(align=True)
                info.label(text="Re-editing a committed patch", icon='FILE_REFRESH')
                if state.reedit_removed_faces:
                    info.label(text=f"Old patch removed ({state.reedit_removed_faces} faces)")
                    info.label(text="Discard restores it. Neighbours keep their spans.")
                else:
                    # Nothing was found to remove: committing would leave the old
                    # geometry in place, overlapping the new grid.
                    info.alert = True
                    info.label(text="Could not find its old faces to remove", icon='ERROR')
                    info.label(text="Committing will overlap the existing surface.")

            col = box.column(align=True)
            if state.generator_name in operators.TWO_SPAN_GENERATORS:
                u_label, v_label = {
                    "Quad": ("Span U", "Span V"),
                    "Ring": ("Span (around)", "Span (across)"),
                }.get(state.generator_name, ("Span (along)", "Span (across)"))
                col.prop(state, "span_u", text=u_label)
                col.prop(state, "span_v", text=v_label)
                row = box.row(align=True)
                row.label(text="Ctrl+wheel/keys adjust:")
                row.prop(state, "span_axis", expand=True)
            else:
                col.prop(state, "span")

            box.prop(state, "reproject")
            box.operator("retop.update_preview", text="Update Preview", icon='FILE_REFRESH')

            row = box.row(align=True)
            row.operator("retop.commit_patch",
                         text="Replace" if state.editing_committed else "Commit",
                         icon='CHECKMARK')
            row.operator("retop.clear_preview", text="Discard", icon='X')

        body = _section(layout, state, "show_keybinds", "Keybinds", icon='EVENT_A')
        if body:
            col = body.column(align=True)
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
                    ("Right click", "Commit"),
                    ("Enter", "Commit"),
                    ("Esc", "Clear typing, then discard"),
                ]),
            ):
                col.label(text=phase_label + ":")
                for key, action in binds:
                    row = col.row()
                    row.label(text=f"      {key}")
                    row.label(text=action)
                col.separator()

        body = _section(layout, state, "show_patch_settings", "Patch Settings", icon='MOD_MESHDEFORM')
        if body:
            body.prop(state, "corner_angle_threshold")
            body.prop(state, "small_side_tolerance")
            body.prop(state, "boundary_weld_distance")

        body = _section(layout, state, "show_picker_settings", "Picker Settings", icon='RESTRICT_SELECT_OFF')
        if body:
            body.prop(state, "length_unit")
            body.prop(state, "pick_depth_tolerance")
            body.prop(state, "pick_max_distance")

        body = _section(layout, state, "show_preview_appearance", "Preview Appearance", icon='SHADING_RENDERED')
        if body:
            body.prop(state, "preview_color")
            body.prop(state, "preview_alpha", slider=True)
            body.prop(state, "preview_offset")

        result_obj = None
        if obj is not None and obj.type == 'MESH':
            result_obj = bpy.data.objects.get(mesh_build.result_object_name_for(obj))
        body = _section(layout, state, "show_result_appearance", "Result Appearance", icon='SHADING_SOLID')
        if body:
            if result_obj is not None:
                body.label(text=result_obj.name, icon='OUTLINER_OB_MESH')
            body.prop(state, "result_color")
            body.prop(state, "result_alpha", slider=True)
            body.prop(state, "result_offset")
            body.separator()
            body.prop(state, "highlight_all_results")
            sub = body.row()
            sub.enabled = state.highlight_all_results
            sub.prop(state, "inactive_result_alpha", slider=True)

        layout.separator()
        reload_row = layout.row(align=True)
        reload_row.operator("retop.reload_addon", text="Reload Addon Only", icon='FILE_REFRESH')
        reload_row.operator("script.reload", text="Reload Scripts", icon='BLENDER')


CLASSES = (VIEW3D_PT_retop,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
