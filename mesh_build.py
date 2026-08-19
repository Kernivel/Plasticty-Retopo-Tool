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

Re-editing a committed patch: each baked face records which Plasticity face it
came from (PATCH_ID_ATTR) and each patch records the spans it was built with
(PATCH_SPANS_PROP), so a patch can be picked again, come back with its own
spans, and be committed a second time -- replacing its old faces instead of
doubling up on them.

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
# Plasticity face ids arrive from the bridge as int32 (client.py decodes them
# with dtype=np.int32), so a Blender INT attribute holds them exactly.
PATCH_ID_ATTR = "retop_patch_face_id"
SPAN_REGISTRY_PROP = "retop_side_spans"
PATCH_SPANS_PROP = "retop_patch_spans"
ADOPTION_PROP = "retop_patch_adoption"
SNAPSHOT_NAME_SUFFIX = "_ReeditBackup"
NO_SOURCE = -1
NO_PATCH = -1


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


# --- committed patches: which ones are in the result mesh, and with what spans ---
#
# Every face baked into the result mesh carries the Plasticity face id of the
# patch it came from (PATCH_ID_ATTR), and the settings used to build that patch
# are stored alongside it (PATCH_SPANS_PROP). Together they make a committed
# patch re-selectable: picking it again restores exactly the spans it was built
# with, and committing again *replaces* its faces instead of piling a second
# copy on top of them (see commit_preview_to_result's `face_id`).


def get_patch_settings_table(result_obj):
    """{ "<face_id>": {"span_u": .., "span_v": .., "span": .., "generator": ..} }
    for every committed patch. JSON custom property, like the span registry.
    """
    raw = result_obj.get(PATCH_SPANS_PROP)
    if not raw:
        return {}
    try:
        table = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return table if isinstance(table, dict) else {}


def save_patch_settings_table(result_obj, table):
    result_obj[PATCH_SPANS_PROP] = json.dumps(table)


def register_patch_settings(source_obj, face_id, span_u, span_v, span, generator_name):
    """Record what a just-committed patch was built with, so re-selecting it
    later comes back with those exact spans rather than recomputed defaults.
    """
    result_obj = bpy.data.objects.get(result_object_name_for(source_obj))
    if result_obj is None:
        return
    table = get_patch_settings_table(result_obj)
    table[str(face_id)] = {
        "span_u": span_u,
        "span_v": span_v,
        "span": span,
        "generator": generator_name,
    }
    save_patch_settings_table(result_obj, table)


def lookup_patch_settings(source_obj, face_id):
    """The settings a patch was committed with, or None if it was never
    committed (or predates this bookkeeping).
    """
    result_obj = bpy.data.objects.get(result_object_name_for(source_obj))
    if result_obj is None:
        return None
    return get_patch_settings_table(result_obj).get(str(face_id))


def _patch_ids_of_faces(mesh):
    attr = mesh.attributes.get(PATCH_ID_ATTR)
    if attr is None or len(mesh.polygons) == 0:
        return []
    values = [NO_PATCH] * len(mesh.polygons)
    attr.data.foreach_get("value", values)
    return values


def committed_face_ids(source_obj):
    """Set of Plasticity face ids currently present in `source_obj`'s result
    mesh. Read from the mesh itself (not from the settings table), so a patch
    the user deleted by hand in Edit Mode stops counting as committed.
    """
    result_obj = bpy.data.objects.get(result_object_name_for(source_obj))
    if result_obj is None:
        return set()
    return {fid for fid in _patch_ids_of_faces(result_obj.data) if fid != NO_PATCH}


def is_patch_committed(source_obj, face_id):
    return face_id in committed_face_ids(source_obj)


def _source_patch_lookup(source_obj, result_obj):
    """Return f(co) -> Plasticity face id for a point of `result_obj`'s mesh,
    by nearest source polygon, or None if the source has no usable geometry.

    This is how retopology that carries no patch id is matched back to the CAD
    face it belongs to: the retopology sits on the surface, so the closest
    source polygon to one of its points names the patch.
    """
    from . import geometry
    from . import patch_data

    src_mesh = source_obj.data
    if len(src_mesh.polygons) == 0:
        return None

    face_id_of_poly, _ = patch_data.polygon_face_ids(src_mesh)
    bvh, tri_poly = geometry.build_bvh_with_polygon_map(src_mesh)
    # The BVH is in the source object's local space; result geometry is stored
    # in world space (i.e. under an identity object matrix, unless the user
    # moved the result object since).
    to_source_local = source_obj.matrix_world.inverted() @ result_obj.matrix_world

    def face_id_at(co):
        hit = bvh.find_nearest(to_source_local @ co)
        if hit is None or hit[2] is None:
            return None
        return face_id_of_poly[tri_poly[hit[2]]]

    return face_id_at


def adopt_untracked_faces(source_obj):
    """Tag result faces that carry no patch id with the Plasticity face they
    sit on, and return how many were tagged.

    Needed for result meshes committed before patch tracking existed (or by
    hand): without a face id nothing links them to a patch, so re-picking that
    patch can't know it already has geometry to replace.

    Votes are collected from the face centre (weighted, it's the point most
    safely *inside* the patch) plus its vertices, and a face is only *tagged* on
    a strict majority -- a tag is permanent, so it had better be right.
    Removing a patch for a re-edit uses the looser rule in
    remove_patch_from_result: that one is visible on screen and undoable.
    """
    result_obj = bpy.data.objects.get(result_object_name_for(source_obj))
    if result_obj is None:
        return 0
    mesh = result_obj.data
    if len(mesh.polygons) == 0:
        return 0

    existing = _patch_ids_of_faces(mesh)
    if existing and NO_PATCH not in existing:
        return 0  # everything already tagged: nothing to do
    if not existing:
        existing = [NO_PATCH] * len(mesh.polygons)

    face_id_at = _source_patch_lookup(source_obj, result_obj)
    if face_id_at is None:
        return 0

    CENTRE_WEIGHT = 2
    adopted = 0
    for poly in mesh.polygons:
        if existing[poly.index] != NO_PATCH:
            continue

        votes = {}
        centre_id = face_id_at(poly.center)
        if centre_id is not None:
            votes[centre_id] = CENTRE_WEIGHT
        for vi in poly.vertices:
            fid = face_id_at(mesh.vertices[vi].co)
            if fid is not None:
                votes[fid] = votes.get(fid, 0) + 1

        if not votes:
            continue
        best_id, best_votes = max(votes.items(), key=lambda kv: kv[1])
        if best_votes * 2 > sum(votes.values()):  # strict majority only
            existing[poly.index] = best_id
            adopted += 1

    if adopted == 0:
        return 0

    attr = mesh.attributes.get(PATCH_ID_ATTR)
    if attr is None:
        attr = mesh.attributes.new(PATCH_ID_ATTR, 'INT', 'FACE')
    attr.data.foreach_set("value", existing)
    mesh.update()
    result_obj[ADOPTION_PROP] = 1
    print(f"[Plasticity Retop] Adopted {adopted} pre-existing face(s) of "
          f"'{result_obj.name}' into patch tracking")
    return adopted


# --- taking a patch out for a re-edit, reversibly ---
#
# Clicking a patch that already has geometry removes that geometry immediately,
# so the viewport shows the patch being rebuilt instead of a new grid stacked on
# the old one. The result mesh is snapshotted into a spare mesh datablock first,
# and discarding the re-edit swaps the snapshot back -- so nothing is lost by
# Esc, by leaving the object, or by ending the session mid-edit.


def _snapshot_result_mesh(result_obj):
    backup = result_obj.data.copy()
    backup.name = f"{result_obj.name}{SNAPSHOT_NAME_SUFFIX}"
    # It has no users while it's just a snapshot; without this it can be purged.
    backup.use_fake_user = True
    return backup.name


def restore_result_snapshot(result_obj_name, backup_mesh_name):
    """Put a snapshot back as `result_obj_name`'s mesh. Returns True if it did."""
    result_obj = bpy.data.objects.get(result_obj_name)
    backup = bpy.data.meshes.get(backup_mesh_name)
    if result_obj is None or backup is None:
        return False

    current = result_obj.data
    current_name = current.name
    result_obj.data = backup
    backup.use_fake_user = False
    if current.users == 0:
        bpy.data.meshes.remove(current)
        backup.name = current_name
    return True


def drop_result_snapshot(backup_mesh_name):
    """Throw away a snapshot (the re-edit was committed, so it's not needed)."""
    backup = bpy.data.meshes.get(backup_mesh_name)
    if backup is None:
        return
    backup.use_fake_user = False
    if backup.users == 0:
        bpy.data.meshes.remove(backup)


def purge_stale_snapshots(keep_name=""):
    """Delete snapshot meshes nothing is using any more, and return how many.

    A snapshot carries a fake user so it can't be purged while a re-edit is in
    flight, which also means an interrupted one (undo rolled the re-edit back,
    Blender crashed, the addon was reloaded) would sit in the file forever.
    Called when entering an object -- a structural moment that gets its own
    undo step -- never from a hover or a callback.
    """
    stale = [mesh for mesh in bpy.data.meshes
             if mesh.name.endswith(SNAPSHOT_NAME_SUFFIX)
             and mesh.name != keep_name
             and mesh.users <= (1 if mesh.use_fake_user else 0)]
    for mesh in stale:
        mesh.use_fake_user = False
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    return len(stale)


def remove_patch_from_result(source_obj, face_id):
    """Take patch `face_id`'s existing geometry out of the result mesh, after
    snapshotting it. Returns (removed_face_count, snapshot_mesh_name); the name
    is "" when nothing was removed (and no snapshot was taken).

    Faces are picked by their patch id, plus -- for faces that carry none --
    whichever ones sit on this patch by their centre alone. That looser rule is
    deliberate here: the removal happens on click, so a wrong guess is visible
    straight away and restore_result_snapshot undoes it, whereas a face left
    behind is exactly the "two overlapping surfaces" the tag was meant to
    prevent.
    """
    result_obj = bpy.data.objects.get(result_object_name_for(source_obj))
    if result_obj is None:
        return 0, ""
    mesh = result_obj.data
    if len(mesh.polygons) == 0:
        return 0, ""

    ids = _patch_ids_of_faces(mesh) or [NO_PATCH] * len(mesh.polygons)
    targets = {i for i, fid in enumerate(ids) if fid == face_id}
    untagged = [i for i, fid in enumerate(ids) if fid == NO_PATCH]
    if untagged:
        face_id_at = _source_patch_lookup(source_obj, result_obj)
        if face_id_at is not None:
            for i in untagged:
                if face_id_at(mesh.polygons[i].center) == face_id:
                    targets.add(i)

    if not targets:
        return 0, ""

    backup_name = _snapshot_result_mesh(result_obj)

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    # context='FACES' drops the patch's own vertices but keeps the ones a
    # neighbouring patch still uses, so the rebuilt grid welds back onto them.
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in targets], context='FACES')
    bm.to_mesh(mesh)
    mesh.update()
    bm.free()

    return len(targets), backup_name


def get_or_create_collection(context):
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION_NAME)
        context.scene.collection.children.link(coll)
    return coll


# --- datablock creation and undo ---
#
# Creating or freeing an ID (material, mesh, object, collection) outside of an
# operator that pushes an undo step is what makes Ctrl+Z crash Blender: the
# undo state restored around it doesn't know about the datablock, and the
# depsgraph then walks an object whose data or material array was freed under
# it. So ID creation happens ONLY on the session's structural moments
# (ensure_result_object, the first update_preview_object of a session) -- never
# from a property update callback, a draw handler or a hover.
#
# Everything reached from an update callback (the refresh_*_appearance
# functions) therefore looks materials up and quietly does without if they
# aren't there yet.


def _create_material(name):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
    return mat


def _existing_material(name):
    """Look up a material without ever creating one -- safe from any context."""
    return bpy.data.materials.get(name)


def ensure_materials():
    """Create the addon's materials up front, from a context allowed to create
    datablocks. Result meshes need two of them, not one: the mesh being worked
    on and the other retop meshes shown alongside it carry different alphas,
    and a single shared material can only hold one.
    """
    _create_material(PREVIEW_MATERIAL_NAME)
    _create_material(RESULT_MATERIAL_NAME)
    _create_material(RESULT_DIM_MATERIAL_NAME)


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
    mat = _existing_material(PREVIEW_MATERIAL_NAME)
    if mat is not None:
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
    ensure_materials()
    mesh = bpy.data.meshes.new(result_name)
    result_obj = bpy.data.objects.new(result_name, mesh)
    coll.objects.link(result_obj)
    result_obj.matrix_world = mathutils.Matrix.Identity(4)
    mesh.materials.append(_create_material(RESULT_MATERIAL_NAME))
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
    # Get-only: this runs from appearance property callbacks, which must not
    # create datablocks (see the note above _create_material).
    mat = _existing_material(material_name)
    if mat is not None:
        _apply_material_appearance(mat, color, alpha)
        if result_obj.data.materials:
            if result_obj.data.materials[0] is not mat:
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


def orphan_result_objects(context):
    """Retopology meshes whose source object no longer exists under the name
    they were built from -- typically because the CAD object was renamed or
    re-imported since. They're invisible to everything here (patch tracking,
    re-editing, span propagation all resolve through `<Source>_Retop`), so a
    session on the renamed object silently starts a *second* result mesh and
    the two overlap in the viewport. Surfaced in the panel for that reason.
    """
    return [o for o in iter_result_objects(context)
            if source_object_for_result(o) is None and len(o.data.polygons) > 0]


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


def ensure_preview_object(context):
    """The preview object, created once and then reused for the whole session.

    Hovering used to create it and delete it again on every mouse move, which
    is the single worst thing an addon can do to Blender's undo: a Ctrl+Z
    landing between two of those steps restores a state where the object or its
    mesh has been freed, and Blender crashes rebuilding the depsgraph. Now the
    object outlives the hover and only its geometry is rewritten.
    """
    obj = bpy.data.objects.get(PREVIEW_OBJ_NAME)
    if obj is not None:
        return obj

    coll = get_or_create_collection(context)
    ensure_materials()
    mesh = bpy.data.meshes.new(PREVIEW_OBJ_NAME)
    obj = bpy.data.objects.new(PREVIEW_OBJ_NAME, mesh)
    coll.objects.link(obj)
    return obj


def update_preview_object(context, source_obj, result, corner_source_ids=None):
    obj = ensure_preview_object(context)
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
        preview_mat = _existing_material(PREVIEW_MATERIAL_NAME)
        if preview_mat is not None:
            mesh.materials.append(preview_mat)

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


def has_preview():
    """True when there is preview geometry to commit or discard. The preview
    object itself sticks around empty between patches, so its mere existence
    doesn't mean anything -- its polygons do.
    """
    obj = bpy.data.objects.get(PREVIEW_OBJ_NAME)
    return obj is not None and len(obj.data.polygons) > 0


def clear_preview_object():
    """Empty the preview without deleting anything.

    Used everywhere inside a session (hover moved off a patch, patch committed,
    preview discarded): freeing the object here would put ID churn back on the
    hover path, which is what made undo crash. remove_preview_object does the
    real teardown, once, when the session ends.
    """
    obj = bpy.data.objects.get(PREVIEW_OBJ_NAME)
    if obj is None:
        return
    obj.data.clear_geometry()
    obj.data.update()


def remove_preview_object():
    """Drop the preview object for good -- session teardown only."""
    obj = bpy.data.objects.get(PREVIEW_OBJ_NAME)
    if obj is None:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def commit_preview_to_result(context, source_obj, face_id=None):
    """Bake the current preview object's *base* geometry (i.e. without the
    cosmetic offset modifier, in world space) into the persistent retop
    result mesh for `source_obj`, welding only corner vertices that share
    the same source Plasticity vertex id with geometry already present.
    Returns (result_obj, error_message_or_None).

    `face_id` is the Plasticity face id of the patch being committed. It is
    stamped onto every face this call adds, and any faces already carrying it
    are removed first -- that's what makes re-selecting a committed patch and
    changing its spans a *replacement* rather than a second copy layered on
    top of the first. Deleting with context='FACES' is deliberate: it drops the
    patch's own interior/boundary vertices but keeps the ones still used by a
    neighbouring patch's faces, so the neighbours stay welded to the new grid.
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
    patch_id_layer = bm.faces.layers.int.get(PATCH_ID_ATTR)
    if patch_id_layer is None:
        # A result mesh committed before patch tracking existed: a fresh int
        # layer would give every one of its faces id 0, which would then read
        # as "patch 0 is committed" and let a re-edit of face 0 delete all of
        # them. Mark them as belonging to no known patch instead.
        patch_id_layer = bm.faces.layers.int.new(PATCH_ID_ATTR)
        for face in bm.faces:
            face[patch_id_layer] = NO_PATCH

    # Drop a previous version of this same patch before anything else, so the
    # vertex bookkeeping below only ever sees geometry that survives.
    if face_id is not None:
        stale = [f for f in bm.faces if f[patch_id_layer] == face_id]
        if stale:
            bmesh.ops.delete(bm, geom=stale, context='FACES')
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

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
        new_face[patch_id_layer] = NO_PATCH if face_id is None else face_id
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
