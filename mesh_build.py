"""Build/update the preview object shown while tweaking a patch, and bake a
confirmed preview into the persistent per-source-object retopology result
mesh.

Stitching adjacent patches: only a patch's *corner* vertices are guaranteed
to be exact, un-resampled source-mesh vertices, so they are the only points
safe to weld across neighboring patches purely by identity (the same source
vertex index always maps to the same welded result vertex). Interior
boundary points are span-dependent resample points that only coincide
between two patches when their spans happen to match exactly along the
shared edge; blindly proximity-welding them (e.g. bmesh.ops.remove_doubles)
can silently merge unrelated points and drop faces, so we deliberately do
NOT do that here. To actually get matching spans (and therefore a fully
welded, seam-free result), see the span propagation registry below: every
commit records, per pair of corner vertex ids, the span used along that
boundary; generating a new patch looks up its own corner pairs in that
registry and uses any match as its default span for that direction.

The visual "push off the surface" used to see the preview clearly is done
with a non-destructive Displace modifier on the preview object, not baked
into its mesh data -- so Commit (which reads the preview's base mesh, not
its modifier-evaluated geometry) always bakes the true, un-offset position.
"""
import bpy
import bmesh
import mathutils
import json

from . import state as state_mod

PREVIEW_OBJ_NAME = "RetopPreview"
RESULT_NAME_SUFFIX = "_Retop"
OFFSET_MODIFIER_NAME = "RetopPreviewOffset"
RESULT_OFFSET_MODIFIER_NAME = "RetopResultOffset"
AUTO_OFFSET_RATIO = 0.001  # of the source object's bounding-box diagonal
PREVIEW_MATERIAL_NAME = "RetopPreviewMaterial"
RESULT_MATERIAL_NAME = "RetopResultMaterial"
RESULT_DIM_MATERIAL_NAME = "RetopResultMaterialDim"
COLLECTION_NAME = "Retop"
SOURCE_VID_ATTR = "retop_source_vid"
BOUNDARY_ATTR = "retop_is_boundary"
SPAN_REGISTRY_PROP = "retop_side_spans"
NO_SOURCE = -1


def result_object_name_for(source_obj):
    return f"{source_obj.name}{RESULT_NAME_SUFFIX}"


def _span_key(corner_a, corner_b):
    lo, hi = (corner_a, corner_b) if corner_a <= corner_b else (corner_b, corner_a)
    return f"{lo}_{hi}"


def get_span_registry(result_obj):
    """{ "cornerA_cornerB": span_int } for every committed patch side, keyed
    by the (order-independent) pair of corner source-vertex ids at its ends.
    Persisted as a JSON string custom property so it survives save/reload
    without needing a separate in-memory cache.
    """
    raw = result_obj.get(SPAN_REGISTRY_PROP)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def save_span_registry(result_obj, registry):
    result_obj[SPAN_REGISTRY_PROP] = json.dumps(registry)


def lookup_span(registry, corner_a, corner_b):
    return registry.get(_span_key(corner_a, corner_b))


def lookup_propagated_span(source_obj, corner_a, corner_b):
    """Convenience for operators.py: look up a side's span directly from the
    source object, without the caller needing to know about the result
    object / registry plumbing. Returns None if there's no committed result
    yet, or no neighboring patch has used that edge.
    """
    result_obj = bpy.data.objects.get(result_object_name_for(source_obj))
    if result_obj is None:
        return None
    return lookup_span(get_span_registry(result_obj), corner_a, corner_b)


def register_patch_spans(source_obj, corner_source_ids, spans_per_side):
    """Record the span used along each side of a just-committed patch, so
    future neighboring patches can propagate it. No-op if the result object
    doesn't exist yet (shouldn't happen right after a commit, but be safe).
    """
    result_obj = bpy.data.objects.get(result_object_name_for(source_obj))
    if result_obj is None:
        return
    registry = get_span_registry(result_obj)
    n = len(corner_source_ids)
    for i in range(n):
        a = corner_source_ids[i]
        b = corner_source_ids[(i + 1) % n]
        registry[_span_key(a, b)] = spans_per_side[i]
    save_span_registry(result_obj, registry)


def get_or_create_collection(context):
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION_NAME)
        context.scene.collection.children.link(coll)
    return coll


def _preview_material():
    mat = bpy.data.materials.get(PREVIEW_MATERIAL_NAME)
    if mat is None:
        mat = bpy.data.materials.new(PREVIEW_MATERIAL_NAME)
        mat.use_nodes = True
    return mat


def _result_material(name=RESULT_MATERIAL_NAME):
    """Result meshes need two materials, not one: the mesh being worked on and
    the other retop meshes shown alongside it carry different alphas, and a
    single shared material can only hold one.
    """
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
    return mat


def _apply_material_appearance(mat, color, alpha):
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = alpha

    # Transparency in Material Preview / Rendered viewport shading, across
    # the property name used by different Blender versions.
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = 'BLENDED' if alpha < 1.0 else 'DITHERED'
    elif hasattr(mat, "blend_method"):
        mat.blend_method = 'BLEND' if alpha < 1.0 else 'OPAQUE'

    mat.diffuse_color = (*color, alpha)


def _apply_offset_modifier(obj, offset):
    mod = obj.modifiers.get(OFFSET_MODIFIER_NAME)
    if offset == 0.0:
        if mod is not None:
            obj.modifiers.remove(mod)
        return
    if mod is None:
        mod = obj.modifiers.new(OFFSET_MODIFIER_NAME, 'DISPLACE')
        mod.texture = None
        mod.direction = 'NORMAL'
        mod.mid_level = 0.0
    mod.strength = offset


def refresh_preview_appearance(context):
    """Re-apply color/alpha/offset settings to the current preview object
    without touching its geometry -- cheap, called from property callbacks.
    """
    obj = bpy.data.objects.get(PREVIEW_OBJ_NAME)
    if obj is None:
        return
    state = context.scene.plasticity_retop
    mat = _preview_material()
    _apply_material_appearance(mat, tuple(state.preview_color), state.preview_alpha)
    obj.color = (*state.preview_color, state.preview_alpha)
    _apply_offset_modifier(obj, state.preview_offset)


def ensure_result_object(context, source_obj):
    """Return the retop result object for `source_obj`, creating an empty one
    if it doesn't exist yet. Called when entering a retop session (so there's
    something to highlight from the start) and by commit.
    """
    result_name = result_object_name_for(source_obj)
    result_obj = bpy.data.objects.get(result_name)
    if result_obj is not None:
        return result_obj

    coll = get_or_create_collection(context)
    mesh = bpy.data.meshes.new(result_name)
    result_obj = bpy.data.objects.new(result_name, mesh)
    coll.objects.link(result_obj)
    result_obj.matrix_world = mathutils.Matrix.Identity(4)
    mesh.materials.append(_result_material())
    # Distinct color from the raw CAD mesh and from the (orange) in-progress
    # preview; the emphasized in-front/wireframe look is only turned on while
    # a retop session is open on this object (see set_result_highlight), so it
    # doesn't visually dominate the viewport once you've moved on.
    _resting_result_appearance(result_obj, tuple(context.scene.plasticity_retop.result_color))
    _apply_result_offset(context, result_obj)
    return result_obj


def source_object_for_result(result_obj):
    """The Plasticity mesh a result object was built from, or None."""
    if not result_obj.name.endswith(RESULT_NAME_SUFFIX):
        return None
    return bpy.data.objects.get(result_obj.name[:-len(RESULT_NAME_SUFFIX)])


def _auto_offset_for(source_obj):
    """A z-fighting offset proportional to the model, so it works unchanged on
    a 2mm fillet and on a 3m part without anyone typing a magic number.
    """
    if source_obj is None:
        return 0.0
    dims = source_obj.dimensions
    diagonal = mathutils.Vector((dims.x, dims.y, dims.z)).length
    return diagonal * AUTO_OFFSET_RATIO


def _apply_result_offset(context, result_obj):
    """Push the result mesh off the CAD surface along its normals, purely so
    the two don't z-fight. Non-destructive (a Displace modifier) and flagged
    show_render=False, so the geometry that actually gets rendered/exported is
    the true, un-offset one sitting exactly on the surface.
    """
    state = context.scene.plasticity_retop
    offset = state_mod.to_blender_units(state, state.result_offset)
    if offset <= 0.0:
        offset = _auto_offset_for(source_object_for_result(result_obj))

    mod = result_obj.modifiers.get(RESULT_OFFSET_MODIFIER_NAME)
    if offset <= 0.0:
        if mod is not None:
            result_obj.modifiers.remove(mod)
        return
    if mod is None:
        mod = result_obj.modifiers.new(RESULT_OFFSET_MODIFIER_NAME, 'DISPLACE')
        mod.texture = None
        mod.direction = 'NORMAL'
        mod.mid_level = 0.0
    mod.strength = offset
    mod.show_render = False


def _apply_result_look(result_obj, color, alpha, material_name, in_front, wire):
    mat = _result_material(material_name)
    _apply_material_appearance(mat, color, alpha)
    if result_obj.data.materials:
        result_obj.data.materials[0] = mat
    else:
        result_obj.data.materials.append(mat)
    result_obj.color = (*color, alpha)
    result_obj.show_in_front = in_front
    result_obj.show_wire = wire
    result_obj.show_all_edges = wire


def _resting_result_appearance(result_obj, color):
    """Neutral, always-on look: same color so it still reads as "retopped",
    but opaque and without the in-front/wireframe emphasis used in-session.
    """
    _apply_result_look(result_obj, color, 1.0, RESULT_MATERIAL_NAME, in_front=False, wire=False)


def iter_result_objects(context):
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None:
        return []
    return [o for o in coll.objects if o.name.endswith(RESULT_NAME_SUFFIX)]


def refresh_result_appearance(context):
    """Apply the right look to every retop result mesh in one pass:

    - the one being worked on: full Result Appearance alpha, drawn in front
      with its wireframe, so the topology under the cursor stays readable;
    - the others, while a session is running and Show All Retopo is on:
      same color at the dimmed alpha, wireframe but not in front, so previously
      retopped parts stay visible for context without stealing attention;
    - everything else: resting (opaque, no emphasis).

    Called on every session transition and from the appearance property
    callbacks.
    """
    state = context.scene.plasticity_retop
    color = tuple(state.result_color)
    active_name = ""
    if state.session_active and state.session_object_name:
        source_obj = bpy.data.objects.get(state.session_object_name)
        if source_obj is not None:
            active_name = result_object_name_for(source_obj)

    for result_obj in iter_result_objects(context):
        _apply_result_offset(context, result_obj)

        if result_obj.name == active_name:
            _apply_result_look(result_obj, color, state.result_alpha,
                               RESULT_MATERIAL_NAME, in_front=True, wire=True)
        elif state.session_active and state.highlight_all_results:
            _apply_result_look(result_obj, color, state.inactive_result_alpha,
                               RESULT_DIM_MATERIAL_NAME, in_front=False, wire=True)
        else:
            _resting_result_appearance(result_obj, color)


def set_result_highlight(context, source_obj, active):
    """Kept as the call site used by session transitions; the actual decision
    for every result mesh is made by refresh_result_appearance from session
    state, so all of them stay consistent with each other.
    """
    refresh_result_appearance(context)


def update_preview_object(context, source_obj, result, corner_source_ids=None):
    coll = get_or_create_collection(context)
    obj = bpy.data.objects.get(PREVIEW_OBJ_NAME)
    if obj is None:
        mesh = bpy.data.meshes.new(PREVIEW_OBJ_NAME)
        obj = bpy.data.objects.new(PREVIEW_OBJ_NAME, mesh)
        coll.objects.link(obj)

    mesh = obj.data
    mesh.clear_geometry()
    verts = [tuple(v) for v in result.verts]
    mesh.from_pydata(verts, [], result.faces)
    mesh.update()

    uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            vi = mesh.loops[li].vertex_index
            uv_layer.data[li].uv = result.uvs[vi]

    source_vid_attr = mesh.attributes.get(SOURCE_VID_ATTR)
    if source_vid_attr is None:
        source_vid_attr = mesh.attributes.new(SOURCE_VID_ATTR, 'INT', 'POINT')
    values = [NO_SOURCE] * len(mesh.vertices)
    if corner_source_ids:
        for local_idx, source_idx in zip(result.corner_local_indices, corner_source_ids):
            values[local_idx] = source_idx
    source_vid_attr.data.foreach_set("value", values)

    boundary_attr = mesh.attributes.get(BOUNDARY_ATTR)
    if boundary_attr is None:
        boundary_attr = mesh.attributes.new(BOUNDARY_ATTR, 'BOOLEAN', 'POINT')
    boundary_values = [False] * len(mesh.vertices)
    for local_idx in result.boundary_local_indices:
        boundary_values[local_idx] = True
    boundary_attr.data.foreach_set("value", boundary_values)

    if len(mesh.materials) == 0:
        mesh.materials.append(_preview_material())

    obj.matrix_world = source_obj.matrix_world.copy()
    obj.hide_render = True
    # Draw as an overlay on top of the (possibly occluding) source CAD mesh,
    # with its wireframe visible, so the grid being built is easy to read
    # while tweaking spans.
    obj.show_in_front = True
    obj.show_wire = True
    obj.show_all_edges = True

    refresh_preview_appearance(context)
    return obj


def clear_preview_object():
    obj = bpy.data.objects.get(PREVIEW_OBJ_NAME)
    if obj is None:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def commit_preview_to_result(context, source_obj):
    """Bake the current preview object's *base* geometry (i.e. without the
    cosmetic offset modifier, in world space) into the persistent retop
    result mesh for `source_obj`, welding only corner vertices that share
    the same source Plasticity vertex id with geometry already present.
    Returns (result_obj, error_message_or_None).
    """
    preview_obj = bpy.data.objects.get(PREVIEW_OBJ_NAME)
    if preview_obj is None or len(preview_obj.data.polygons) == 0:
        return None, "No preview to commit"

    result_obj = ensure_result_object(context, source_obj)

    src_mesh = preview_obj.data  # base mesh: offset modifier is NOT evaluated here
    world_matrix = preview_obj.matrix_world.copy()

    bm = bmesh.new()
    bm.from_mesh(result_obj.data)
    uv_layer = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
    result_vid_layer = bm.verts.layers.int.get(SOURCE_VID_ATTR) or bm.verts.layers.int.new(SOURCE_VID_ATTR)
    result_boundary_layer = bm.verts.layers.int.get(BOUNDARY_ATTR) or bm.verts.layers.int.new(BOUNDARY_ATTR)

    # existing source-vertex-id -> bm.vert already in the result mesh
    existing_by_source_id = {}
    for v in bm.verts:
        sid = v[result_vid_layer]
        if sid != NO_SOURCE:
            existing_by_source_id[sid] = v

    src_uv_layer = src_mesh.uv_layers.get("UVMap")
    src_vid_attr = src_mesh.attributes.get(SOURCE_VID_ATTR)
    src_vids = [NO_SOURCE] * len(src_mesh.vertices)
    if src_vid_attr is not None:
        src_vid_attr.data.foreach_get("value", src_vids)

    src_boundary_attr = src_mesh.attributes.get(BOUNDARY_ATTR)
    src_boundary = [False] * len(src_mesh.vertices)
    if src_boundary_attr is not None:
        src_boundary_attr.data.foreach_get("value", src_boundary)

    vert_map = {}
    for v in src_mesh.vertices:
        sid = src_vids[v.index]
        if sid != NO_SOURCE and sid in existing_by_source_id:
            vert_map[v.index] = existing_by_source_id[sid]
            continue
        world_co = world_matrix @ v.co
        new_vert = bm.verts.new(world_co)
        new_vert[result_vid_layer] = sid
        new_vert[result_boundary_layer] = 1 if src_boundary[v.index] else 0
        if sid != NO_SOURCE:
            existing_by_source_id[sid] = new_vert
        vert_map[v.index] = new_vert
    bm.verts.ensure_lookup_table()

    skipped = 0
    for poly in src_mesh.polygons:
        loop_range = range(poly.loop_start, poly.loop_start + poly.loop_total)
        loop_verts = [vert_map[src_mesh.loops[li].vertex_index] for li in loop_range]
        try:
            new_face = bm.faces.new(loop_verts)
        except ValueError:
            skipped += 1
            continue
        if src_uv_layer:
            for loop, li in zip(new_face.loops, loop_range):
                loop[uv_layer].uv = src_uv_layer.data[li].uv

    # Weld coincident boundary vertices only (never interior/reprojected
    # ones): with propagation keeping spans equal along a shared edge, the
    # new patch's boundary resample points land (almost) exactly on the
    # neighbor's already-committed boundary points, so this closes the
    # "positions match but topology doesn't" gap propagation alone leaves.
    # Scoping to boundary-flagged verts and a tiny epsilon keeps this safe --
    # see the module docstring for why an unscoped weld is dangerous.
    boundary_verts = [v for v in bm.verts if v[result_boundary_layer] == 1]
    retop_state = context.scene.plasticity_retop
    weld_distance = state_mod.to_blender_units(retop_state, retop_state.boundary_weld_distance)
    if len(boundary_verts) > 1 and weld_distance > 0.0:
        bmesh.ops.remove_doubles(bm, verts=boundary_verts, dist=weld_distance)

    bm.to_mesh(result_obj.data)
    result_obj.data.update()
    bm.free()

    clear_preview_object()

    if skipped:
        return result_obj, None  # committed; a few faces already existed and were skipped
    return result_obj, None
