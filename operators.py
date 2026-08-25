import sys

import bpy
import mathutils
from bpy_extras import view3d_utils

from . import constants
from . import patch_data
from . import geometry
from . import generators
from . import mesh_build
from . import overlay
from . import patchprep
from . import sidematch
from . import state as state_mod

# Whether a session modal is actually listening. Session *state* lives in the
# scene and outlives a reload or a crashed modal, so the two can disagree --
# which is what `session_is_running` exists to report (see the panel's reset).
_SESSION_RUNNING: bool = False


def resolve_session_object(
    obj: bpy.types.Object | None,
) -> bpy.types.Object | None:
    """The object a session should actually run on.

    Selecting `<Something>_Retop` and starting a session is asking to carry on
    retopologizing `Something` -- the result mesh has no patch data of its own
    and never will, so taking it literally can only fail. Everything else is
    returned untouched.
    """
    if obj is None:
        return None
    source = mesh_build.source_object_for_result(obj)
    return source if source is not None else obj


def _is_plasticity_mesh(obj: bpy.types.Object | None) -> bool:
    return bool(obj is not None and obj.type == 'MESH' and obj.data.get("face_ids"))


def _propagated_defaults(
    obj: bpy.types.Object,
    generator: generators.base.Generator,
    corner_source_ids: list[int],
    defaults: dict[str, int],
) -> tuple[dict[str, int], list[str]]:
    """Override `defaults` (span_u/span_v or span) with spans already used by
    committed neighboring patches sharing a side (see mesh_build's span
    registry), so adjacent patches naturally weld along their whole shared
    edge instead of only at corners. Returns (defaults, locked_keys) where
    locked_keys names which entries were overridden by propagation.
    """
    n = len(corner_source_ids)

    def side_span(i: int) -> int | None:
        a = corner_source_ids[i]
        b = corner_source_ids[(i + 1) % n]
        return mesh_build.lookup_propagated_span(obj, a, b)

    locked = []
    if generator.name == constants.QUAD:
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
    elif generator.name == constants.WEDGE:
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


def register_spans_for(
    context: bpy.types.Context,
    source_obj: bpy.types.Object,
    prepared: patchprep.PreparedPatch,
) -> None:
    """Record the span used along each side of a just-committed patch, so
    neighbouring patches pick it up (mesh_build's span registry).

    A ring registers each of its two loops separately: pairing corners
    cyclically across the whole flat list would invent a side running from the
    outer boundary to the hole. Its per-side counts come from the generator's
    own allocation, since "around" is one number spread over the sides.
    """
    state = context.scene.plasticity_retop
    if state.generator_name == generators.NGON.name:
        # An n-gon has no span, but it does have a segment count per side, and
        # that is what a neighbouring grid patch has to match to weld onto it.
        # Recomputed rather than carried over: same inputs, same result, and it
        # keeps the commit path from having to thread the allocation through.
        #
        # Per loop, like a ring: pairing corners cyclically across a flat list
        # of both loops' ids would invent a side running from the outer
        # boundary into the hole.
        # Same substitution the preview was built with, or the registry would
        # advertise a curvature count on a side that was matched to a neighbour.
        forced = sidematch.ngon_side_segments(
            prepared,
            sidematch.apply_side_matches(context, source_obj, prepared, generators.NGON.name)[0])
        for loop_i, (corner_ids, loop_sides) in enumerate(
                zip(prepared.loops_corner_ids, prepared.loops_sides)):
            if corner_ids:
                mesh_build.register_patch_spans(
                    source_obj, corner_ids,
                    generators.ngon.loop_allocation(
                        loop_sides, state.ngon_angle,
                        forced[loop_i] if loop_i < len(forced) else None))
        return

    if prepared.is_ring:
        around = generators.ring.around_count(prepared.loops_sides, state.span_u)
        for corner_ids, loop_sides in zip(prepared.loops_corner_ids, prepared.loops_sides):
            lengths = [generators.ring.polyline_length(side) for side in loop_sides]
            alloc = generators.ring.allocate_segments(lengths, around)
            mesh_build.register_patch_spans(source_obj, corner_ids, alloc)
        return

    corner_ids = prepared.corner_source_ids
    if corner_ids:
        mesh_build.register_patch_spans(
            source_obj, corner_ids, spans_per_side(state, len(corner_ids)))


def spans_per_side(state: state_mod.RetopPatchState, num_sides: int) -> list[int]:
    """Span used along each side of the active patch, in boundary order --
    what gets recorded for propagation to neighbouring patches.
    """
    if state.generator_name == constants.QUAD:
        return [state.span_u, state.span_v, state.span_u, state.span_v]
    if state.generator_name == constants.WEDGE:
        return [state.span_u] * num_sides
    return [state.span] * num_sides


class PatchPreview:
    """What _generate_for_face produced, so callers don't juggle a 6-tuple."""

    __slots__ = ("generator", "num_sides", "num_loops", "spans", "corner_source_ids",
                 "propagated", "committed", "ngon")

    def __init__(
        self,
        generator: generators.base.Generator,
        num_sides: int,
        num_loops: int,
        spans: tuple[int, int, int],
        corner_source_ids: list[int],
        propagated: list[str],
        committed: bool,
        ngon: bool = False,
    ) -> None:
        self.ngon = ngon  # generated as a single n-gon rather than a span grid
        self.generator = generator
        self.num_sides = num_sides
        self.num_loops = num_loops  # boundary loops the patch has (2 = ring, >2 = unsupported)
        self.spans = spans  # (span_u, span_v, span)
        self.corner_source_ids = corner_source_ids
        self.propagated = propagated  # span keys taken from a committed neighbour
        self.committed = committed  # this patch is already in the result mesh (re-edit)
def adopt_side_reference(
    context: bpy.types.Context, flat_index: int, kind: str | None = None
) -> sidematch.SideReference | None:
    """Pin side `flat_index` to the vertices it should reproduce.

    One path for every generator: the pin is recorded, and regeneration
    substitutes those points into that side and sets whatever count reproduces
    them. Which span that turns out to be is the generator's business (see
    `span_key_for`).

    Two things a side can be pinned to. `sidematch.PIN_NEIGHBOUR` follows the committed
    patch across it, which is what welds two patches together. `sidematch.PIN_SOURCE`
    follows the CAD tessellation of the side itself -- no neighbour needed, so
    it works on the very first patch of a model and on any side facing nothing
    yet, and it is what keeps a feature the even resampling would cut across.
    Given no `kind`, the neighbour is preferred and the source is the fallback.

    Returns the SideReference that was pinned, or None if it can't be.
    """
    state = context.scene.plasticity_retop
    references = sidematch.active_sides()
    if not 0 <= flat_index < len(references):
        return None
    reference = references[flat_index]

    if kind is None:
        kind = sidematch.PIN_NEIGHBOUR if reference.available else sidematch.PIN_SOURCE
    if kind == sidematch.PIN_NEIGHBOUR and not reference.available:
        return None
    if kind == sidematch.PIN_SOURCE and len(reference.source_points) < 2:
        return None

    overrides = sidematch.side_override_map(state)
    if overrides.get(flat_index) == kind:
        overrides.pop(flat_index)  # clicking the same side again releases it
    else:
        overrides[flat_index] = kind
    sidematch.store_side_overrides(state, overrides)
    regenerate_active_preview(context)
    return reference


def _ngon_wanted(
    state: state_mod.RetopPatchState,
    obj: bpy.types.Object,
    face_id: int,
    committed: bool,
) -> bool:
    """Whether the *mode* asks for an n-gon, before checking the patch can take
    one (see ngon_blocker).

    A patch already in the result mesh comes back the way it was committed --
    same rule as its spans, and for the same reason: hovering a finished patch
    must show what is actually there, not what the current mode would build.
    """
    if committed:
        stored = mesh_build.lookup_patch_settings(obj, face_id)
        if stored and stored.get("generator"):
            return stored.get("generator") == generators.NGON.name
    return state.ngon_mode


def ngon_blocker(
    state: state_mod.RetopPatchState,
    mesh: bpy.types.Mesh,
    face_id: int,
    num_loops: int | None = None,
) -> str:
    """Why this patch can't be an n-gon, or "" when it can.

    Two reasons, both hard: a curved face would get a flat lid over it, and
    more than one hole can't be bridged by the two-edge cut generate_holed
    makes (the pipeline only ever hands generators the outer loop past two).
    """
    if not patchprep.patch_is_planar(mesh, face_id, state.ngon_planar_tolerance):
        return "not a flat face"
    if num_loops is not None and num_loops > 2:
        return f"{num_loops} boundary loops"
    return ""


def _generate_for_face(
    context: bpy.types.Context,
    obj: bpy.types.Object,
    face_id: int,
    span_overrides: dict[str, int] | None = None,
) -> "PatchPreview | None":
    """Shared core: prepare a patch, pick a generator, generate a result and
    push it into the preview object. Returns a PatchPreview on success, or None
    on failure (nothing reported here -- callers report, since CANCELLED vs.
    silently-ignored-during-hover differ).
    """
    state = context.scene.plasticity_retop
    mesh = obj.data

    # Committed state is needed before anything else: an n-gon patch has to come
    # back as an n-gon, and the corner method depends on which mode will run.
    committed = mesh_build.is_patch_committed(obj, face_id)
    wants_ngon = _ngon_wanted(state, obj, face_id, committed)
    blocker = ngon_blocker(state, mesh, face_id) if wants_ngon else ""
    ngon = wants_ngon and not blocker

    def prepare(for_ngon: bool) -> patchprep.PreparedPatch | None:
        return patchprep.prepare_patch(
            mesh, face_id, state.corner_angle_threshold,
            # Like every other distance in the panel: typed in state.length_unit.
            state_mod.to_blender_units(state, state.small_side_tolerance),
            state.corner_method_ngon if for_ngon else state.corner_method_spans)

    prepared = prepare(ngon)
    if prepared is None:
        return None

    if ngon:
        # The loop count only comes out of the preparation, so this second gate
        # can't be merged into the first one.
        blocker = ngon_blocker(state, mesh, face_id, prepared.num_loops)
        if blocker:
            ngon = False
            prepared = prepare(False)  # corners resolved for the wrong mode
            if prepared is None:
                return None

    # Two boundary loops is not the same thing as a band. A flat plate with a
    # small hole is an annulus too, and the Ring generator has to give both of
    # its loops the same point count -- so the hole ends up absurdly dense, the
    # outline absurdly coarse, and every quad stretched across the plate. The
    # n-gon fill (outer boundary plus hole, bridged) is the right topology for
    # a flat one, and it is already what pressing N would produce, so a
    # non-band takes it rather than being quietly ruined by a band.
    ring_note = ""
    if not ngon and prepared.is_ring and not generators.ring.is_band(prepared.loops_sides):
        if committed:
            pass  # a committed patch comes back as whatever it was built as
        elif blocker:
            ring_note = f"hole too small for a band, and {blocker}"
        else:
            ngon = True
            ring_note = "hole too small for a band -- filled as an n-gon"
            prepared = prepare(True)
            if prepared is None:
                return None

    state.ngon_available = not blocker
    state.ngon_unavailable_reason = blocker
    state.corner_warning = prepared.corner_warning
    state.generator_note = ring_note

    corner_source_ids = prepared.corner_source_ids

    # Which generator runs is settled before anything is substituted, and can
    # be: substitution swaps a side's *points*, never how many sides there are.
    # It has to be, because a grid has one span per direction, so resolving two
    # sides that want different counts needs to know which sides share one.
    if ngon:
        generator = generators.NGON
    elif prepared.is_ring:
        generator = generators.RING
    else:
        generator = generators.find_generator(len(prepared.sides))
        if generator is None:
            return None

    sidematch.build_side_references(context, obj, prepared, face_id)
    # Collected here, applied further down: a match both *drives* a span and
    # depends on it, so the spans have to be settled before any side is
    # rewritten. The references have to exist first -- they are what holds the
    # neighbour's vertices.
    winners, outvoted = sidematch.collect_side_matches(context, generator.name)
    state.match_conflicts = len(outvoted)

    if ngon:
        # An n-gon carries a segment count per side, so no two matches can
        # disagree and there is nothing to resolve first.
        matched, _ = sidematch.apply_side_matches(context, obj, prepared, generator.name,
                                        winners=winners)
        settings = {"ngon_angle": state.ngon_angle,
                    "side_segments": sidematch.ngon_side_segments(prepared, matched)}
        if prepared.is_ring:
            # One hole: bridged to the outer boundary with two edges, giving
            # two n-gons (a Blender n-gon can't carry a hole on its own).
            result = generator.generate_holed(prepared.loops_sides, settings)
        else:
            settings = dict(settings, side_segments=settings["side_segments"][0])
            result = generator.generate(prepared.sides, settings)
        num_sides = len(corner_source_ids)
        mesh_build.update_preview_object(context, obj, result, corner_source_ids)
        return PatchPreview(generator, num_sides, prepared.num_loops,
                            (state.span_u, state.span_v, state.span),
                            corner_source_ids, [], committed, ngon=True)

    if prepared.is_ring:
        # Two boundary loops: fill the band between them instead of trying to
        # treat one of the loops as if it were the whole patch boundary.
        generation_input = prepared.loops_sides
        num_sides = len(corner_source_ids)
        defaults = state_mod.scale_default_spans(
            state, generator.default_spans(generation_input))
        # Propagation is per side; a ring's "around" span is one number for the
        # whole loop, so nothing is pulled in from neighbours here (it is still
        # pushed out to them on commit).
        propagated = []
    else:
        generation_input = prepared.sides
        num_sides = len(generation_input)
        # Resolution first, propagation second: a span taken from a committed
        # neighbour has to survive the preset, or the two patches stop welding.
        defaults = state_mod.scale_default_spans(
            state, generator.default_spans(generation_input))
        defaults, propagated = _propagated_defaults(obj, generator, corner_source_ids, defaults)

    # An already-committed patch comes back with the spans it was committed
    # with -- they beat both the computed defaults and propagation, which would
    # otherwise silently re-shape a patch the user had already tuned by hand.
    if committed:
        stored = mesh_build.lookup_patch_settings(obj, face_id)
        if stored:
            for key in ("span_u", "span_v", "span"):
                value = stored.get(key)
                if isinstance(value, int) and value >= 1:
                    defaults[key] = value

    span_u = defaults.get("span_u", state.span_u)
    span_v = defaults.get("span_v", state.span_v)
    span = defaults.get("span", state.span)
    if span_overrides:
        span_u = span_overrides.get("span_u", span_u)
        span_v = span_overrides.get("span_v", span_v)
        span = span_overrides.get("span", span)

    # A matched side only reproduces the neighbour's vertices if the generator
    # asks for exactly as many points as it was handed, so the match decides the
    # span that drives it. A grid has one span per *direction*, so pinning one
    # side pins the opposite one's count too -- that's the generator's model,
    # not a choice made here.
    #
    # A **pin** always decides; an **automatic** match only seeds the span the
    # first time the patch is generated. Otherwise scrolling the span on a side
    # that happens to border a committed neighbour would do nothing at all --
    # the match would put its own count straight back every regeneration, and
    # the control would look broken. Changing it away from the neighbour's
    # count instead drops that substitution: the two can no longer weld, which
    # is what asking for a different count means.
    for key, (_reference, points, pinned) in winners.items():
        if key.startswith("side:"):
            continue
        if not (pinned or span_overrides is None):
            continue
        count = len(points) - 1
        if key == "span_u":
            span_u = count
        elif key == "span_v":
            span_v = count
        else:
            span = count

    spans = {"span_u": span_u, "span_v": span_v, "span": span}
    sidematch.apply_side_matches(context, obj, prepared, generator.name, spans, winners=winners)

    bvh = (geometry.build_bvh_for_polygons(mesh, prepared.patch.poly_indices)
           if state.reproject else None)
    span_settings = {"span_u": span_u, "span_v": span_v, "span": span}
    result = generator.generate(generation_input, span_settings, bvh=bvh)

    mesh_build.update_preview_object(context, obj, result, corner_source_ids)
    return PatchPreview(generator, num_sides, prepared.num_loops, (span_u, span_v, span),
                        corner_source_ids, propagated, committed)


def regenerate_active_preview(context: bpy.types.Context) -> bool:
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
    preview = _generate_for_face(context, obj, state.active_face_id, span_overrides)
    if preview is None:
        return False

    # Which generator ran can change under a live update -- toggling N-gon mode
    # is exactly that -- and the panel, the overlay and the commit path all read
    # the patch's shape from these.
    state.generator_name = preview.generator.name
    state.num_sides = preview.num_sides
    state.num_loops = preview.num_loops
    return True


def update_committed_count(
    context: bpy.types.Context, obj: bpy.types.Object | None
) -> None:
    """Refresh the panel's cached "N patches done" figure. Called whenever the
    result mesh changes, so the panel never has to walk it while redrawing.
    """
    state = context.scene.plasticity_retop
    state.committed_patch_count = len(mesh_build.committed_face_ids(obj)) if obj else 0


def begin_reedit(
    context: bpy.types.Context, obj: bpy.types.Object, face_id: int
) -> int:
    """Take patch `face_id`'s existing geometry out of the result mesh so the
    re-edit rebuilds it from nothing, and remember the snapshot that puts it
    back. Returns how many faces were removed.

    Removing on pick rather than on commit is what makes a re-edit legible: the
    old patch disappears the moment you click it, so "nothing was removed" shows
    up immediately instead of surfacing as two overlapping surfaces afterwards.
    """
    state = context.scene.plasticity_retop
    removed, backup = mesh_build.remove_patch_from_result(obj, face_id)
    state.reedit_removed_faces = removed
    state.reedit_backup_mesh = backup
    state.reedit_result_object = mesh_build.result_object_name_for(obj) if backup else ""
    update_committed_count(context, obj)
    print(f"[Plasticity Retop] Re-editing patch {face_id} of '{obj.name}': "
          f"removed {removed} existing face(s)")
    if removed:
        # Taking the patch out edits the result mesh and creates the snapshot
        # datablock: both belong in an undo step of their own.
        push_undo(f"Retop: re-edit patch {face_id}")
    return removed


def _clear_reedit(state: state_mod.RetopPatchState) -> None:
    state.editing_committed = False
    state.reedit_removed_faces = 0
    state.reedit_backup_mesh = ""
    state.reedit_result_object = ""


def keep_reedit_removal(context: bpy.types.Context) -> None:
    """The re-edit was committed: the snapshot of the old patch isn't needed."""
    state = context.scene.plasticity_retop
    if state.reedit_backup_mesh:
        mesh_build.drop_result_snapshot(state.reedit_backup_mesh)
    _clear_reedit(state)


def restore_reedit_removal(context: bpy.types.Context) -> None:
    """Put back the patch a re-edit took out (discard, Esc, leaving the object,
    ending the session): an uncommitted re-edit must never lose topology.
    """
    state = context.scene.plasticity_retop
    if state.reedit_backup_mesh:
        mesh_build.restore_result_snapshot(state.reedit_result_object, state.reedit_backup_mesh)
        update_committed_count(context, bpy.data.objects.get(state.session_object_name)
                               or bpy.data.objects.get(state.source_object_name))
    _clear_reedit(state)


def _is_own_scaffolding(obj: bpy.types.Object) -> bool:
    """True for objects this addon itself creates (the live preview and the
    committed result meshes). They sit right on top of the surface being
    picked -- the preview even sits slightly in front of it when Preview
    Offset is used -- so a raycast must look straight through them instead of
    treating them as an occluder.
    """
    return (obj.name == mesh_build.PREVIEW_OBJ_NAME
            or obj.name.endswith(mesh_build.RESULT_NAME_SUFFIX))


def _raycast_patch_ray(
    context: bpy.types.Context,
    ray_origin: mathutils.Vector,
    ray_direction: mathutils.Vector,
    space: bpy.types.SpaceView3D | None = None,
) -> tuple[bpy.types.Object | None, int | None, float | None]:
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
    for _attempt in range(64):
        result, location, _normal, index, hit_obj, _matrix = context.scene.ray_cast(
            depsgraph, origin, ray_direction)

        if not result:
            return None, None, None

        distance = (location - ray_origin).length
        if max_distance > 0.0 and distance > max_distance:
            return None, None, None

        visible = hit_obj.visible_get(viewport=space) if space else hit_obj.visible_get()
        # A non-Plasticity mesh in the way used to abort the whole cast, which
        # made anything behind it unpickable -- a stand-in, a boolean cutter, a
        # block-out. It is an obstacle like the others, so look through it.
        if not visible or _is_own_scaffolding(hit_obj) or not _is_plasticity_mesh(hit_obj):
            # Step past this hit and keep looking along the same ray. Scaled to
            # the distance travelled: a fixed epsilon is either too small to
            # clear the surface at far range (the same hit repeats until the
            # attempts run out) or big enough to skip past a thin recess floor
            # on a small part.
            origin = location + ray_direction * max(1e-6, distance * 1e-5)
            continue

        face_id_of_poly = patch_data.analyse(hit_obj.data).face_id_of_poly
        if index < 0 or index >= len(face_id_of_poly):
            return None, None, None
        return hit_obj, face_id_of_poly[index], distance

    return None, None, None


def patch_hit_distance(
    ray_origin: mathutils.Vector,
    ray_direction: mathutils.Vector,
    obj: bpy.types.Object | None,
    face_id: int,
) -> float | None:
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

    face_id_of_poly = patch_data.analyse(obj.data).face_id_of_poly
    if index < 0 or index >= len(face_id_of_poly) or face_id_of_poly[index] != face_id:
        return None

    return ((obj.matrix_world @ location) - ray_origin).length


def viewport_region(
    context: bpy.types.Context,
) -> tuple[bpy.types.Region | None, bpy.types.RegionView3D | None]:
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


# Events the modal must never swallow when the cursor is outside the 3D view's
# WINDOW region -- which is *all* of them; the set is here so the rule can be
# asserted rather than only described. Clicks and scrolls are the obvious ones;
# mouse moves are the non-obvious part (Blender drives button highlighting from
# them, so eating MOUSEMOVE over the N-panel leaves the panel unclickable even
# while the clicks are let through), and the keys matter too, since digits
# collide with a field being typed into and Enter confirms the wrong thing.
PANEL_EVENTS = {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE', 'RIGHTMOUSE',
                'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                'RET', 'NUMPAD_ENTER', 'ESC', 'TAB', 'BACK_SPACE',
                'M', 'N', 'X', 'ZERO', 'ONE', 'TWO', 'THREE', 'FOUR',
                'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE'}


# Regions drawn *over* the 3D view's WINDOW region. With Region Overlap on --
# Blender's default -- the WINDOW region spans the whole area and the N-panel,
# toolbar and headers float on top of it, so a point under the N-panel is
# genuinely inside the WINDOW region. Testing that region alone therefore says
# "over the viewport" while the pointer is over the panel, which is exactly how
# the modal ended up swallowing the panel's events.
OVERLAY_REGION_TYPES = {'UI', 'TOOLS', 'TOOL_PROPS', 'HEADER', 'TOOL_HEADER',
                        'NAV_BAR', 'FOOTER', 'ASSET_SHELF', 'ASSET_SHELF_HEADER',
                        'HUD', 'EXECUTE', 'CHANNELS'}


def point_in_region(region: bpy.types.Region | None, x: float, y: float) -> bool:
    """Whether a window-absolute point is inside `region`.

    Window-absolute because `context.region` is unreliable inside a modal (it
    can be the N-panel's), so the modal works from window coordinates and the
    region it resolved itself -- see viewport_region.
    """
    if region is None:
        return False
    local_x = x - region.x
    local_y = y - region.y
    return 0 <= local_x <= region.width and 0 <= local_y <= region.height


def point_in_viewport(
    area: bpy.types.Area | None,
    region: bpy.types.Region | None,
    x: float,
    y: float,
) -> bool:
    """Whether the point is over the 3D view *and not* over a panel floating
    on it. See OVERLAY_REGION_TYPES for why the second half is needed.
    """
    if not point_in_region(region, x, y):
        return False
    if area is None:
        return True
    for other in area.regions:
        # A collapsed region still exists, reporting a 1px size; it covers
        # nothing and must not veto the whole viewport.
        if (other.type in OVERLAY_REGION_TYPES
                and other.width > 1 and other.height > 1
                and point_in_region(other, x, y)):
            return False
    return True


def ray_from_event(
    context: bpy.types.Context, event: bpy.types.Event
) -> tuple[mathutils.Vector | None, mathutils.Vector | None]:
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


def _raycast_patch(
    context: bpy.types.Context, event: bpy.types.Event
) -> tuple[bpy.types.Object | None, int | None, float | None]:
    """Raycast under the mouse (Object Mode, viewport region) and return
    (hit_object, face_id, distance) for the first pickable Plasticity patch,
    or (None, None, None). See _raycast_patch_ray for the filtering rules.
    """
    ray_origin, ray_direction = ray_from_event(context, event)
    if ray_origin is None:
        return None, None, None

    return _raycast_patch_ray(context, ray_origin, ray_direction, space=context.space_data)


def nearest_side_to_cursor(
    context: bpy.types.Context, event: bpy.types.Event, max_pixels: float = 60.0
) -> int:
    """Flat index of the side nearest the cursor, or -1.

    Screen space, not a raycast: the sides are polylines lying exactly on the
    surface, so a ray would hit the surface beside them as often as the line
    itself. Distance to the projected segments is what "pointing at an edge"
    actually means on screen.
    """
    region, rv3d = viewport_region(context)
    if region is None or rv3d is None:
        return -1

    mouse = mathutils.Vector((event.mouse_x - region.x, event.mouse_y - region.y))
    best_index = -1
    best_distance = max_pixels

    for reference in sidematch.active_sides():
        projected = []
        for point in reference.points:
            screen = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
            if screen is not None:
                projected.append(screen)
        for start, end in zip(projected, projected[1:]):
            distance = _distance_to_segment(mouse, start, end)
            if distance < best_distance:
                best_distance = distance
                best_index = reference.index

    return best_index


def _distance_to_segment(
    point: mathutils.Vector, start: mathutils.Vector, end: mathutils.Vector
) -> float:
    segment = end - start
    length_squared = segment.length_squared
    if length_squared < 1e-12:
        return (point - start).length
    t = max(0.0, min(1.0, (point - start).dot(segment) / length_squared))
    return (point - (start + segment * t)).length


def set_active_patch(
    context: bpy.types.Context, obj: bpy.types.Object, face_id: int
) -> tuple[str | None, int | None, list[str] | None]:
    """Generate a preview for `face_id` on `obj` and lock it in as the active
    patch (the state the N-panel's span controls act on). Returns
    (generator_name, num_sides, propagated_keys), or (None, None, None) if the
    patch can't be generated. Shared by the viewport picker and by tests, so
    both go through exactly one code path.
    """
    # A pin names a side *of the patch it was picked on*, by index. Carrying it
    # into the next patch would silently pin whichever side happened to land on
    # that index. Cleared here rather than in the modal so every caller --
    # viewport, panel, tests -- gets the same guarantee.
    state = context.scene.plasticity_retop
    state.side_overrides = ""
    state.hovered_side = -1

    # Same reason as in enter_session_object: claim untracked pre-existing
    # retopology before deciding whether this patch is a re-edit. Cheap no-op
    # once every face carries its patch id.
    mesh_build.adopt_untracked_faces(obj)

    # Generate first, remove second: _generate_for_face reads the result mesh to
    # decide this is a re-edit and to recover the spans it was committed with.
    preview = _generate_for_face(context, obj, face_id)
    if preview is None:
        return None, None, None

    state.active_face_id = face_id
    state.generator_name = preview.generator.name
    state.num_sides = preview.num_sides
    state.num_loops = preview.num_loops
    state.source_object_name = obj.name
    state.span_u, state.span_v, state.span = preview.spans
    state.editing_committed = preview.committed
    if preview.committed:
        begin_reedit(context, obj, face_id)
    return preview.generator.name, preview.num_sides, preview.propagated


def session_is_running() -> bool:
    return _SESSION_RUNNING


# Re-exported so `operators.TWO_SPAN_GENERATORS` keeps working for the panel
# and the tests; the definition lives in `constants`, which the overlay can
# also reach without importing this module back.
TWO_SPAN_GENERATORS = constants.TWO_SPAN_GENERATORS

# Number-row and numpad digits, for typing a span directly.
DIGIT_KEYS: dict[str, str] = {}
for _d in range(10):
    DIGIT_KEYS[("ZERO", "ONE", "TWO", "THREE", "FOUR",
                "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")[_d]] = str(_d)
    DIGIT_KEYS[f"NUMPAD_{_d}"] = str(_d)


def active_span_prop(state: state_mod.RetopPatchState) -> str:
    """Name of the span property the wheel/keyboard adjusts for the current
    patch: quads and wedges have two spans (Tab switches between them),
    everything else has a single one shared by all sides.
    """
    if state.generator_name in TWO_SPAN_GENERATORS:
        return "span_u" if state.span_axis == 'U' else "span_v"
    return "span"


def _clear_match_state(state: state_mod.RetopPatchState) -> None:
    """The side picker is per patch: its cache holds Vectors describing a
    preview, and its pins describe sides that patch had. `match_mode` is a
    preference, not patch state, so it survives."""
    sidematch.clear_side_references()
    state.hovered_side = -1
    state.side_overrides = ""


def end_session(context: bpy.types.Context) -> None:
    """Leave the current retop session entirely: drop any preview, stop
    highlighting the result mesh, and clear session/patch state. Safe to call
    when no modal is running (used to reset stale session state).
    """
    global _SESSION_RUNNING
    _SESSION_RUNNING = False

    state = context.scene.plasticity_retop
    # The one place the preview object is actually freed: ending the session is
    # a deliberate moment, unlike a hover.
    mesh_build.remove_preview_object()
    overlay.hover_committed = False
    # An in-flight re-edit is rolled back, never silently dropped: its patch was
    # removed from the result mesh on pick and was never re-committed.
    restore_reedit_removal(context)

    # Clear the state *before* refreshing: the look of every result mesh is
    # derived from session state, so refreshing first would just re-apply the
    # highlight we're trying to drop.
    state.session_active = False
    state.session_object_name = ""
    state.session_phase = 'OBJECT'
    state.active_face_id = -1
    state.generator_name = ""
    state.num_sides = 0
    state.editing_committed = False
    _clear_match_state(state)

    mesh_build.refresh_result_appearance(context)
    push_undo("Retop: end session")


def push_undo(message: str) -> None:
    """Give the objects a session just created their own undo step.

    Datablocks created between two undo steps are invisible to the one Ctrl+Z
    rolls back to, which is how the depsgraph ends up walking freed data. All
    of the session's ID creation happens at the two moments that call this.
    """
    if bpy.app.background:
        return  # no undo stack in --background, and the tests don't need one
    try:
        bpy.ops.ed.undo_push(message=message)
    except Exception:
        pass


def enter_session_object(
    context: bpy.types.Context, obj: bpy.types.Object | None
) -> None:
    """Enter `obj` for retopology: make sure its result mesh exists, highlight
    it, and move to the patch-picking phase.

    A result mesh resolves to its source first, so entering by way of the
    retopology -- selecting it in the outliner, say -- carries on where it left
    off instead of starting a session on a mesh with no patch data.
    """
    obj = resolve_session_object(obj)
    state = context.scene.plasticity_retop
    previous = bpy.data.objects.get(state.session_object_name)
    if previous is not None and previous is not obj:
        mesh_build.set_result_highlight(context, previous, False)

    mesh_build.ensure_result_object(context, obj)
    # Create the preview here too, rather than on the first hover: that keeps
    # every datablock this session needs inside the single undo step below.
    mesh_build.ensure_preview_object(context)
    # Retopology committed before per-face patch tracking existed has to be
    # claimed once, here, or its patches read as "never retopped": picking one
    # would quietly build a second grid on top of the first instead of
    # re-editing it.
    mesh_build.adopt_untracked_faces(obj)
    # Snapshots left by a re-edit that was undone, crashed or reloaded out from
    # under us: they carry a fake user, so nothing else would ever collect them.
    mesh_build.purge_stale_snapshots(keep_name=state.reedit_backup_mesh)
    update_committed_count(context, obj)
    # Entering an object *is* being in a session: don't rely on the caller
    # having set this first, or the highlight below resolves against stale
    # state and the result mesh silently stays un-highlighted.
    state.session_active = True
    state.session_object_name = obj.name
    state.session_phase = 'PATCH'
    mesh_build.set_result_highlight(context, obj, True)
    # Starting a session while already isolated ('/') would otherwise create
    # the preview and result meshes outside the local view, i.e. invisible.
    mesh_build.sync_local_view(context)
    push_undo(f"Retop: enter {obj.name}")


def exit_session_object(context: bpy.types.Context) -> None:
    """Leave the current object but keep the session running, so the next
    click picks another Plasticity object (workflow step 4 -> 5).
    """
    state = context.scene.plasticity_retop
    mesh_build.clear_preview_object()
    restore_reedit_removal(context)  # same rule as end_session

    # Same ordering rule as end_session: state first, then refresh.
    state.session_object_name = ""
    state.session_phase = 'OBJECT'
    state.active_face_id = -1
    state.generator_name = ""
    state.num_sides = 0
    _clear_match_state(state)

    mesh_build.refresh_result_appearance(context)


def _match_report(
    state: state_mod.RetopPatchState, reference: sidematch.SideReference
) -> str:
    """What a click on a side just did, in the status bar."""
    pins = sidematch.side_override_map(state)
    kind = pins.get(reference.index)
    if kind is None:
        return f"Side {reference.in_loop} released"
    if kind == sidematch.PIN_SOURCE:
        return (f"Side {reference.in_loop} follows the CAD edge: "
                f"{reference.source_span} segment(s)")
    neighbour = ("patch " + str(reference.neighbour)) if reference.neighbour is not None \
        else "its neighbour"
    conflict = ""
    if state.match_conflicts:
        conflict = (f" -- {state.match_conflicts} other side(s) wanted the same span "
                    "and were outvoted")
    return (f"Side {reference.in_loop} matched to {neighbour}: "
            f"{reference.span} segment(s){conflict}")


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
    _hover_num_loops = 1
    _hover_spans = None
    _hover_committed = False
    _hover_ngon = False
    _timer = None
    _typed = ""  # digits typed so far for direct span entry
    # None until the first mouse move tells us which side of the region the
    # pointer is on; see _update_cursor.
    _cursor_in_viewport = None

    # phase -> (cursor, status line)
    _PHASE_UI = {
        'OBJECT': ('EYEDROPPER',
                   "Pick an object   |   Click: enter a Plasticity object   |   Esc: end session"),
        'PATCH': ('PAINT_CROSS',
                  "Pick a surface   |   Click: choose a patch (an already retopped one to "
                  "re-edit it)   |   Esc: leave this object"),
        'ADJUST': ('DEFAULT',
                   "Adjust spans in the Retop panel   |   Enter: commit   |   Esc: discard"),
    }

    def _leave_for_other_mode(self, context: bpy.types.Context) -> None:
        """Drop back to picking an object because Blender left Object mode.

        Entering Edit Mode on the retopology is the normal way to hand-tweak
        it, and coming back to a session still claiming to be inside an object
        -- with a stale preview and a cursor to match -- is worse than starting
        the pick again.
        """
        state = context.scene.plasticity_retop
        if state.session_phase == 'OBJECT':
            return

        # One exception, and it is not optional: a re-edit has that patch's
        # faces out of the result mesh and only a snapshot to put them back
        # with. If the mesh being edited *is* that result mesh, writing to it
        # from here is discarded the moment edit mode exits -- the patch would
        # be gone for good. Stay put; the panel says the session is paused.
        editing = getattr(context, "edit_object", None)
        if (state.editing_committed and state.reedit_result_object
                and editing is not None
                and editing.name == state.reedit_result_object):
            return

        exit_session_object(context)
        self._clear_hover(context)
        self._apply_phase_ui(context)
        self.report({'INFO'}, "Left the object: Blender is not in Object Mode")

    def _apply_phase_ui(self, context: bpy.types.Context) -> None:
        state = context.scene.plasticity_retop
        cursor, status = self._PHASE_UI.get(state.session_phase, ('DEFAULT', ""))
        # Only while the pointer is actually over the 3D view: a modal cursor is
        # set on the whole window, so setting it here unconditionally would put
        # the eyedropper over the panel's own buttons.
        if context.window and self._cursor_in_viewport is not False:
            context.window.cursor_modal_set(cursor)
        if context.workspace:
            context.workspace.status_text_set(f"Retop — {status}")

    def _update_cursor(
        self, context: bpy.types.Context, over_viewport: bool
    ) -> None:
        """Session cursor over the 3D view, the normal one everywhere else.

        `cursor_modal_set` applies to the entire window, so without this the
        retop cursor sits over the N-panel and every other editor for as long
        as the session runs -- which reads as "the UI is not for you".
        """
        if over_viewport == self._cursor_in_viewport or context.window is None:
            return
        self._cursor_in_viewport = over_viewport
        if over_viewport:
            state = context.scene.plasticity_retop
            cursor, _status = self._PHASE_UI.get(state.session_phase, ('DEFAULT', ""))
            context.window.cursor_modal_set(cursor)
        else:
            context.window.cursor_modal_restore()

    def _set_hover(
        self, context: bpy.types.Context, obj: bpy.types.Object, face_id: int
    ) -> bool:
        preview = _generate_for_face(context, obj, face_id)
        if preview is None:
            return False
        self._hover_obj = obj
        self._hover_face_id = face_id
        self._hover_generator_name = preview.generator.name
        self._hover_num_sides = preview.num_sides
        self._hover_num_loops = preview.num_loops
        self._hover_spans = preview.spans
        self._hover_committed = preview.committed
        self._hover_ngon = preview.ngon
        # so the overlay can advertise "Re-edit patch" instead of "Pick surface"
        overlay.hover_committed = preview.committed
        return True

    def _clear_hover(self, context: bpy.types.Context) -> None:
        mesh_build.clear_preview_object()
        self._hover_obj = None
        self._hover_face_id = None
        self._hover_committed = False
        self._hover_ngon = False
        overlay.hover_committed = False

    def _keeps_current_hover(
        self,
        context: bpy.types.Context,
        event: bpy.types.Event,
        new_distance: float | None,
    ) -> bool:
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

    def _modal_match(
        self, context: bpy.types.Context, event: bpy.types.Event
    ) -> set[str] | None:
        """Mouse handling for the side highlight, while it is on. Returns a
        modal result to stop on, or None to let normal ADJUST handling have the
        event.

        Deliberately does *not* take Esc or the commit keys: the highlight is
        on by default, so swallowing Esc would mean the patch could no longer
        be discarded, and that trade is not worth one keystroke.
        """
        state = context.scene.plasticity_retop

        if event.type == 'MOUSEMOVE':
            state.hovered_side = nearest_side_to_cursor(context, event)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # A left click has only two jobs while adjusting: take the side
            # under the cursor, or -- pointing at nothing -- commit. So a
            # missed aim commits rather than doing nothing, which is the same
            # thing right-click and Enter already do.
            #
            # Ctrl forces the *source* topology: a side already matched to a
            # committed neighbour can still be asked to follow the CAD edge
            # instead, and one facing nothing committed has no other choice.
            if state.hovered_side == -1:
                return None
            kind = sidematch.PIN_SOURCE if event.ctrl else None
            adopted = adopt_side_reference(context, state.hovered_side, kind)
            if adopted is None:
                references = sidematch.active_sides()
                reason = (references[state.hovered_side].reason
                          if 0 <= state.hovered_side < len(references) else "")
                self.report({'WARNING'},
                            f"Can't match this side: {reason or 'nothing committed along it'}")
                return {'RUNNING_MODAL'}
            self.report({'INFO'}, _match_report(state, adopted))
            return {'RUNNING_MODAL'}

        return None

    def _commit(self, context: bpy.types.Context) -> None:
        self._flush_typed_span(context)
        if mesh_build.has_preview():
            bpy.ops.retop.commit_patch()
        self._set_typed("")

    def _set_typed(self, value: str) -> None:
        self._typed = value
        overlay.typed_span = value  # echoed in the viewport overlay

    def _flush_typed_span(self, context: bpy.types.Context) -> None:
        """Apply whatever number has been typed so far, if any."""
        if not self._typed:
            return
        state = context.scene.plasticity_retop
        value = int(self._typed)
        if value >= 1:
            setattr(state, active_span_prop(state), value)

    def _handle_typed_digit(
        self, context: bpy.types.Context, event: bpy.types.Event
    ) -> bool:
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

    def _nudge_ngon_angle(self, context: bpy.types.Context, direction: int) -> None:
        """Ctrl+wheel in N-gon mode: same gesture, the same meaning.

        An n-gon has no span to step, but it does have a density, and that is
        `ngon_angle` -- *inverted*, since it is degrees of boundary turn per
        kept vertex. Scrolling up therefore lowers it. Multiplicative because
        the setting is: a 2 degree step is nothing at 90 and everything at 4.
        """
        state = context.scene.plasticity_retop
        factor = 1.25
        angle = state.ngon_angle / factor if direction > 0 else state.ngon_angle * factor
        # The property's update callback regenerates the preview.
        state.ngon_angle = max(1.0, min(180.0, round(angle, 1)))

    def _nudge_span(self, context: bpy.types.Context, delta: int) -> None:
        """Bump the span the wheel currently drives. Assigning the property
        fires its update callback, which regenerates the preview live.
        """
        state = context.scene.plasticity_retop
        prop = active_span_prop(state)
        setattr(state, prop, max(1, getattr(state, prop) + delta))

    def _finish(
        self, context: bpy.types.Context, report: str | None = None
    ) -> set[str]:
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

    def _in_viewport(self, context: bpy.types.Context) -> bool:
        return context.area is not None and context.area.type == 'VIEW_3D'

    def _cursor_over_viewport(
        self, context: bpy.types.Context, event: bpy.types.Event
    ) -> bool:
        """True only when the pointer is over the 3D view and clear of the
        panels floating on it."""
        region, _rv3d = viewport_region(context)
        return point_in_viewport(context.area, region, event.mouse_x, event.mouse_y)

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
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

    def _modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        state = context.scene.plasticity_retop

        if context.area:
            context.area.tag_redraw()

        # The panel's Commit/Discard buttons clear active_face_id; when that
        # happens, drop straight back to picking the next surface so patches
        # can be retopologized one after another without relaunching.
        if state.session_phase == 'ADJUST' and state.active_face_id == -1:
            state.session_phase = 'PATCH'
            state.hovered_side = -1
            self._clear_hover(context)
            self._apply_phase_ui(context)

        if event.type == 'TIMER':
            return {'PASS_THROUGH'}

        # Edit/Sculpt/Weight-paint mode: the session has no business in the
        # viewport there, and holding on to events would make the mode
        # unusable. Handled on the timer as well as on input, so the hand-back
        # happens the moment the mode changes rather than on the next click.
        if context.mode != 'OBJECT':
            self._leave_for_other_mode(context)
            return {'PASS_THROUGH'}

        # The cursor first, and before the area check: a modal cursor is set on
        # the whole *window*, so it has to be dropped as soon as the pointer
        # leaves the 3D view -- including for another editor entirely, which the
        # area check below returns on. viewport_region gives (None, None) there,
        # which point_in_region reads as "outside".
        over_viewport = self._cursor_over_viewport(context, event)
        self._update_cursor(context, over_viewport)

        # Anything outside the 3D viewport (N-panel, properties, ...) must stay
        # fully interactive -- that's where spans get adjusted during ADJUST.
        if not self._in_viewport(context):
            return {'PASS_THROUGH'}

        # The N-panel lives *inside* the 3D view's area, so the check above
        # doesn't cover it: only the region test does.
        #
        # Everything passes through when the pointer is outside the 3D view --
        # every event, not a list of them. The panel has to stay fully usable
        # for as long as a session runs, and a modal that keeps *any* event
        # over it will eventually eat the one that mattered: mouse moves stop
        # buttons from highlighting, digits collide with a field being typed
        # into, Enter confirms the wrong thing. The cost is that the session's
        # keybinds need the pointer over the viewport, which is how Blender's
        # own region keymaps behave anyway.
        if not over_viewport:
            state.hovered_side = -1
            return {'PASS_THROUGH'}

        # Handled before the per-phase blocks, because it belongs to all of
        # them: the CAD structure is what you read while *choosing* a surface
        # as much as while adjusting one.
        if event.type == 'E' and event.value == 'PRESS' and not event.ctrl:
            state.show_cad_edges = not state.show_cad_edges
            self.report({'INFO'},
                        "Plasticity edges: " + ("on" if state.show_cad_edges else "off"))
            return {'RUNNING_MODAL'}
        if event.type == 'E' and event.value == 'PRESS' and event.ctrl:
            state.show_surface_flow = not state.show_surface_flow
            self.report({'INFO'},
                        "Surface flow: " + ("on" if state.show_surface_flow else "off"))
            return {'RUNNING_MODAL'}

        if state.session_phase == 'ADJUST':
            # Match mode owns the mouse while it is on, so it is handled before
            # anything else in this phase.
            if state.match_mode:
                consumed = self._modal_match(context, event)
                if consumed is not None:
                    return consumed

            if event.value == 'PRESS' and self._handle_typed_digit(context, event):
                return {'RUNNING_MODAL'}

            if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
                self._commit(context)
                return {'RUNNING_MODAL'}

            # Left click: nothing else to select while adjusting a patch, and
            # the side picker above has already had its chance at it.
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                self._commit(context)
                return {'RUNNING_MODAL'}

            # Right-click commits, like Plasticity's modal tools.
            if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
                self._commit(context)
                return {'RUNNING_MODAL'}

            if event.type == 'X' and event.value == 'PRESS':
                if not state.editing_committed:
                    self.report({'WARNING'},
                                "Nothing to delete: this patch isn't committed yet")
                    return {'RUNNING_MODAL'}
                bpy.ops.retop.delete_patch()
                return {'RUNNING_MODAL'}

            if event.type == 'M' and event.value == 'PRESS':
                state.match_mode = not state.match_mode
                state.hovered_side = -1
                self._set_typed("")
                return {'RUNNING_MODAL'}

            if event.type == 'N' and event.value == 'PRESS':
                if not state.ngon_mode and not state.ngon_available:
                    self.report({'WARNING'},
                                f"N-gon mode not available here: {state.ngon_unavailable_reason}")
                    return {'RUNNING_MODAL'}
                # The property's own update callback regenerates the preview and
                # refreshes generator_name, so the panel and overlay follow.
                state.ngon_mode = not state.ngon_mode
                self._set_typed("")
                return {'RUNNING_MODAL'}

            if event.type == 'TAB' and event.value == 'PRESS':
                if state.generator_name in TWO_SPAN_GENERATORS:
                    state.span_axis = 'V' if state.span_axis == 'U' else 'U'
                    self._set_typed("")  # the number being typed applied to the other span
                return {'RUNNING_MODAL'}

            # Ctrl+wheel adjusts the span; a plain wheel stays zoom, so
            # navigating while tweaking a patch keeps working normally.
            if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
                if not event.ctrl:
                    return {'PASS_THROUGH'}
                self._set_typed("")  # scrolling takes over from a half-typed number
                direction = +1 if event.type == 'WHEELUPMOUSE' else -1
                if state.ngon_mode:
                    self._nudge_ngon_angle(context, direction)
                else:
                    self._nudge_span(context, direction)
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
            state.num_loops = self._hover_num_loops
            state.source_object_name = self._hover_obj.name
            state.span_u, state.span_v, state.span = self._hover_spans
            # Per-side matches belong to the patch they were picked on.
            state.side_overrides = ""
            state.hovered_side = -1
            # Re-editing a patch committed as an n-gon puts the session back
            # into n-gon mode, so panel and keybinds describe what is on screen.
            state.ngon_mode = self._hover_ngon
            state.editing_committed = self._hover_committed
            state.session_phase = 'ADJUST'
            self._set_typed("")
            self._apply_phase_ui(context)

            if self._hover_committed:
                # The hover preview already holds the regenerated grid, so the
                # old geometry can go now -- no need to rebuild anything.
                removed = begin_reedit(context, self._hover_obj, self._hover_face_id)
                self.report(
                    {'INFO'} if removed else {'WARNING'},
                    f"Re-editing patch {self._hover_face_id} "
                    f"({self._hover_generator_name}) — removed {removed} old face(s)")
            else:
                self.report({'INFO'},
                            f"Patch {self._hover_face_id} ({self._hover_generator_name})")
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

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        global _SESSION_RUNNING

        state = context.scene.plasticity_retop
        self._hover_obj = None
        self._hover_face_id = None
        self._hover_committed = False
        self._cursor_in_viewport = None

        # Clear anything a previous, interrupted session left behind.
        end_session(context)

        _SESSION_RUNNING = True
        state.session_active = True
        state.active_face_id = -1

        # Skip the object-picking step when the active object is already a
        # Plasticity mesh -- that's the common case after importing.
        active = resolve_session_object(context.active_object)
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
    def poll(cls, context: bpy.types.Context) -> bool:
        return context.scene.plasticity_retop.session_active

    def execute(self, context: bpy.types.Context) -> set[str]:
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
    def poll(cls, context: bpy.types.Context) -> bool:
        state = context.scene.plasticity_retop
        return mesh_build.has_preview() and state.source_object_name in bpy.data.objects

    def execute(self, context: bpy.types.Context) -> set[str]:
        state = context.scene.plasticity_retop
        source_obj = bpy.data.objects[state.source_object_name]
        face_id = state.active_face_id
        replacing = state.editing_committed

        # Recompute this patch's corner ids so their spans can be registered
        # for propagation to future neighboring patches (cheap: same lookup
        # generation already does, just no need to regenerate geometry here).
        # Same corner method the preview was generated with, or the spans
        # registered for propagation would describe sides that don't exist.
        prepared = patchprep.prepare_patch(
            source_obj.data, face_id, state.corner_angle_threshold,
            state.small_side_tolerance,
            state.corner_method_ngon if state.generator_name == generators.NGON.name
            else state.corner_method_spans)

        # Passing the face id is what lets a re-committed patch replace its own
        # previous faces instead of stacking a second grid on top of them.
        result_obj, error = mesh_build.commit_preview_to_result(context, source_obj, face_id=face_id)
        if error:
            self.report({'WARNING'}, error)
            return {'CANCELLED'}

        # Bookkeeping first, propagation second. The geometry is already in the
        # result mesh at this point, so anything that throws from here on leaves
        # the commit half-done -- and of the three, only these two matter for
        # correctness: without them the re-edit snapshot stays alive and the
        # panel's patch count goes stale. Span registration is additive.
        keep_reedit_removal(context)
        update_committed_count(context, source_obj)

        mesh_build.register_patch_settings(
            source_obj, face_id, state.span_u, state.span_v, state.span, state.generator_name)
        if prepared is not None:
            register_spans_for(context, source_obj, prepared)

        # Note: the result highlight is owned by the session (it stays on for
        # as long as you're inside this object), so it is deliberately NOT
        # turned off here. Clearing active_face_id is what tells a running
        # session to go back to picking the next surface.
        state.active_face_id = -1
        state.generator_name = ""
        state.num_sides = 0

        verb = "Replaced" if replacing else "Committed"
        self.report({'INFO'}, f"{verb} patch {face_id} in {result_obj.name}")
        return {'FINISHED'}


class RETOP_OT_clear_preview(bpy.types.Operator):
    bl_idname = "retop.clear_preview"
    bl_label = "Clear Preview"
    bl_description = "Discard the current preview without committing it"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        state = context.scene.plasticity_retop
        # Also available with an empty preview while a re-edit is open, so its
        # removal can still be rolled back.
        return mesh_build.has_preview() or state.editing_committed

    def execute(self, context: bpy.types.Context) -> set[str]:
        mesh_build.clear_preview_object()
        state = context.scene.plasticity_retop
        # Discarding a re-edit puts the patch that was taken out on pick back
        # exactly as it was, so Esc can never lose committed topology.
        restore_reedit_removal(context)
        # Highlight stays on while the session is inside this object; clearing
        # active_face_id sends a running session back to picking a surface.
        state.active_face_id = -1
        state.generator_name = ""
        state.num_sides = 0
        return {'FINISHED'}


class RETOP_OT_delete_patch(bpy.types.Operator):
    bl_idname = "retop.delete_patch"
    bl_label = "Delete Patch"
    bl_description = ("Remove this patch's retopology for good instead of replacing it. "
                      "Only its own faces go: vertices a neighbouring patch still uses "
                      "survive, so the patches around it keep their welds")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        state = context.scene.plasticity_retop
        # Only during a re-edit: picking a committed patch is what takes its
        # faces out, and deleting is simply choosing not to put anything back.
        return state.editing_committed and state.source_object_name in bpy.data.objects

    def execute(self, context: bpy.types.Context) -> set[str]:
        state = context.scene.plasticity_retop
        source_obj = bpy.data.objects[state.source_object_name]
        face_id = state.active_face_id
        removed = state.reedit_removed_faces

        # The faces went when the patch was picked; deleting is keeping that
        # removal and committing nothing in their place. Dropping the snapshot
        # is what makes it permanent.
        keep_reedit_removal(context)
        mesh_build.clear_preview_object()
        mesh_build.forget_patch_settings(source_obj, face_id)
        update_committed_count(context, source_obj)

        # Creases are a property of the border *between* patches, so losing one
        # changes the shading of edges that belong to its neighbours.
        result_obj = bpy.data.objects.get(mesh_build.result_object_name_for(source_obj))
        if result_obj is not None:
            mesh_build.apply_result_shading(context, result_obj)

        state.active_face_id = -1
        state.generator_name = ""
        state.num_sides = 0

        self.report({'INFO'}, f"Deleted patch {face_id} ({removed} face(s))")
        return {'FINISHED'}


class RETOP_OT_match_neighbour(bpy.types.Operator):
    """Arm the side picker. The session modal does the pointing -- this only
    flips the sub-mode on, so the panel button and the M key are one thing.
    """

    bl_idname = "retop.match_neighbour"
    bl_label = "Match Neighbour"
    bl_description = ("Point at a side this patch shares with an already-retopologized "
                      "neighbour and click it, to reuse that neighbour's vertex count "
                      "along the shared boundary instead of the computed one")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        state = context.scene.plasticity_retop
        return state.session_active and state.session_phase == 'ADJUST'

    def execute(self, context: bpy.types.Context) -> set[str]:
        state = context.scene.plasticity_retop
        state.match_mode = not state.match_mode
        state.hovered_side = -1
        return {'FINISHED'}


class RETOP_OT_toggle_see_through(bpy.types.Operator):
    bl_idname = "retop.toggle_see_through"
    bl_label = "Retopo Through Meshes"
    bl_description = ("Toggle whether the retopology draws over everything else or is occluded "
                      "like any other object. Seeing it through the CAD surface is what you want "
                      "while building it; switching that off is the only way to check it sits on "
                      "the surface rather than floating off it")
    bl_options = {'REGISTER'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        state = context.scene.plasticity_retop
        state.result_see_through = not state.result_see_through
        # The property's own update callback re-applies the look.
        self.report({'INFO'},
                    "Retopo drawn through meshes" if state.result_see_through
                    else "Retopo occluded like any object")
        return {'FINISHED'}


class RETOP_OT_local_view(bpy.types.Operator):
    """Blender's Local View, extended to keep the retopology in view."""

    bl_idname = "retop.local_view"
    bl_label = "Isolate (Keep Retopology)"
    bl_description = ("Toggle Local View like '/' does, then pull the isolated object's "
                      "retopology mesh and the live preview into it, so isolating a CAD "
                      "surface doesn't hide the very geometry you're building on it")
    bl_options = {'REGISTER'}

    frame_selected: bpy.props.BoolProperty(
        name="Frame Selected", default=True,
        description="Move the view to frame the isolated objects",
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        space = context.space_data
        return space is not None and space.type == 'VIEW_3D'

    def execute(self, context: bpy.types.Context) -> set[str]:
        # Delegate the actual toggle: matching Blender's own selection rules,
        # framing and undo behaviour by hand is a losing game. When the setting
        # is off, sync_local_view is a no-op and '/' behaves exactly as usual.
        bpy.ops.view3d.localview('INVOKE_DEFAULT', frame_selected=self.frame_selected)

        space = context.space_data
        if space.local_view is None:
            return {'FINISHED'}  # we just left local view, nothing to add

        added = mesh_build.sync_local_view(context)
        if added:
            self.report({'INFO'}, f"Isolated with {added} retop object(s)")
        return {'FINISHED'}


def _perform_reload() -> None:
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
        constants as constants_mod,
        patch_data as patch_data_mod,
        sides as sides_mod2,
        geometry as geometry_mod,
        generators as generators_mod,
        cad_display as cad_display_mod,
        state as state_mod,
        mesh_build as mesh_build_mod,
        patchprep as patchprep_mod,
        sidematch as sidematch_mod,
        overlay as overlay_mod,
    )
    # Submodules are collected from sys.modules, never listed by hand.
    # Reloading a package re-runs its imports, but those resolve straight out
    # of sys.modules, so a module missing from the reload list keeps running
    # its old code -- and the mismatch surfaces as an AttributeError from a
    # *reloaded* module calling a function the stale one doesn't have yet.
    # That is precisely what a hand-written list did when generators/ngon.py
    # was added, hence this sweep.
    package_name = __name__.rpartition(".")[0]
    generator_prefix = f"{package_name}.generators."
    generator_modules = [module for name, module in sorted(sys.modules.items())
                         if name.startswith(generator_prefix) and module is not None]

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

    # Order matters for the listed ones: each is reloaded before whatever
    # imports it, so nothing is left holding a reference into a dead module.
    ordered = ([version_mod, constants_mod, patch_data_mod, sides_mod2, geometry_mod]
               + generator_modules
               + [generators_mod, cad_display_mod, mesh_build_mod,
                  patchprep_mod, sidematch_mod, overlay_mod, state_mod])

    reloaded = set()
    for module in ordered:
        importlib.reload(module)
        reloaded.add(module.__name__)

    # Anything else the package has picked up since -- a module nobody thought
    # to add above -- is reloaded too rather than silently left stale.
    last = (__name__, ui.__name__)
    for name, module in sorted(sys.modules.items()):
        if (name.startswith(f"{package_name}.") and module is not None
                and name not in reloaded and name not in last):
            importlib.reload(module)

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

    def execute(self, context: bpy.types.Context) -> set[str]:
        # Schedule the reload for the next event loop tick instead of doing it
        # inline: unregistering this very operator's class while its execute()
        # is still running is unsafe (see _perform_reload's docstring).
        bpy.app.timers.register(_perform_reload, first_interval=0.0)
        self.report({'INFO'}, "Reloading Plasticity Retop...")
        return {'FINISHED'}


@bpy.app.handlers.persistent
def _on_undo_redo(
    scene: bpy.types.Scene, _depsgraph: bpy.types.Depsgraph | None = None
) -> None:
    """Bring session state back in line with what undo just restored.

    An undo step can put the result mesh back to a state that has nothing to do
    with the patch currently open: the faces a re-edit removed may be back, the
    snapshot taken to restore them may be gone, the object being retopped may
    not exist any more. Anything acted on afterwards would be acting on stale
    references, so the active patch is simply dropped and the session returns to
    picking.

    Deliberately touches scene properties only -- no datablock is created,
    freed or edited from a handler.
    """
    state = getattr(scene, "plasticity_retop", None)
    if state is None:
        return

    state.active_face_id = -1
    state.generator_name = ""
    state.num_sides = 0
    state.num_loops = 1
    # The snapshot belongs to a mesh state undo has just replaced; restoring it
    # later would overwrite whatever the user undid back to.
    state.editing_committed = False
    state.reedit_removed_faces = 0
    state.reedit_backup_mesh = ""
    state.reedit_result_object = ""

    if state.session_active:
        session_obj = bpy.data.objects.get(state.session_object_name)
        if session_obj is None:
            state.session_object_name = ""
            state.session_phase = 'OBJECT'
            state.committed_patch_count = 0
        elif state.session_phase == 'ADJUST':
            state.session_phase = 'PATCH'


def _register_handlers() -> None:
    _unregister_handlers()  # never stack duplicates across an addon reload
    bpy.app.handlers.undo_post.append(_on_undo_redo)
    bpy.app.handlers.redo_post.append(_on_undo_redo)


def _unregister_handlers() -> None:
    for handlers in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        for handler in list(handlers):
            # By name: a module reload leaves the previous function object
            # registered, and it is no longer identical to this one.
            if getattr(handler, "__name__", "") == "_on_undo_redo":
                handlers.remove(handler)


CLASSES = (
    RETOP_OT_session,
    RETOP_OT_end_session,
    RETOP_OT_commit_patch,
    RETOP_OT_clear_preview,
    RETOP_OT_delete_patch,
    RETOP_OT_match_neighbour,
    RETOP_OT_toggle_see_through,
    RETOP_OT_local_view,
    RETOP_OT_reload_addon,
)


_addon_keymaps: list[tuple[bpy.types.KeyMap, bpy.types.KeyMapItem]] = []


def _register_keymaps() -> None:
    """Take over '/' in the 3D view.

    The override is unconditional because the binding can't follow a scene
    property; when "Keep Retopo in Isolate" is off, RETOP_OT_local_view just
    forwards to view3d.localview and nothing about '/' changes.
    """
    _unregister_keymaps()
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return  # background/headless Blender has no addon keyconfig
    km = keyconfig.keymaps.new(name='3D View', space_type='VIEW_3D')
    for key in ('SLASH', 'NUMPAD_SLASH'):
        kmi = km.keymap_items.new(RETOP_OT_local_view.bl_idname, key, 'PRESS')
        _addon_keymaps.append((km, kmi))
    # Alt+X, not Alt+Z: Alt+Z is Blender's own X-ray and taking it over cost
    # more than it gave. This is a different thing anyway -- it decides whether
    # the *retopology* draws through the rest of the scene, and leaves the
    # viewport's X-ray alone.
    kmi = km.keymap_items.new(RETOP_OT_toggle_see_through.bl_idname, 'X', 'PRESS', alt=True)
    _addon_keymaps.append((km, kmi))


def _unregister_keymaps() -> None:
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass  # the keymap can already be gone on a full reload
    _addon_keymaps.clear()


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _register_handlers()
    _register_keymaps()


def unregister() -> None:
    # A session could still be running (e.g. Reload Addon Only was clicked
    # mid-session); leaving its draw handler behind would leak an overlay that
    # nothing can remove afterwards.
    overlay.disable()
    _unregister_keymaps()
    _unregister_handlers()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
