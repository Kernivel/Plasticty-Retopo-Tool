"""Run inside Blender: blender --background --python tests/test_mirror.py

Mirroring the retopology (Alt+X, then X / Y / Z).

Symmetry is a Mirror modifier on `<Object>_Retop`, planed on the *source*
object's origin. What is worth pinning is why it is a modifier rather than
baked geometry: everything else here reads the result mesh's **base** data, so
the mirror must stay invisible to commit, re-edit, matching and shading. Baked
mirror faces would carry the same patch ids as the originals, and re-editing a
patch deletes every face carrying its id -- both halves would go and only one
would come back.

`bake_mirror` is the supported way to make it real, and the check that matters
is that the copies come out `NO_PATCH`: unclaimed faces are never deleted, so a
later re-edit can't tear the mirrored side open.
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
# A part that is symmetric about Y, which is the only case mirroring is for:
# patch 7 on +Y, patch 8 its reflection on -Y. Only 7 gets retopped; the mirror
# is what covers 8.
#
# The symmetry is load-bearing for more than realism. Applying the mirror
# leaves the copies untracked, and `adopt_untracked_faces` then hands each one
# to the Plasticity face it sits on -- which is patch 8, precisely because
# there *is* a face there. Mirror a patch out over empty space and adoption has
# only patch 7 to offer them, so they join it and a later re-edit of 7 takes
# them with it. That is mirroring a part that isn't symmetric, and it degrades
# the way the adoption rule says it does.
# ---------------------------------------------------------------------------
verts = [
    (-2.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 3.0, 0.0), (-2.0, 3.0, 0.0),
    (2.0, -3.0, 0.0), (-2.0, -3.0, 0.0),
]
mesh = bpy.data.meshes.new("MirrorMesh")
mesh.from_pydata(verts, [], [(0, 1, 2), (0, 2, 3), (1, 0, 5), (1, 5, 4)])
mesh.update()
mesh["groups"] = [0, 6, 6, 6]
mesh["face_ids"] = [7, 8]

obj = bpy.data.objects.new("MirrorObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

# ---------------------------------------------------------------------------
# Nothing committed: nothing to mirror, and it says so rather than doing it
# ---------------------------------------------------------------------------
source, result = pr.mesh_build.mirror_target(bpy.context)
check("the target resolves from the active object", source is obj, source)
check("but there is no result mesh yet", result is None, result)
check("so the operator is not offered", not bpy.ops.retop.mirror_axis.poll())

pr.operators.enter_session_object(bpy.context, obj)
state.ngon_mode = False
pr.operators.set_active_patch(bpy.context, obj, 7)
state.span_u = 2
state.span_v = 2
bpy.ops.retop.commit_patch()

result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
faces_before = len(result.data.polygons)
verts_before = len(result.data.vertices)
check("the patch is committed", faces_before == 4, faces_before)
check("and now the mirror is offered", bpy.ops.retop.mirror_axis.poll())
check("with nothing mirrored yet",
      pr.mesh_build.mirror_axes(result) == (False, False, False),
      pr.mesh_build.mirror_axes(result))

# ---------------------------------------------------------------------------
# Toggling axes
# ---------------------------------------------------------------------------
bpy.ops.retop.mirror_axis(axis='Y')
check("Y is on", pr.mesh_build.mirror_axes(result) == (False, True, False),
      pr.mesh_build.mirror_axes(result))

mod = result.modifiers.get(pr.mesh_build.MIRROR_MODIFIER_NAME)
check("a Mirror modifier appeared", mod is not None and mod.type == 'MIRROR',
      mod.type if mod else None)
check("planed on the source object, not the result",
      mod.mirror_object is obj, mod.mirror_object)
check("it is first in the stack, ahead of the cosmetic offset",
      result.modifiers.find(pr.mesh_build.MIRROR_MODIFIER_NAME) == 0,
      [m.name for m in result.modifiers])
check("clipping follows the panel", mod.use_clip == state.mirror_clip)

# The whole point of a modifier: the real mesh is untouched, so every piece of
# bookkeeping that reads it carries on seeing exactly one half.
check("the result mesh itself did not grow",
      len(result.data.polygons) == faces_before
      and len(result.data.vertices) == verts_before,
      f"{len(result.data.polygons)}f/{len(result.data.vertices)}v")
check("the patch is still one patch",
      pr.mesh_build.committed_face_ids(obj) == {7},
      pr.mesh_build.committed_face_ids(obj))

bpy.ops.retop.mirror_axis(axis='X')
check("axes are cumulative",
      pr.mesh_build.mirror_axes(result) == (True, True, False),
      pr.mesh_build.mirror_axes(result))

bpy.ops.retop.mirror_axis(axis='Y')
check("pressing the same axis again turns it off",
      pr.mesh_build.mirror_axes(result) == (True, False, False),
      pr.mesh_build.mirror_axes(result))

bpy.ops.retop.mirror_axis(axis='X')
check("the last axis off removes the modifier",
      result.modifiers.get(pr.mesh_build.MIRROR_MODIFIER_NAME) is None,
      [m.name for m in result.modifiers])
check("and mirror_axes says so",
      pr.mesh_build.mirror_axes(result) == (False, False, False))

# Settings reach an existing mirror without creating one anywhere.
bpy.ops.retop.mirror_axis(axis='Y')
state.mirror_clip = False        # update callback -> apply_mirror_settings
mod = result.modifiers.get(pr.mesh_build.MIRROR_MODIFIER_NAME)
check("turning clipping off reaches the live modifier", not mod.use_clip)
state.mirror_clip = True
check("and back on again", mod.use_clip)

state.mirror_merge_distance = 0.0
check("a zero merge distance turns the merge off, not the mirror",
      not mod.use_mirror_merge
      and result.modifiers.get(pr.mesh_build.MIRROR_MODIFIER_NAME) is not None,
      f"merge={mod.use_mirror_merge}")
state.mirror_merge_distance = 1e-3
check("a non-zero one turns it back on", mod.use_mirror_merge)

# ---------------------------------------------------------------------------
# Applying it: the copies must come out untracked
# ---------------------------------------------------------------------------
ids_before = {d.value for d in
              result.data.attributes[pr.mesh_build.PATCH_ID_ATTR].data}
check("every committed face carries its patch id", ids_before == {7}, ids_before)

added, error = pr.mesh_build.bake_mirror(bpy.context, result)
check("the mirror applied", error is None, error)
check("the geometry doubled", len(result.data.polygons) == faces_before * 2,
      len(result.data.polygons))
check("and it says how much it added", added == faces_before, added)

ids_after = [d.value for d in
             result.data.attributes[pr.mesh_build.PATCH_ID_ATTR].data]
originals = [i for i in ids_after if i == 7]
copies = [i for i in ids_after if i == pr.mesh_build.NO_PATCH]
check("the originals kept their patch id", len(originals) == faces_before,
      len(originals))
check("the copies are untracked, so a re-edit can't delete them",
      len(copies) == faces_before, len(copies))
check("nothing else got an id", len(originals) + len(copies) == len(ids_after),
      sorted(set(ids_after)))

check("the modifier is gone",
      result.modifiers.get(pr.mesh_build.MIRROR_MODIFIER_NAME) is None)
check("applying again is refused with a reason",
      pr.mesh_build.bake_mirror(bpy.context, result)[1] is not None,
      pr.mesh_build.bake_mirror(bpy.context, result)[1])

# The untracked copies are exactly what adoption is for: entering the object
# again hands each one to the Plasticity face it sits on, which on a symmetric
# part is the *real* face on the other side. Patch 8 was never retopped by
# hand, and now it is.
adopted = pr.mesh_build.adopt_untracked_faces(obj)
check("adoption claimed the copies", adopted == faces_before, adopted)
claimed = pr.mesh_build.committed_face_ids(obj)
check("onto the CAD face they landed on, not the one they came from",
      claimed == {7, 8}, sorted(claimed))

# And that is what makes re-editing safe: patch 7 owns one half only.
pr.operators.set_active_patch(bpy.context, obj, 7)
check("re-editing 7 took out only 7's faces",
      len(result.data.polygons) == faces_before, len(result.data.polygons))
pr.operators.restore_reedit_removal(bpy.context)
bpy.ops.retop.clear_preview()
check("and discarding puts them back",
      len(result.data.polygons) == faces_before * 2,
      len(result.data.polygons))

# ---------------------------------------------------------------------------
# The keys
# ---------------------------------------------------------------------------
state.session_phase = 'PATCH'
patch_keys = [k for k, _a in pr.overlay.keybinds_for(state)]
check("Alt+X is advertised as the mirror", "Alt+X" in patch_keys, patch_keys)
check("the x-ray moved to V", "V" in patch_keys, patch_keys)
check("Alt+X is no longer the x-ray",
      all(a != "Retopo X-Ray" for k, a in pr.overlay.keybinds_for(state)
          if k == "Alt+X"),
      pr.overlay.keybinds_for(state))
# Ctrl+Z is Blender's own and reaching for it is automatic; the hint line is
# short and every entry has to earn its width.
check("Ctrl+Z is not in the hints", "Ctrl+Z" not in patch_keys, patch_keys)

for phase in ('OBJECT', 'PATCH', 'ADJUST', 'TWEAK'):
    state.session_phase = phase
    keys = [k for k, _a in pr.overlay.keybinds_for(state)]
    check(f"{phase}: no stale Alt+X x-ray hint",
          not any(k == "Alt+X" and "X-Ray" in a
                  for k, a in pr.overlay.keybinds_for(state)),
          keys)

pr.operators.end_session(bpy.context)
pr.unregister()

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
