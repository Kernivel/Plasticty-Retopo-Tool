import sys
import bpy
from bpy_extras import view3d_utils

from . import patch_data
from . import sides as sides_mod
from . import geometry
from . import generators
from . import mesh_build
from . import overlay
from . import state as state_mod


def _prepare_patch(mesh, face_id, angle_threshold, small_side_tolerance):
    patches = patch_data.get_patches_with_boundaries(mesh)
    patch = patches.get(face_id)
    if patch is None or not patch.boundary_loops:
        return None, None, None

    positions = {v.index: v.co.copy() for v in mesh.vertices}
    loop = patch.boundary_loops[0]
    side_indices = sides_mod.split_into_sides(loop, positions, angle_threshold=angle_threshold)
    side_indices = sides_mod.merge_small_sides(side_indices, positions, small_side_tolerance)
    side_points = generators.base.resolve_side_points(side_indices, positions)
    # corner k = first vertex of side k, in the same order generators use to
    # fill GenerationResult.corner_local_indices
    corner_source_ids = [side[0] for side in side_indices]
    return patch, side_points, corner_source_ids


def _is_plasticity_mesh(obj):
    return obj is not None and obj.type == 'MESH' and obj.data.get("face_ids")


def _propagated_defaults(obj, generator, corner_source_ids, defaults):
    """Override `defaults` (span_u/span_v or span) with spans already used by
    committed neighboring patches sharing a side (see mesh_build's span
    registry), so adjacent patches naturally weld along their whole shared
    edge instead of only at corners. Returns (defaults, locked_keys) where
    locked_keys names which entries were overridden by propagation.
    """
    n = len(corner_source_ids)

    def side_span(i):
        a = corner_source_ids[i]
        b = corner_source_ids[(i + 1) % n]
        return mesh_build.lookup_propagated_span(obj, a, b)

    locked = []
    if generator.name == "Quad":
        span_u = side_span(0)
        if span_u is None:
            span_u = side_span(2)
        span_v = side_span(1)
        if span_v is None:
            span_v = side_span(3)
        if span_u is not None:
            defaults["span_u"] = span_u
            locked.append("span_u")
        if span_v is not None:
            defaults["span_v"] = span_v
            locked.append("span_v")
    elif generator.name == "Wedge":
        # both sides are linked, so either one determines the span
        span_u = side_span(0)
        if span_u is None:
            span_u = side_span(1)
        if span_u is not None:
            defaults["span_u"] = span_u
            locked.append("span_u")
    else:
        # Triangle / N-Side: one span shared by every side, so the first
        # already-committed neighbour edge decides it.
        for i in range(n):
            span = side_span(i)
            if span is not None:
                defaults["span"] = span
                locked.append("span")
                break

    return defaults, locked


def spans_per_side(state, num_sides):
    """Span used along each side of the active patch, in boundary order --
    what gets recorded for propagation to neighbouring patches.
    """
    if state.generator_name == "Quad":
        return [state.span_u, state.span_v, state.span_u, state.span_v]
    if state.generator_name == "Wedge":
        return [state.span_u] * num_sides
    return [state.span] * num_sides


def _generate_for_face(context, obj, face_id, span_overrides=None):
    """Shared core: prepare a patch, pick a generator, generate a result and
    push it into the preview object. Returns (generator, num_sides, spans,
    corner_source_ids, propagated_keys) on success, or (None, None, None,
    None, None) on failure (nothing reported here -- callers report, since
    CANCELLED vs. silently-ignored-during-hover differ).
    """
    state = context.scene.plasticity_retop
    mesh = obj.data

    patch, side_points, corner_source_ids = _prepare_patch(
        mesh, face_id, state.corner_angle_threshold, state.small_side_tolerance)
    if patch is None:
        return None, None, None, None, None

    generator = generators.find_generator(len(side_points))
    if generator is None:
        return None, None, None, None, None

    defaults = generator.default_spans(side_points)
    defaults, propagated = _propagated_defaults(obj, generator, corner_source_ids, defaults)
    span_u = defaults.get("span_u", state.span_u)
    span_v = defaults.get("span_v", state.span_v)
    span = defaults.get("span", state.span)
    if span_overrides:
        span_u = span_overrides.get("span_u", span_u)
        span_v = span_overrides.get("span_v", span_v)
        span = span_overrides.get("span", span)

    bvh = geometry.build_bvh_for_polygons(mesh, patch.poly_indices) if state.reproject else None
    span_settings = {"span_u": span_u, "span_v": span_v, "span": span}
    result = generator.generate(side_points, span_settings, bvh=bvh)

    mesh_build.update_preview_object(context, obj, result, corner_source_ids)
    return generator, len(side_points), (span_u, span_v, span), corner_source_ids, propagated


def regenerate_active_preview(context):
    """Re-run generation for the currently locked-in patch (state.active_face_id)
    using the current span settings. Used by the Update Preview operator and
    by the span/reproject property update callbacks (state.py) so dragging a
    slider updates the preview live instead of requiring a manual click.
    """
    state = context.scene.plasticity_retop
    if state.active_face_id == -1 or state.source_object_name not in bpy.data.objects:
        return False

    obj = bpy.data.objects[state.source_object_name]
    span_overrides = {"span_u": state.span_u, "span_v": state.span_v, "span": state.span}
    generator, num_sides, spans, corner_source_ids, propagated = _generate_for_face(
        context, obj, state.active_face_id, span_overrides)
    return generator is not None


def _is_own_scaffolding(obj):
    """True for objects this addon itself creates (the live preview and the
    committed result meshes). They sit right on top of the surface being
    picked -- the preview even sits slightly in front of it when Preview
    Offset is used -- so a raycast must look straight through them instead of
    treating them as an occluder.
    """
    return (obj.name == mesh_build.PREVIEW_OBJ_NAME
            or obj.name.endswith(mesh_build.RESULT_NAME_SUFFIX))


def _raycast_patch_ray(context, ray_origin, ray_direction, space=None):
    """Cast `ray_origin`/`ray_direction` through the scene and return
    (hit_object, face_id, distance) for the first Plasticity mesh that is
    actually visible in this viewport, or (None, None, None). `distance` is
    measured in world units from `ray_origin`.

    Two classes of hit are skipped by re-casting from just past them rather
    than aborting the whole cast:

    - objects hidden in this viewport (Local View '/', eye/collection
      toggles): context.scene.ray_cast ignores per-viewport visibility, so
      without this it would happily pick a patch on an isolated-away object.
    - this addon's own preview/result meshes: they're coincident with (or
      pushed in front of) the very surface being hovered, so treating them as
      an occluder made the hover flicker -- the ray would hit the preview,
      report "no patch here", delete the preview, then hit the source mesh
      again on the next mouse move and rebuild it, over and over.

    Respects the Pick Max Distance setting (0 = unlimited).
    """
    depsgraph = context.evaluated_depsgraph_get()
    retop_state = context.scene.plasticity_retop
    max_distance = state_mod.to_blender_units(retop_state, retop_state.pick_max_distance)
    origin = ray_origin
    for _attempt in range(16):
        result, location, _normal, index, hit_obj, _matrix = context.scene.ray_cast(
            depsgraph, origin, ray_direction)

        if not result:
            return None, None, None

        distance = (location - ray_origin).length
        if max_distance > 0.0 and distance > max_distance:
            return None, None, None

        visible = hit_obj.visible_get(viewport=space) if space else hit_obj.visible_get()
        if not visible or _is_own_scaffolding(hit_obj):
            # step past this hit and keep looking along the same ray
            origin = location + ray_direction * 1e-4
            continue

        if not _is_plasticity_mesh(hit_obj):
            return None, None, None

        face_id_of_poly, _ = patch_data.polygon_face_ids(hit_obj.data)
        if index < 0 or index >= len(face_id_of_poly):
            return None, None, None
        return hit_obj, face_id_of_poly[index], distance

    return None, None, None


def patch_hit_distance(ray_origin, ray_direction, obj, face_id):
    """Distance from `ray_origin` to where the ray strikes patch `face_id` of
    `obj`, or None if the ray doesn't hit that particular patch. Used for the
    hover hysteresis in the modal picker.
    """
    if obj is None or obj.name not in bpy.data.objects:
        return None

    matrix_inv = obj.matrix_world.inverted()
    local_origin = matrix_inv @ ray_origin
    # direction transforms without translation
    local_dir = (matrix_inv.to_3x3() @ ray_direction).normalized()

    hit, location, _normal, index = obj.ray_cast(local_origin, local_dir)
    if not hit:
        return None

    face_id_of_poly, _ = patch_data.polygon_face_ids(obj.data)
    if index < 0 or index >= len(face_id_of_poly) or face_id_of_poly[index] != face_id:
        return None

    return ((obj.matrix_world @ location) - ray_origin).length


def viewport_region(context):
    """(region, region_3d) of the 3D viewport's WINDOW region, or (None, None).

    context.region / context.region_data can't be trusted inside a modal: when
    the operator was launched from the N-panel button, the current region is
    the UI one (and region_data is None), which silently produced an invalid
    ray -- so nothing was ever hit and clicks appeared to do nothing.
    """
    area = context.area
    if area is None or area.type != 'VIEW_3D':
        return None, None

    region = context.region
    if region is None or region.type != 'WINDOW':
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)

    rv3d = context.region_data
    if rv3d is None:
        space = area.spaces.active
        rv3d = getattr(space, "region_3d", None)

    if region is None or rv3d is None:
        return None, None
    return region, rv3d


def ray_from_event(context, event):
    """(ray_origin, ray_direction) under the mouse, or (None, None) when the
    cursor isn't over the 3D viewport.
    """
    region, rv3d = viewport_region(context)
    if region is None:
        return None, None

    # Window-absolute coordinates, converted against the WINDOW region itself:
    # event.mouse_region_* is relative to whichever region received the event,
    # which may not be the one we're casting into.
    x = event.mouse_x - region.x
    y = event.mouse_y - region.y
    if not (0 <= x <= region.width and 0 <= y <= region.height):
        return None, None  # cursor is outside the viewport (e.g. over the N-panel)

    coord = (x, y)
    return (view3d_utils.region_2d_to_origin_3d(region, rv3d, coord),
            view3d_utils.region_2d_to_vector_3d(region, rv3d, coord))


def _raycast_patch(context, event):
    """Raycast under the mouse (Object Mode, viewport region) and return
    (hit_object, face_id, distance) for the first pickable Plasticity patch,
    or (None, None, None). See _raycast_patch_ray for the filtering rules.
    """
    ray_origin, ray_direction = ray_from_event(context, event)
    if ray_origin is None:
        return None, None, None

    return _raycast_patch_ray(context, ray_origin, ray_direction, space=context.space_data)


def set_active_patch(context, obj, face_id):
    """Generate a preview for `face_id` on `obj` and lock it in as the active
    patch (the state the N-panel's span controls act on). Returns
    (generator_name, num_sides, propagated_keys), or (None, None, None) if the
    patch can't be generated. Shared by the viewport picker and by tests, so
    both go through exactly one code path.
    """
    generator, num_sides, spans, _corner_source_ids, propagated = _generate_for_face(context, obj, face_id)
    if generator is None:
        return None, None, None

    state = context.scene.plasticity_retop
    state.active_face_id = face_id
    state.generator_name = generator.name
    state.num_sides = num_sides
    state.source_object_name = obj.name
    state.span_u, state.span_v, state.span = spans
    return generator.name, num_sides, propagated


class RETOP_OT_update_preview(bpy.types.Operator):
    bl_idname = "retop.update_preview"
    bl_label = "Update Retop Preview"
    bl_description = "Regenerate the preview using the current span settings"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        state = context.scene.plasticity_retop
        return state.active_face_id != -1 and state.source_object_name in bpy.data.objects

    def execute(self, context):
        if not regenerate_active_preview(context):
            self.report({'ERROR'}, "Active patch no longer found on the source mesh")
            return {'CANCELLED'}
        return {'FINISHED'}


# True only while RETOP_OT_session's modal handler is actually alive. This is
# module state on purpose: a reload (or a crashed modal) resets it to False
# while the scene's session_* properties persist, which is exactly how a
# stale "session" left behind by an interrupted modal is detected -- without
# it, the panel would keep showing a session that no longer handles any
# events (Esc and clicks silently doing nothing).
_SESSION_RUNNING = False


def session_is_running():
    return _SESSION_RUNNING


TWO_SPAN_GENERATORS = {"Quad", "Wedge"}

# Number-row and numpad digits, for typing a span directly.
DIGIT_KEYS = {}
for _d in range(10):
    DIGIT_KEYS[("ZERO", "ONE", "TWO", "THREE", "FOUR",
                "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")[_d]] = str(_d)
    DIGIT_KEYS[f"NUMPAD_{_d}"] = str(_d)


def active_span_prop(state):
    """Name of the span property the wheel/keyboard adjusts for the current
    patch: quads and wedges have two spans (Tab switches between them),
    everything else has a single one shared by all sides.
    """
    if state.generator_name in TWO_SPAN_GENERATORS:
        return "span_u" if state.span_axis == 'U' else "span_v"
    return "span"


def end_session(context):
    """Leave the current retop session entirely: drop any preview, stop
    highlighting the result mesh, and clear session/patch state. Safe to call
    when no modal is running (used to reset stale session state).
    """
    global _SESSION_RUNNING
    _SESSION_RUNNING = False

    state = context.scene.plasticity_retop
    mesh_build.clear_preview_object()

    # Clear the state *before* refreshing: the look of every result mesh is
    # derived from session state, so refreshing first would just re-apply the
    # highlight we're trying to drop.
    state.session_active = False
    state.session_object_name = ""
    state.session_phase = 'OBJECT'
    state.active_face_id = -1
    state.generator_name = ""
    state.num_sides = 0

    mesh_build.refresh_result_appearance(context)


def enter_session_object(context, obj):
    """Enter `obj` for retopology: make sure its result mesh exists, highlight
    it, and move to the patch-picking phase.
    """
    state = context.scene.plasticity_retop
    previous = bpy.data.objects.get(state.session_object_name)
    if previous is not None and previous is not obj:
        mesh_build.set_result_highlight(context, previous, False)

    mesh_build.ensure_result_object(context, obj)
    # Entering an object *is* being in a session: don't rely on the caller
    # having set this first, or the highlight below resolves against stale
    # state and the result mesh silently stays un-highlighted.
    state.session_active = True
    state.session_object_name = obj.name
    state.session_phase = 'PATCH'
    mesh_build.set_result_highlight(context, obj, True)


def exit_session_object(context):
    """Leave the current object but keep the session running, so the next
    click picks another Plasticity object (workflow step 4 -> 5).
    """
    state = context.scene.plasticity_retop
    mesh_build.clear_preview_object()

    # Same ordering rule as end_session: state first, then refresh.
    state.session_object_name = ""
    state.session_phase = 'OBJECT'
    state.active_face_id = -1
    state.generator_name = ""
    state.num_sides = 0

    mesh_build.refresh_result_appearance(context)


class RETOP_OT_session(bpy.types.Operator):
    bl_idname = "retop.session"
    bl_label = "Start Retop Session"
    bl_description = ("Run the retopology workflow in the viewport: click a Plasticity object to "
                       "enter it, click its surfaces one after another to retopologize them, "
                       "Esc to leave the object, Esc again to end the session")
    bl_options = {'REGISTER'}

    _hover_obj = None
    _hover_face_id = None
    _hover_generator_name = None
    _hover_num_sides = None
    _hover_spans = None
    _timer = None
    _typed = ""  # digits typed so far for direct span entry

    # phase -> (cursor, status line)
    _PHASE_UI = {
        'OBJECT': ('EYEDROPPER',
                   "Pick an object   |   Click: enter a Plasticity object   |   Esc: end session"),
        'PATCH': ('PAINT_CROSS',
                  "Pick a surface   |   Click: choose a patch   |   Esc: leave this object"),
        'ADJUST': ('DEFAULT',
                   "Adjust spans in the Retop panel   |   Enter: commit   |   Esc: discard"),
    }

    def _apply_phase_ui(self, context):
        state = context.scene.plasticity_retop
        cursor, status = self._PHASE_UI.get(state.session_phase, ('DEFAULT', ""))
        if context.window:
            context.window.cursor_modal_set(cursor)
        if context.workspace:
            context.workspace.status_text_set(f"Retop — {status}")

    def _set_hover(self, context, obj, face_id):
        generator, num_sides, spans, corner_source_ids, propagated = _generate_for_face(context, obj, face_id)
        if generator is None:
            return False
        self._hover_obj = obj
        self._hover_face_id = face_id
        self._hover_generator_name = generator.name
        self._hover_num_sides = num_sides
        self._hover_spans = spans
        return True

    def _clear_hover(self, context):
        mesh_build.clear_preview_object()
        self._hover_obj = None
        self._hover_face_id = None

    def _keeps_current_hover(self, context, event, new_distance):
        """True when the currently-hovered patch is still under the cursor at
        essentially the same depth as the newly-reported hit.

        Overlapping/coincident Plasticity surfaces make scene.ray_cast report
        whichever of them wins by a sub-epsilon margin, which alternates as
        the mouse moves and made the hover flip-flop between two patches
        (rebuilding the preview each frame = flicker). Sticking to the
        current patch unless the new one is *clearly* in front keeps the
        pick stable; the user can still reach the other surface by moving off
        the patch and back, or by hiding/isolating the one in the way.
        """
        if self._hover_obj is None or new_distance is None:
            return False

        ray_origin, ray_direction = ray_from_event(context, event)
        if ray_origin is None:
            return False

        current_distance = patch_hit_distance(ray_origin, ray_direction, self._hover_obj, self._hover_face_id)
        if current_distance is None:
            return False  # cursor genuinely left the current patch

        state = context.scene.plasticity_retop
        if state.pick_depth_tolerance > 0.0:
            tolerance = state_mod.to_blender_units(state, state.pick_depth_tolerance)
        else:
            # Automatic: proportional to view distance, which is already
            # scale-independent (a 1mm fillet is viewed from proportionally
            # closer than a 10m part), so no unit conversion applies.
            tolerance = max(1e-6, new_distance * 2e-3)
        return current_distance <= new_distance + tolerance

    def _commit(self, context):
        self._flush_typed_span(context)
        if bpy.data.objects.get(mesh_build.PREVIEW_OBJ_NAME) is not None:
            bpy.ops.retop.commit_patch()
        self._set_typed("")

    def _set_typed(self, value):
        self._typed = value
        overlay.typed_span = value  # echoed in the viewport overlay

    def _flush_typed_span(self, context):
        """Apply whatever number has been typed so far, if any."""
        if not self._typed:
            return
        state = context.scene.plasticity_retop
        value = int(self._typed)
        if value >= 1:
            setattr(state, active_span_prop(state), value)

    def _handle_typed_digit(self, context, event):
        """Digits type a span directly (a faster path than scrolling for big
        jumps); Backspace edits, Esc clears the entry. Returns True when the
        event was a numeric-entry key and has been consumed.
        """
        digit = DIGIT_KEYS.get(event.type)
        if digit is not None:
            # Cap the buffer so a stray keyboard repeat can't build an absurd
            # span and lock Blender up regenerating it.
            if len(self._typed) < 3:
                self._set_typed(self._typed + digit)
                self._flush_typed_span(context)
            return True

        if event.type == 'BACK_SPACE':
            self._set_typed(self._typed[:-1])
            self._flush_typed_span(context)
            return True

        return False

    def _nudge_span(self, context, delta):
        """Bump the span the wheel currently drives. Assigning the property
        fires its update callback, which regenerates the preview live.
        """
        state = context.scene.plasticity_retop
        prop = active_span_prop(state)
        setattr(state, prop, max(1, getattr(state, prop) + delta))

    def _finish(self, context, report=None):
        global _SESSION_RUNNING
        _SESSION_RUNNING = False

        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except (ValueError, ReferenceError, RuntimeError):
                pass
            self._timer = None
        if context.window:
            context.window.cursor_modal_restore()
        if context.workspace:
            context.workspace.status_text_set(None)
        overlay.disable()
        end_session(context)
        if report:
            self.report({'INFO'}, report)
        return {'FINISHED'}

    def _in_viewport(self, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def _cursor_over_viewport(self, context, event):
        """True only when the pointer is over the 3D view's WINDOW region.

        The N-panel lives inside the same VIEW_3D area, so without this the
        modal would swallow clicks and scrolls aimed at its own buttons and
        sliders (including Stop Session).
        """
        region, _rv3d = viewport_region(context)
        if region is None:
            return False
        x = event.mouse_x - region.x
        y = event.mouse_y - region.y
        return 0 <= x <= region.width and 0 <= y <= region.height

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception as exc:
            # Never die silently: an unhandled error used to leave the scene's
            # session_* state saying "in session" while no modal was listening,
            # so Esc and clicks did nothing at all.
            import traceback
            traceback.print_exc()
            self._finish(context)
            self.report({'ERROR'}, f"Retop session stopped: {exc}")
            return {'CANCELLED'}

    def _modal(self, context, event):
        state = context.scene.plasticity_retop

        if context.area:
            context.area.tag_redraw()

        # The panel's Commit/Discard buttons clear active_face_id; when that
        # happens, drop straight back to picking the next surface so patches
        # can be retopologized one after another without relaunching.
        if state.session_phase == 'ADJUST' and state.active_face_id == -1:
            state.session_phase = 'PATCH'
            self._clear_hover(context)
            self._apply_phase_ui(context)

        if event.type == 'TIMER':
            return {'PASS_THROUGH'}

        # Anything outside the 3D viewport (N-panel, properties, ...) must stay
        # fully interactive -- that's where spans get adjusted during ADJUST.
        if not self._in_viewport(context):
            return {'PASS_THROUGH'}

        if state.session_phase == 'ADJUST':
            if event.value == 'PRESS' and self._handle_typed_digit(context, event):
                return {'RUNNING_MODAL'}

            if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
                self._commit(context)
                return {'RUNNING_MODAL'}

            # Right-click commits, like Plasticity's modal tools.
            if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
                if not self._cursor_over_viewport(context, event):
                    return {'PASS_THROUGH'}
                self._commit(context)
                return {'RUNNING_MODAL'}

            if event.type == 'TAB' and event.value == 'PRESS':
                if state.generator_name in TWO_SPAN_GENERATORS:
                    state.span_axis = 'V' if state.span_axis == 'U' else 'U'
                    self._set_typed("")  # the number being typed applied to the other span
                return {'RUNNING_MODAL'}

            # Ctrl+wheel adjusts the span; a plain wheel stays zoom, so
            # navigating while tweaking a patch keeps working normally.
            if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
                if not event.ctrl or not self._cursor_over_viewport(context, event):
                    return {'PASS_THROUGH'}
                self._set_typed("")  # scrolling takes over from a half-typed number
                self._nudge_span(context, +1 if event.type == 'WHEELUPMOUSE' else -1)
                return {'RUNNING_MODAL'}

            if event.type == 'ESC' and event.value == 'PRESS':
                # A first Esc only cancels a half-typed number, so a typo
                # doesn't throw away the patch itself.
                if self._typed:
                    self._set_typed("")
                    return {'RUNNING_MODAL'}
                bpy.ops.retop.clear_preview()
                state.session_phase = 'PATCH'
                self._clear_hover(context)
                self._apply_phase_ui(context)
                return {'RUNNING_MODAL'}
            # everything else (navigation, panel clicks) passes through
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE':
            if state.session_phase == 'OBJECT':
                return {'PASS_THROUGH'}

            session_obj = bpy.data.objects.get(state.session_object_name)
            obj, face_id, distance = _raycast_patch(context, event)
            # stay within the object being retopped
            if obj is not None and session_obj is not None and obj != session_obj:
                obj, face_id = None, None

            if obj is not None and face_id is not None:
                if face_id != self._hover_face_id or obj != self._hover_obj:
                    if not self._keeps_current_hover(context, event, distance):
                        if not self._set_hover(context, obj, face_id):
                            self._clear_hover(context)
            elif self._hover_face_id is not None:
                self._clear_hover(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # Clicks on the N-panel (same area, different region) must reach it.
            if not self._cursor_over_viewport(context, event):
                return {'PASS_THROUGH'}

            if state.session_phase == 'OBJECT':
                obj, _face_id, _distance = _raycast_patch(context, event)
                if obj is None:
                    return {'RUNNING_MODAL'}
                enter_session_object(context, obj)
                context.view_layer.objects.active = obj
                self._apply_phase_ui(context)
                self.report({'INFO'}, f"Retopping {obj.name}")
                return {'RUNNING_MODAL'}

            if self._hover_face_id is None:
                return {'RUNNING_MODAL'}

            state.active_face_id = self._hover_face_id
            state.generator_name = self._hover_generator_name
            state.num_sides = self._hover_num_sides
            state.source_object_name = self._hover_obj.name
            state.span_u, state.span_v, state.span = self._hover_spans
            state.session_phase = 'ADJUST'
            self._set_typed("")
            self._apply_phase_ui(context)
            self.report({'INFO'}, f"Patch {self._hover_face_id} ({self._hover_generator_name})")
            return {'RUNNING_MODAL'}

        if event.type == 'ESC' and event.value == 'PRESS':
            if state.session_phase == 'PATCH':
                exit_session_object(context)
                self._clear_hover(context)
                self._apply_phase_ui(context)
                return {'RUNNING_MODAL'}
            return self._finish(context, "Retop session ended")

        # let viewport navigation (orbit/pan/zoom) through untouched
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        global _SESSION_RUNNING

        state = context.scene.plasticity_retop
        self._hover_obj = None
        self._hover_face_id = None

        # Clear anything a previous, interrupted session left behind.
        end_session(context)

        _SESSION_RUNNING = True
        state.session_active = True
        state.active_face_id = -1

        # Skip the object-picking step when the active object is already a
        # Plasticity mesh -- that's the common case after importing.
        active = context.active_object
        if _is_plasticity_mesh(active):
            enter_session_object(context, active)
        else:
            state.session_object_name = ""
            state.session_phase = 'OBJECT'

        self._apply_phase_ui(context)
        overlay.enable()
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class RETOP_OT_end_session(bpy.types.Operator):
    bl_idname = "retop.end_session"
    bl_label = "Stop Retop Session"
    bl_description = ("End the retop session and clear its state. Also use this to recover if the "
                       "panel still shows a session but the viewport no longer responds to clicks "
                       "or Esc (e.g. after reloading the addon mid-session)")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.scene.plasticity_retop.session_active

    def execute(self, context):
        overlay.disable()
        end_session(context)
        if context.workspace:
            context.workspace.status_text_set(None)
        self.report({'INFO'}, "Retop session stopped")
        return {'FINISHED'}


class RETOP_OT_commit_patch(bpy.types.Operator):
    bl_idname = "retop.commit_patch"
    bl_label = "Commit Patch"
    bl_description = "Bake the current preview into the source object's retopology result mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        state = context.scene.plasticity_retop
        return (bpy.data.objects.get(mesh_build.PREVIEW_OBJ_NAME) is not None
                and state.source_object_name in bpy.data.objects)

    def execute(self, context):
        state = context.scene.plasticity_retop
        source_obj = bpy.data.objects[state.source_object_name]

        # Recompute this patch's corner ids so their spans can be registered
        # for propagation to future neighboring patches (cheap: same lookup
        # generation already does, just no need to regenerate geometry here).
        _patch, _side_points, corner_source_ids = _prepare_patch(
            source_obj.data, state.active_face_id, state.corner_angle_threshold, state.small_side_tolerance)

        result_obj, error = mesh_build.commit_preview_to_result(context, source_obj)
        if error:
            self.report({'WARNING'}, error)
            return {'CANCELLED'}

        if corner_source_ids:
            mesh_build.register_patch_spans(
                source_obj, corner_source_ids, spans_per_side(state, len(corner_source_ids)))

        # Note: the result highlight is owned by the session (it stays on for
        # as long as you're inside this object), so it is deliberately NOT
        # turned off here. Clearing active_face_id is what tells a running
        # session to go back to picking the next surface.
        state.active_face_id = -1
        state.generator_name = ""
        state.num_sides = 0

        self.report({'INFO'}, f"Committed patch into {result_obj.name}")
        return {'FINISHED'}


class RETOP_OT_clear_preview(bpy.types.Operator):
    bl_idname = "retop.clear_preview"
    bl_label = "Clear Preview"
    bl_description = "Discard the current preview without committing it"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bpy.data.objects.get(mesh_build.PREVIEW_OBJ_NAME) is not None

    def execute(self, context):
        mesh_build.clear_preview_object()
        state = context.scene.plasticity_retop
        # Highlight stays on while the session is inside this object; clearing
        # active_face_id sends a running session back to picking a surface.
        state.active_face_id = -1
        state.generator_name = ""
        state.num_sides = 0
        return {'FINISHED'}


def _perform_reload():
    """The actual unregister/reload/register cycle, run from a bpy.app.timers
    callback (see RETOP_OT_reload_addon) -- i.e. on Blender's next event loop
    tick, never from inside a still-running operator call. Unregistering an
    operator's own class while its execute() is still on the call stack is
    what crashed Blender the first time this was tried inline; deferring it
    like this is the standard safe pattern for a self-reloading addon.
    """
    import importlib
    from . import (
        ui,
        version as version_mod,
        patch_data as patch_data_mod,
        sides as sides_mod2,
        geometry as geometry_mod,
        generators as generators_mod,
        state as state_mod,
        mesh_build as mesh_build_mod,
        overlay as overlay_mod,
    )
    from .generators import base as gen_base_mod, quad as gen_quad_mod, triangle as gen_triangle_mod

    # Reloading unregisters the session operator's class, which kills any
    # running modal without it ever reaching _finish. Tear the session down
    # first so the scene isn't left claiming to be in a session that no longer
    # listens to anything.
    try:
        end_session(bpy.context)
        if bpy.context.workspace:
            bpy.context.workspace.status_text_set(None)
    except Exception:
        pass

    ui.unregister()
    unregister()
    state_mod.unregister()

    importlib.reload(version_mod)
    importlib.reload(patch_data_mod)
    importlib.reload(sides_mod2)
    importlib.reload(geometry_mod)
    importlib.reload(gen_base_mod)
    importlib.reload(gen_quad_mod)
    importlib.reload(gen_triangle_mod)
    importlib.reload(generators_mod)
    importlib.reload(mesh_build_mod)
    importlib.reload(overlay_mod)
    importlib.reload(state_mod)
    importlib.reload(sys.modules[__name__])  # this operators module itself
    importlib.reload(ui)

    state_mod.register()
    sys.modules[__name__].register()
    ui.register()

    print(f"[Plasticity Retop] Reloaded: v{version_mod.ADDON_VERSION} ({version_mod.BUILD_ID})")
    return None  # one-shot timer, don't reschedule


class RETOP_OT_reload_addon(bpy.types.Operator):
    bl_idname = "retop.reload_addon"
    bl_label = "Reload Retop Addon Only"
    bl_description = ("Reload just this addon's Python modules from disk. More reliable than "
                       "Blender's global Reload Scripts, which can silently fail to finish if any "
                       "other installed addon errors partway through its own reload")
    bl_options = {'REGISTER'}

    def execute(self, context):
        # Schedule the reload for the next event loop tick instead of doing it
        # inline: unregistering this very operator's class while its execute()
        # is still running is unsafe (see _perform_reload's docstring).
        bpy.app.timers.register(_perform_reload, first_interval=0.0)
        self.report({'INFO'}, "Reloading Plasticity Retop...")
        return {'FINISHED'}


CLASSES = (
    RETOP_OT_update_preview,
    RETOP_OT_session,
    RETOP_OT_end_session,
    RETOP_OT_commit_patch,
    RETOP_OT_clear_preview,
    RETOP_OT_reload_addon,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    # A session could still be running (e.g. Reload Addon Only was clicked
    # mid-session); leaving its draw handler behind would leak an overlay that
    # nothing can remove afterwards.
    overlay.disable()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
