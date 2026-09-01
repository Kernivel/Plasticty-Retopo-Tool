"""Run inside Blender: blender --background --python tests/test_shading_ngon.py

Covers the four things added in 0.16:
  - smooth shading with creases marked only on patch borders that really turn
  - the Show Wireframe / wireframe-opacity settings
  - mirroring the Plasticity Inbox collection hierarchy under Retop
  - N-gon mode: one face per patch, boundary densified by curvature
"""
import os
import sys
import importlib
import math

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy
import mathutils

pr = importlib.import_module(os.path.basename(_ADDON_DIR))

FAILURES = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


try:
    pr.unregister()
except Exception:
    pass
pr.register()

V = mathutils.Vector


# ===========================================================================
# N-gon generator: segment counts come from curvature, not length
# ===========================================================================
ngon = pr.generators.ngon

straight = [V((0.0, 0.0, 0.0)), V((5.0, 0.0, 0.0)), V((10.0, 0.0, 0.0))]
check("a straight side turns 0 degrees however long it is",
      ngon.side_turn_degrees(straight) < 1e-6, ngon.side_turn_degrees(straight))
check("a straight side stays one segment",
      ngon.side_segments(straight, 20.0) == 1, ngon.side_segments(straight, 20.0))

# Quarter circle, finely sampled: ~90 degrees of turn.
arc = [V((math.cos(t), math.sin(t), 0.0))
       for t in [i / 32 * (math.pi / 2) for i in range(33)]]
turn = ngon.side_turn_degrees(arc)
check("a quarter circle turns ~90 degrees", 85.0 < turn < 95.0, f"{turn:.2f}")
# 90 degrees of turn, a vertex kept every 20: 4 of them fire before the arc
# runs out, so 4 segments.
check("a curved side is densified by the angle setting",
      ngon.side_segments(arc, 20.0) == 4, ngon.side_segments(arc, 20.0))
check("a finer curve angle densifies further",
      ngon.side_segments(arc, 5.0) > ngon.side_segments(arc, 20.0),
      f"{ngon.side_segments(arc, 5.0)} vs {ngon.side_segments(arc, 20.0)}")
check("kept points are source boundary vertices, not resampled ones",
      all(any((kept - p).length < 1e-9 for p in arc)
          for kept in ngon.side_points(arc, 20.0)))

# --- the chamfer case: a shallow kink in the middle of an otherwise straight
# side. sides.py does not call it a corner (it deviates less than
# corner_angle_threshold), so it is only preserved if the boundary is selected
# from rather than resampled along. This is the regression photo 2 showed. ---
chamfer_side = [
    V((0.0, 0.0, 0.0)),
    V((1.0, 0.0, 0.0)),
    V((2.0, 0.0, 0.0)),
    V((2.6, 0.4, 0.0)),   # ~34 degrees of deviation: a chamfer, not a corner
    V((3.6, 0.4, 0.0)),
    V((4.6, 0.4, 0.0)),
]
kink_turn = ngon.turn_at(chamfer_side[1], chamfer_side[2], chamfer_side[3])
check("the chamfer kink is shallower than a detected corner",
      kink_turn < 45.0, f"{kink_turn:.1f} degrees")
kept = ngon.side_points(chamfer_side, 20.0)
check("the chamfer vertex itself is kept",
      any((kept_point - chamfer_side[3]).length < 1e-9 for kept_point in kept)
      or any((kept_point - chamfer_side[2]).length < 1e-9 for kept_point in kept),
      [tuple(k) for k in kept])
check("and nothing else on the straight runs is",
      len(kept) == 4, len(kept))
check("a threshold above the kink drops it, as documented",
      len(ngon.side_points(chamfer_side, 90.0)) == 2,
      len(ngon.side_points(chamfer_side, 90.0)))

# A square with one rounded side: three straight sides + the arc above.
square_sides = [
    [V((0.0, 0.0, 0.0)), V((2.0, 0.0, 0.0))],
    [V((2.0, 0.0, 0.0)), V((2.0, 2.0, 0.0))],
    [V((2.0, 2.0, 0.0)), V((0.0, 2.0, 0.0))],
    [V((0.0, 2.0, 0.0)), V((0.0, 0.0, 0.0))],
]
result = pr.generators.NGON.generate(square_sides, {"ngon_angle": 20.0})
check("a flat quad becomes a single face", len(result.faces) == 1, len(result.faces))
check("with one vertex per corner and no duplicates",
      len(result.verts) == 4, len(result.verts))
check("the face is the whole boundary", len(result.faces[0]) == 4, len(result.faces[0]))
check("every vertex is flagged as boundary (all of them weld to neighbours)",
      sorted(result.boundary_local_indices) == list(range(len(result.verts))))
check("one corner index per side", len(result.corner_local_indices) == 4)
check("the segment allocation is reported for span propagation",
      result.side_allocation == [1, 1, 1, 1], result.side_allocation)

curved_sides = [
    square_sides[0],
    [V((2.0, 0.0, 0.0))] + [V((2.0 + math.sin(t), 1.0 - math.cos(t), 0.0))
                            for t in [i / 32 * math.pi for i in range(1, 33)]],
    square_sides[2],
    square_sides[3],
]
curved = pr.generators.NGON.generate(curved_sides, {"ngon_angle": 20.0})
check("a curved side gets extra vertices, the straight ones don't",
      curved.side_allocation[1] > 1 and curved.side_allocation[0] == 1,
      curved.side_allocation)
check("every n-gon vertex lies on the source boundary",
      all(any((v - p).length < 1e-9 for side in curved_sides for p in side)
          for v in curved.verts))
check("the n-gon is still a single face", len(curved.faces) == 1, len(curved.faces))
check("its vertex count is the total segment count",
      len(curved.verts) == sum(curved.side_allocation), len(curved.verts))
check("UVs land in 0..1", all(-1e-6 <= u <= 1.000001 and -1e-6 <= v <= 1.000001
                              for u, v in curved.uvs))


# ===========================================================================
# A two-patch mesh, folded so the shared border is a real crease
# ===========================================================================
def build_folded_object(name, fold_degrees, collection=None):
    """Two 1x1 patches sharing an edge, the second rotated `fold_degrees` out
    of the first's plane. 0 degrees = coplanar, 90 = a hard corner.
    """
    angle = math.radians(fold_degrees)
    verts = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
    ]
    # second patch continues past y=1, folded around the y=1 edge
    dy = math.cos(angle)
    dz = math.sin(angle)
    verts.extend([
        (1.0, 1.0 + dy, dz), (0.0, 1.0 + dy, dz),
    ])
    tris_a = [(0, 1, 2), (0, 2, 3)]
    tris_b = [(3, 2, 4), (3, 4, 5)]

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], tris_a + tris_b)
    mesh.update()
    mesh["groups"] = [0, len(tris_a) * 3, len(tris_a) * 3, len(tris_b) * 3]
    mesh["face_ids"] = [11, 22]

    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.collection).objects.link(obj)
    return obj


def retop_patch(obj, face_id):
    """Pick a patch and commit it, the way a click then Enter does."""
    pr.operators.set_active_patch(bpy.context, obj, face_id)
    return bpy.ops.retop.commit_patch()


state = bpy.context.scene.plasticity_retop

folded = build_folded_object("Folded90", 90.0)
bpy.context.view_layer.objects.active = folded
pr.operators.enter_session_object(bpy.context, folded)
retop_patch(folded, 11)
retop_patch(folded, 22)

result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(folded))
check("committing built a result mesh", result is not None and len(result.data.polygons) > 0,
      len(result.data.polygons) if result else "none")
check("every face is shaded smooth",
      all(poly.use_smooth for poly in result.data.polygons))

sharp_attr = result.data.attributes.get(pr.mesh_build.SHARP_EDGE_ATTR)
check("a sharp_edge attribute was written", sharp_attr is not None)
sharp = [d.value for d in sharp_attr.data] if sharp_attr else []
check("the 90-degree patch border is creased", any(sharp), sum(sharp))

# Every sharp edge must sit between two *different* patches -- an interior edge
# of a single CAD surface is never a crease.
patch_ids = pr.mesh_build._patch_ids_of_faces(result.data)
edge_faces = {}
for poly in result.data.polygons:
    for key in poly.edge_keys:
        edge_faces.setdefault(key, []).append(poly.index)
edge_of_key = {tuple(sorted(e.vertices)): e.index for e in result.data.edges}
interior_sharp = [key for key, faces in edge_faces.items()
                  if len(faces) == 2
                  and patch_ids[faces[0]] == patch_ids[faces[1]]
                  and sharp[edge_of_key[key]]]
check("no crease inside a patch (one patch is one smooth CAD surface)",
      not interior_sharp, interior_sharp)

# Same topology, no fold: the border is tangent, so nothing may be creased.
pr.operators.end_session(bpy.context)
flat = build_folded_object("Folded0", 0.0)
bpy.context.view_layer.objects.active = flat
pr.operators.enter_session_object(bpy.context, flat)
retop_patch(flat, 11)
retop_patch(flat, 22)
flat_result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(flat))
flat_attr = flat_result.data.attributes.get(pr.mesh_build.SHARP_EDGE_ATTR)
flat_sharp = [d.value for d in flat_attr.data] if flat_attr else []
check("a tangent patch border stays smooth", not any(flat_sharp), sum(flat_sharp))

# Turning smooth shading off must undo both halves of the look.
state.result_shade_smooth = False
check("Shade Smooth off flattens the faces",
      not any(poly.use_smooth for poly in result.data.polygons))
sharp_attr = result.data.attributes.get(pr.mesh_build.SHARP_EDGE_ATTR)
check("Shade Smooth off clears the creases too",
      not any(d.value for d in sharp_attr.data))
state.result_shade_smooth = True
sharp_attr = result.data.attributes.get(pr.mesh_build.SHARP_EDGE_ATTR)
check("turning it back on restores them",
      any(d.value for d in sharp_attr.data))

# The angle threshold has to actually decide.
state.sharp_edge_angle = 170.0
sharp_attr = result.data.attributes.get(pr.mesh_build.SHARP_EDGE_ATTR)
check("a threshold above the fold angle leaves the border smooth",
      not any(d.value for d in sharp_attr.data))
state.sharp_edge_angle = 30.0


# ===========================================================================
# Wireframe settings
# ===========================================================================
pr.operators.end_session(bpy.context)
bpy.context.view_layer.objects.active = folded
pr.operators.enter_session_object(bpy.context, folded)

state.result_show_wire = True
pr.mesh_build.refresh_result_appearance(bpy.context)
check("the worked-on result shows its wireframe", result.show_wire, result.show_wire)

# --- see-through: whether the retopology draws over the rest of the scene ---
state.result_see_through = True
check("on, the result is drawn in front of everything", result.show_in_front,
      result.show_in_front)
state.result_see_through = False
check("off, it is occluded like any other object -- the only way to check it "
      "sits on the surface rather than floating off it",
      not result.show_in_front, result.show_in_front)
bpy.ops.retop.toggle_see_through()
check("the operator toggles it back", state.result_see_through is True)
check("and the look follows without another refresh", result.show_in_front)
bpy.ops.retop.toggle_see_through()
check("and toggles it off again", state.result_see_through is False
      and not result.show_in_front)
state.result_see_through = True

bindings = [(kmi.type, kmi.alt, kmi.shift, kmi.idname)
            for _km, kmi in pr.operators._addon_keymaps]
# Shift+X, not Alt+X: Alt+X is the mirror, borrowed from Hard Ops because that
# is the reflex, and symmetry is reached for far more often than the x-ray.
check("the retopo x-ray is on Shift+X",
      ('X', False, True, "retop.toggle_see_through") in bindings, bindings)
check("and Alt+X is the mirror",
      ('X', True, False, "retop.mirror") in bindings, bindings)
# Still true, and for the same reason as before: Alt+Z is Blender's own
# viewport X-ray, and taking it over cost more than it gave.
check("Alt+Z is left to Blender's own X-ray",
      not any(t == 'Z' and alt for t, alt, _shift, _name in bindings), bindings)

state.result_show_wire = False
check("Show Wireframe off hides it", not result.show_wire, result.show_wire)
state.result_show_wire = True

state.result_wire_opacity = 0.25
opacities = []
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    opacities.append(space.overlay.wireframe_opacity)
# --background has no viewports; the call must simply be harmless there.
check("wireframe opacity reaches every 3D viewport (none in background)",
      all(abs(o - 0.25) < 1e-6 for o in opacities), opacities)

pr.operators.end_session(bpy.context)
check("a resting result never shows a wireframe, whatever the setting",
      not result.show_wire, result.show_wire)


# ===========================================================================
# Collection mirroring
# ===========================================================================
inbox = bpy.data.collections.new("Inbox")
bpy.context.scene.collection.children.link(inbox)
above = bpy.data.collections.new("PlasticityFile")  # bridge scaffolding: ignored
bpy.context.scene.collection.children.link(above)
above.children.link(inbox)
bpy.context.scene.collection.children.unlink(inbox)

group = bpy.data.collections.new("Body")
inbox.children.link(group)
sub_group = bpy.data.collections.new("Bracket")
group.children.link(sub_group)

nested = build_folded_object("Nested", 90.0, collection=sub_group)
check("source_collection_path is relative to Inbox",
      pr.mesh_build.source_collection_path(nested) == ["Body", "Bracket"],
      pr.mesh_build.source_collection_path(nested))

bpy.context.view_layer.objects.active = nested
pr.operators.enter_session_object(bpy.context, nested)
nested_result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(nested))
# Base names, not exact ones: Blender's collection namespace is global, so the
# mirror of a collection whose name is already taken by the source hierarchy is
# created as "Bracket.001". Unambiguous in the outliner, since it is nested
# under Retop, and _child_collection looks it up by base name.
parents = [c.name.rsplit(".", 1)[0] for c in nested_result.users_collection]
check("the result mesh is filed under the mirrored path",
      parents == ["Bracket"], parents)

retop = bpy.data.collections.get(pr.mesh_build.COLLECTION_NAME)
mirror_body = pr.mesh_build._child_collection(retop, "Body")
check("the mirror is rebuilt under Retop, not next to it", mirror_body is not None)
check("and nested one level deeper",
      mirror_body is not None
      and pr.mesh_build._child_collection(mirror_body, "Bracket") is not None)
check("iter_result_objects still finds nested results",
      nested_result in pr.mesh_build.iter_result_objects(bpy.context))

# An object outside any Inbox must not invent a path from unrelated names.
check("no Inbox above the object means no mirroring",
      pr.mesh_build.source_collection_path(folded) == [],
      pr.mesh_build.source_collection_path(folded))

pr.operators.end_session(bpy.context)
state.mirror_source_collections = False
plain = build_folded_object("Plain", 90.0, collection=sub_group)
bpy.context.view_layer.objects.active = plain
pr.operators.enter_session_object(bpy.context, plain)
plain_result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(plain))
check("the setting off keeps result meshes at the top of Retop",
      [c.name for c in plain_result.users_collection] == [pr.mesh_build.COLLECTION_NAME],
      [c.name for c in plain_result.users_collection])
state.mirror_source_collections = True


# ===========================================================================
# N-gon mode end to end
# ===========================================================================
pr.operators.end_session(bpy.context)
ngon_obj = build_folded_object("NgonTest", 90.0)
bpy.context.view_layer.objects.active = ngon_obj
pr.operators.enter_session_object(bpy.context, ngon_obj)

state.ngon_mode = True
pr.operators.set_active_patch(bpy.context, ngon_obj, 11)
check("N-gon mode reports the N-gon generator",
      state.generator_name == pr.generators.NGON.name, state.generator_name)
preview = bpy.data.objects.get(pr.mesh_build.PREVIEW_OBJ_NAME)
check("the preview is a single face", len(preview.data.polygons) == 1,
      len(preview.data.polygons))

bpy.ops.retop.commit_patch()
ngon_result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(ngon_obj))
check("the committed patch is one n-gon", len(ngon_result.data.polygons) == 1,
      len(ngon_result.data.polygons))

# Re-picking it must come back as an n-gon even with the mode turned off.
state.ngon_mode = False
pr.operators.set_active_patch(bpy.context, ngon_obj, 11)
check("a patch committed as an n-gon reopens as one",
      state.generator_name == pr.generators.NGON.name, state.generator_name)
bpy.ops.retop.clear_preview()

# The mode must not swallow a patch with a hole: an n-gon has one loop.
state.ngon_mode = True
registry = pr.mesh_build.get_span_registry(ngon_result)
check("an n-gon registers its boundary segments for propagation",
      len(registry) > 0, len(registry))

pr.operators.end_session(bpy.context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
