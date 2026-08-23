"""Run inside Blender: blender --background --python tests/test_context.py

Context switching, so the session follows what the user is actually doing:

  - selecting `<Something>_Retop` and starting a session means carrying on with
    `Something`, not starting one on a mesh that has no patch data;
  - Blender leaving Object Mode hands the viewport back, with one exception
    that would otherwise lose committed topology.
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

verts = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
tris = [(0, 1, 2), (0, 2, 3)]
mesh = bpy.data.meshes.new("CtxMesh")
mesh.from_pydata(verts, [], tris)
mesh.update()
mesh["groups"] = [0, len(tris) * 3]
mesh["face_ids"] = [5]

obj = bpy.data.objects.new("CtxObj", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj


# ===========================================================================
# The retopology points back at what it was built from
# ===========================================================================
check("an ordinary object resolves to itself",
      pr.operators.resolve_session_object(obj) is obj)
check("and nothing resolves to nothing",
      pr.operators.resolve_session_object(None) is None)

pr.operators.enter_session_object(bpy.context, obj)
result = bpy.data.objects.get(pr.mesh_build.result_object_name_for(obj))
check("the session built a result mesh", result is not None)

check("the result mesh resolves back to its source",
      pr.operators.resolve_session_object(result) is obj, result.name)
check("which is the whole point: it has no patch data of its own",
      not result.data.get("face_ids"))

pr.operators.end_session(bpy.context)

# Entering *by way of* the retopology must land on the source.
pr.operators.enter_session_object(bpy.context, result)
check("entering through the retopology enters its source instead",
      state.session_object_name == obj.name, state.session_object_name)
check("and reaches the patch-picking phase, not a dead end",
      state.session_phase == 'PATCH', state.session_phase)
pr.operators.end_session(bpy.context)

# An orphaned result -- source renamed or gone -- has nothing to resolve to and
# must not silently redirect somewhere else.
orphan_mesh = bpy.data.meshes.new("Gone_Retop")
orphan = bpy.data.objects.new("Gone_Retop", orphan_mesh)
bpy.context.collection.objects.link(orphan)
check("a result whose source is gone resolves to itself",
      pr.operators.resolve_session_object(orphan) is orphan)


# ===========================================================================
# Leaving Object Mode
# ===========================================================================
pr.operators.enter_session_object(bpy.context, obj)
check("the session is inside the object", state.session_phase == 'PATCH',
      state.session_phase)

session = pr.operators.RETOP_OT_session
check("mode changes are handled by the modal, not a handler",
      hasattr(session, "_leave_for_other_mode"))


class FakeModal:
    """Enough of the operator to exercise the decision, which is all that can
    be reached headless -- a modal needs an event loop."""

    _hover_obj = None
    _hover_face_id = None
    _hover_committed = False
    _hover_ngon = False
    _cursor_in_viewport = None
    reports = []

    _PHASE_UI = session._PHASE_UI

    def report(self, _level, message):
        self.reports.append(message)

    def _clear_hover(self, context):
        session._clear_hover(self, context)

    def _apply_phase_ui(self, context):
        pass

    def _leave_for_other_mode(self, context):
        session._leave_for_other_mode(self, context)


fake = FakeModal()
fake._leave_for_other_mode(bpy.context)
check("it leaves the object", state.session_phase == 'OBJECT', state.session_phase)
check("and says so rather than doing it silently",
      any("Object Mode" in message for message in fake.reports), fake.reports)
check("the session itself is still running -- only the object was left",
      state.session_active)

fake.reports.clear()
fake._leave_for_other_mode(bpy.context)
check("calling it again while already out is a no-op", not fake.reports, fake.reports)

# --- the exception: a re-edit whose result mesh is the one being edited ---
pr.operators.enter_session_object(bpy.context, obj)
pr.operators.set_active_patch(bpy.context, obj, 5)
bpy.ops.retop.commit_patch()
pr.operators.set_active_patch(bpy.context, obj, 5)
check("a re-edit is open", state.editing_committed)
check("with a snapshot to put the patch back with", bool(state.reedit_backup_mesh))


class FakeEditContext:
    """context.edit_object is the mesh Blender has open in Edit Mode."""

    def __init__(self, real, edit_object):
        self._real = real
        self.edit_object = edit_object

    def __getattr__(self, name):
        return getattr(self._real, name)


faces_out = len(result.data.polygons)
phase_before = state.session_phase   # set_active_patch leaves the phase alone;
                                     # the modal's click handler is what moves
                                     # it to ADJUST, and that can't run headless
fake.reports.clear()
fake._leave_for_other_mode(FakeEditContext(bpy.context, result))
check("editing the very result mesh a re-edit took faces from does NOT exit",
      state.session_phase == phase_before, state.session_phase)
check("because the snapshot could only be written into a mesh Blender owns",
      state.editing_committed and bool(state.reedit_backup_mesh))
check("so nothing was restored into it", len(result.data.polygons) == faces_out,
      len(result.data.polygons))

# Editing anything else is not that case, so it exits and restores normally.
fake._leave_for_other_mode(FakeEditContext(bpy.context, obj))
check("editing another object exits and puts the patch back",
      state.session_phase == 'OBJECT' and not state.editing_committed,
      f"{state.session_phase} / {state.editing_committed}")
check("the removed faces are back", len(result.data.polygons) > faces_out,
      len(result.data.polygons))

pr.operators.end_session(bpy.context)


# ===========================================================================
# Starting resolution
#
# The generators size a patch from its own edge lengths. That is the right
# shape but not necessarily the density wanted, and scrolling every new patch
# back down to it is the complaint this answers.
# ===========================================================================
# A fresh object, and a patch tessellated finely enough that the computed span
# is more than 1 -- `obj` above has been committed by now, and a committed
# patch reopens with its own spans, which is exactly what the preset must not
# override (asserted below).
GRID = 8
res_verts = []
index_of = {}
for j in range(GRID + 1):
    for i in range(GRID + 1):
        index_of[(i, j)] = len(res_verts)
        res_verts.append((i, j, 0.0))
res_tris = []
for j in range(GRID):
    for i in range(GRID):
        a = index_of[(i, j)]
        b = index_of[(i + 1, j)]
        c = index_of[(i + 1, j + 1)]
        d = index_of[(i, j + 1)]
        res_tris.append((a, b, c))
        res_tris.append((a, c, d))

res_mesh = bpy.data.meshes.new("ResMesh")
res_mesh.from_pydata(res_verts, [], res_tris)
res_mesh.update()
res_mesh["groups"] = [0, len(res_tris) * 3]
res_mesh["face_ids"] = [77]
res_obj = bpy.data.objects.new("ResObj", res_mesh)
bpy.context.collection.objects.link(res_obj)

state.resolution = 'MID'
pr.operators.enter_session_object(bpy.context, res_obj)
pr.operators.set_active_patch(bpy.context, res_obj, 77)
mid = (state.span_u, state.span_v)
check("Mid gives a usable starting count", all(v > 1 for v in mid), mid)

resolutions = {}
for preset in ('VERY_LOW', 'LOW', 'HIGH', 'EXTREME'):
    state.resolution = preset
    pr.operators.set_active_patch(bpy.context, res_obj, 77)
    resolutions[preset] = (state.span_u, state.span_v)

check("the presets order as their names say",
      resolutions['VERY_LOW'] <= resolutions['LOW'] <= mid
      <= resolutions['HIGH'] <= resolutions['EXTREME'],
      f"{resolutions} around {mid}")
check("High doubles Mid",
      resolutions['HIGH'] == tuple(v * 2 for v in mid),
      f"{mid} -> {resolutions['HIGH']}")
check("Extreme quadruples it",
      resolutions['EXTREME'] == tuple(v * 4 for v in mid),
      f"{mid} -> {resolutions['EXTREME']}")
check("and nothing is ever scaled below one span",
      all(v >= 1 for v in resolutions['VERY_LOW']), resolutions['VERY_LOW'])

scale = pr.state.scale_default_spans
state.resolution = 'VERY_LOW'
check("a span of 1 stays 1 rather than rounding away",
      scale(state, {"span": 1}) == {"span": 1}, scale(state, {"span": 1}))

# The arithmetic, on a known input -- the end-to-end checks above can only
# assert ordering, since rounding a real patch's count is not exact.
factors = pr.state.RESOLUTION_FACTORS
check("every preset is trimmed by a quarter off its power of two",
      [round(factors[name] / trim, 4) for name, trim in
       (('VERY_LOW', 0.75), ('LOW', 0.75), ('MID', 0.75), ('HIGH', 0.75),
        ('EXTREME', 0.75))] == [0.25, 0.5, 1.0, 2.0, 4.0],
      factors)
state.resolution = 'MID'
check("so Mid asks for three quarters of what the generator computed",
      scale(state, {"span_u": 8, "span_v": 4}) == {"span_u": 6, "span_v": 3},
      scale(state, {"span_u": 8, "span_v": 4}))
state.resolution = 'HIGH'
check("and High is still exactly twice Mid",
      scale(state, {"span": 8}) == {"span": 12}, scale(state, {"span": 8}))

# The preset must not touch a span a patch was committed with, or re-editing
# under a different preset would silently re-shape finished work.
state.resolution = 'MID'
pr.operators.set_active_patch(bpy.context, res_obj, 77)
state.span_u = 6
state.span_v = 6
bpy.ops.retop.commit_patch()
state.resolution = 'EXTREME'
pr.operators.set_active_patch(bpy.context, res_obj, 77)
check("a committed patch reopens with its own spans, not scaled ones",
      (state.span_u, state.span_v) == (6, 6), (state.span_u, state.span_v))
bpy.ops.retop.clear_preview()
state.resolution = 'MID'


# ===========================================================================
# Ctrl+wheel in N-gon mode drives the detail angle
# ===========================================================================
state.ngon_mode = True
pr.operators.set_active_patch(bpy.context, res_obj, 77)


class FakeWheelModal:
    def _nudge_ngon_angle(self, context, direction):
        pr.operators.RETOP_OT_session._nudge_ngon_angle(self, context, direction)


wheel = FakeWheelModal()
state.ngon_angle = 20.0
wheel._nudge_ngon_angle(bpy.context, +1)
check("scrolling up asks for more detail, i.e. a smaller angle",
      state.ngon_angle < 20.0, state.ngon_angle)
wheel._nudge_ngon_angle(bpy.context, -1)
check("and scrolling back down returns where it was",
      abs(state.ngon_angle - 20.0) < 0.1, state.ngon_angle)

state.ngon_angle = 1.0
wheel._nudge_ngon_angle(bpy.context, +1)
check("it cannot be driven below the property minimum",
      state.ngon_angle >= 1.0, state.ngon_angle)
state.ngon_angle = 180.0
wheel._nudge_ngon_angle(bpy.context, -1)
check("nor above the maximum", state.ngon_angle <= 180.0, state.ngon_angle)

# Multiplicative, not a fixed step: 2 degrees is nothing at 90 and everything
# at 4, so one fixed step is unusable at one end or the other.
state.ngon_angle = 100.0
wheel._nudge_ngon_angle(bpy.context, -1)
coarse_step = state.ngon_angle - 100.0
state.ngon_angle = 4.0
wheel._nudge_ngon_angle(bpy.context, -1)
fine_step = state.ngon_angle - 4.0
check("the step scales with the value it steps",
      coarse_step > fine_step * 4, f"{coarse_step:.2f} vs {fine_step:.2f}")

pr.operators.end_session(bpy.context)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
