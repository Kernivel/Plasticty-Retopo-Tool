"""Run inside Blender: blender --background --python tests/test_keymap.py

The session's keys as real KeyMapItems.

They were `event.type == 'X'` comparisons inside the modal, then a hand-rolled
table with a capture modal and a panel to edit it in — a second, worse keymap
editor next to Blender's. They are `KeyMapItem`s on real operators now, so
Blender owns the editing, the conflict display, the restore-to-default and the
persistence, and the addon's preferences page just draws `rna_keymap_ui` rows.

That trade has one hard requirement and this is where it is pinned: **the modal
must stop claiming those events**, because a modal handler sits above every
keymap and nothing below it ever runs. And each operator's `poll` has to carry
the phase logic the modal used to spell out, since an item in the 3D View
keymap is offered whether a session exists or not.

Three items share `TAB` on purpose. Their polls are mutually exclusive by
phase, which is the whole design expressed natively — and a test that let two
of them pass at once would be a Tab that does the wrong thing.
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
km = pr.keymap

# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------
check("every action has a unique id",
      len(km.ACTION_IDS) == len(set(km.ACTION_IDS)), km.ACTION_IDS)
check("every action has at least one default binding",
      all(km.default_bindings(a) for a in km.ACTION_IDS),
      [a for a in km.ACTION_IDS if not km.default_bindings(a)])
check("every action names a registered operator",
      all(hasattr(bpy.ops.retop, km.operator_of(a).split(".", 1)[1])
          for a in km.ACTION_IDS),
      [a for a in km.ACTION_IDS
       if not hasattr(bpy.ops.retop, km.operator_of(a).split(".", 1)[1])])

# Defaults are handed out copied: the module-level list is shared by everything
# that asks, and a caller that edits what it is given would corrupt it for good.
borrowed = km.default_bindings("commit")
borrowed[0]["type"] = "MANGLED"
check("default_bindings hands back a copy",
      km.default_bindings("commit")[0]["type"] == 'RET',
      km.default_bindings("commit"))

# ---------------------------------------------------------------------------
# Polls: the phase logic the modal used to spell out
# ---------------------------------------------------------------------------
POLLS = {
    "span_more": bpy.ops.retop.nudge_span.poll,
    "span_axis": bpy.ops.retop.toggle_span_axis.poll,
    "ngon_mode": bpy.ops.retop.toggle_ngon.poll,
    "match_mode": bpy.ops.retop.toggle_match_mode.poll,
    "cad_edges": bpy.ops.retop.toggle_cad_edges.poll,
    "surface_flow": bpy.ops.retop.toggle_surface_flow.poll,
    "back": bpy.ops.retop.back.poll,
}


def polls_in(phase, active=True):
    state.session_active = active
    state.session_phase = phase
    return {name for name, poll in POLLS.items() if poll()}


check("no session: none of the session keys are offered",
      polls_in('PATCH', active=False) == set(), polls_in('PATCH', active=False))
check("picking a surface offers only the always-on ones",
      polls_in('PATCH') == {"cad_edges", "surface_flow", "back"},
      polls_in('PATCH'))
check("picking an object, the same",
      polls_in('OBJECT') == {"cad_edges", "surface_flow", "back"},
      polls_in('OBJECT'))
check("adjusting offers the patch keys too",
      polls_in('ADJUST') == set(POLLS), polls_in('ADJUST'))
check("hand-editing offers none of them",
      polls_in('TWEAK') == set(), polls_in('TWEAK'))

# The three Tab items. Exactly one poll may pass in any phase, or Tab does the
# wrong thing -- Blender runs the first item whose poll passes.
state.session_active = True
for phase, expected in (('ADJUST', "retop.toggle_span_axis"),
                        ('PATCH', "retop.tweak_mesh"),
                        ('TWEAK', "retop.end_tweak")):
    state.session_phase = phase
    passing = [op for op in ("retop.toggle_span_axis", "retop.tweak_mesh",
                             "retop.end_tweak")
               if getattr(bpy.ops.retop, op.split(".", 1)[1]).poll()]
    # tweak_mesh also needs something committed, so in PATCH it can legitimately
    # be none; what must never happen is *two*.
    check(f"at most one Tab action is live in {phase}", len(passing) <= 1, passing)
    if passing:
        check(f"and in {phase} it is {expected}", passing == [expected], passing)

state.session_active = False
state.session_phase = 'OBJECT'
check("with no session, Tab belongs to Blender again",
      not any(getattr(bpy.ops.retop, op).poll()
              for op in ("toggle_span_axis", "tweak_mesh", "end_tweak")))

# ---------------------------------------------------------------------------
# What the operators actually do
# ---------------------------------------------------------------------------
state.session_active = True
state.session_phase = 'ADJUST'
state.generator_name = "Quad"
state.span_axis = 'U'
state.span_u = 4
state.ngon_mode = False

state.typed_span = "7"
bpy.ops.retop.nudge_span(delta=1)
check("the span key steps the span", state.span_u == 5, state.span_u)
check("and takes over from a half-typed number", state.typed_span == "",
      state.typed_span)
for _ in range(9):
    bpy.ops.retop.nudge_span(delta=-1)
check("it never drives the span below 1", state.span_u == 1, state.span_u)

bpy.ops.retop.toggle_span_axis()
check("U/V switches direction", state.span_axis == 'V', state.span_axis)
state.generator_name = "Triangle"
check("and refuses on a single-span generator, rather than silently doing nothing",
      bpy.ops.retop.toggle_span_axis() == {'CANCELLED'})
state.generator_name = "Quad"

was = state.match_mode
bpy.ops.retop.toggle_match_mode()
check("the side highlight toggles", state.match_mode is not was)
bpy.ops.retop.toggle_match_mode()

for op, prop in (("toggle_cad_edges", "show_cad_edges"),
                 ("toggle_surface_flow", "show_surface_flow")):
    before = getattr(state, prop)
    getattr(bpy.ops.retop, op)()
    check(f"{op} flips {prop}", getattr(state, prop) is not before)
    getattr(bpy.ops.retop, op)()

state.ngon_available = False
state.ngon_unavailable_reason = "not a flat face"
state.ngon_mode = False
check("N-gon mode refuses where the patch can't take one",
      bpy.ops.retop.toggle_ngon() == {'CANCELLED'})
check("and leaves the mode alone", not state.ngon_mode)

# ---------------------------------------------------------------------------
# `back`: one step out per press
# ---------------------------------------------------------------------------
state.session_phase = 'ADJUST'
state.typed_span = "12"
bpy.ops.retop.back()
check("a first press only clears the typing", state.typed_span == ""
      and state.session_phase == 'ADJUST', state.session_phase)
bpy.ops.retop.back()
check("the second discards the patch", state.session_phase == 'PATCH',
      state.session_phase)
bpy.ops.retop.back()
check("then it leaves the object", state.session_phase == 'OBJECT',
      state.session_phase)
bpy.ops.retop.back()
# The modal owns the timer, the cursor and the draw handlers, so the operator
# asks for the end rather than doing it; the modal acts on the flag.
check("and asks for the session to end", not state.session_active)

# ---------------------------------------------------------------------------
# No key is spelled out in the modal any more
#
# The modal *does* dispatch these -- a keymap item does not reliably beat a
# mode keymap, and `X` in Object Mode is `object.delete` -- but it resolves
# them through the bindings. A hardcoded `event.type == 'X'` is what made them
# unremappable in the first place, and it comes back one line at a time.
# ---------------------------------------------------------------------------
import inspect
modal_source = inspect.getsource(pr.operators.RETOP_OT_session._modal)
for claimed in ("'RET'", "'NUMPAD_ENTER'", "'RIGHTMOUSE'", "'ESC'", "'TAB'",
                "'WHEELUPMOUSE'", "'WHEELDOWNMOUSE'", "'N'", "'M'", "'X'",
                "'E'"):
    check(f"_modal no longer tests for {claimed}", claimed not in modal_source,
          "resolve it through keymap.session_action_for instead")
check("_modal still owns the left click, which depends on what is under it",
      "'LEFTMOUSE'" in modal_source)

# The click is split, not fixed. Taking the side under the cursor is a normal
# binding; only the fallback -- nothing under the cursor, so commit -- stays in
# the modal, and the picker hands the event over whenever it doesn't apply.
picker_source = inspect.getsource(pr.operators.RETOP_OT_session._modal_match)
check("the side picker resolves the click through the bindings",
      "session_action_for" in picker_source
      and "adopt_side_reference" not in picker_source,
      "Ctrl+click was fixed only because it was lumped in with the fallback")
state.session_active = True
state.session_phase = 'ADJUST'
state.match_mode = True
state.hovered_side = -1
check("with no side under the cursor the pin is not offered",
      not bpy.ops.retop.pin_side.poll())
state.hovered_side = 0
check("with one, it is", bpy.ops.retop.pin_side.poll())
state.match_mode = False
check("and never with the highlight off", not bpy.ops.retop.pin_side.poll())
state.match_mode = True
state.hovered_side = -1


# --- the dispatch, and what it must never let through ---------------------
#
# `X` reaching Blender during a session is `object.delete`: it takes the CAD
# object with it. That is why a session action whose poll *fails* is still
# consumed for the two keys Blender itself claims -- and why the others are
# not, since `N` outside ADJUST should still open the sidebar.
class _Event:
    def __init__(self, type, value='PRESS', ctrl=False, shift=False, alt=False):
        self.type, self.value = type, value
        self.ctrl, self.shift, self.alt, self.oskey = ctrl, shift, alt, False


class _Modal:
    _MUST_CONSUME = pr.operators.RETOP_OT_session._MUST_CONSUME
    _refusal = pr.operators.RETOP_OT_session._refusal
    _run_bound_action = pr.operators.RETOP_OT_session._run_bound_action
    reported = []

    def report(self, _level, message):
        self.reported.append(message)


modal = _Modal()
state.session_active = True
state.session_phase = 'ADJUST'
state.editing_committed = False

check("X resolves to the delete action",
      km.session_action_for(_Event('X')) == "delete_patch",
      km.session_action_for(_Event('X')))
check("and Alt+X does not -- modifiers are compared exactly",
      km.session_action_for(_Event('X', alt=True)) is None)

check("delete refuses on an uncommitted patch",
      not bpy.ops.retop.delete_patch.poll())
modal.reported.clear()
check("but the key is consumed anyway, so it never reaches object.delete",
      modal._run_bound_action(bpy.context, "delete_patch") is True)
check("and it says why rather than reading as a dead key",
      any("Nothing to delete" in m for m in modal.reported), modal.reported)

# The opposite case: a key Blender has a better use for outside its phase.
state.session_phase = 'PATCH'
check("N-gon mode is not offered while picking",
      not bpy.ops.retop.toggle_ngon.poll())
check("so N is left alone and the sidebar still opens",
      modal._run_bound_action(bpy.context, "ngon_mode") is False)
state.session_phase = 'ADJUST'

# ---------------------------------------------------------------------------
# Registration, and the labels the overlay reads off it
# ---------------------------------------------------------------------------
if bpy.context.window_manager.keyconfigs.addon is None:
    print("[SKIP] no addon keyconfig in this build")
else:
    registered = [(kmi.type, kmi.ctrl, kmi.shift, kmi.alt, kmi.idname)
                  for _km, kmi in pr.operators._addon_keymaps]
    declared = sum(len(km.default_bindings(a)) for a in km.ACTION_IDS)
    check("every declared binding is registered", len(registered) == declared,
          f"{len(registered)} vs {declared}")
    check("the mirror is on Alt+X",
          ('X', False, False, True, "retop.mirror") in registered, registered)
    # `V`, and deliberately not any flavour of `X`: the mirror wants Alt+X and
    # the patch delete wants a bare X, and hanging a third meaning off the same
    # letter is how Shift+X ended up reaching `object.delete`'s confirmation
    # popup instead of the toggle.
    check("the x-ray on V",
          ('V', False, False, False, "retop.toggle_see_through") in registered,
          registered)
    check("commit answers to three things",
          len(km.items_for("commit")) == 3, km.describe_all("commit"))

    # Two items share one operator and differ only by a property; matching them
    # back by idname would pair them up wrong, which is why the registry keys
    # on the action rather than the operator.
    ups = km.items_for("span_more")
    downs = km.items_for("span_less")
    check("the two wheel directions are told apart",
          ups and downs and ups[0].properties.delta == 1
          and downs[0].properties.delta == -1,
          f"{ups[0].properties.delta} / {downs[0].properties.delta}"
          if ups and downs else "missing")

    # The overlay names its keys off the live items, so a remap changes the
    # hint with it -- a hint that says E when the key is Ctrl+E is the one
    # place a user checks before deciding the feature is broken.
    check("the overlay reads a live binding",
          km.describe("cad_edges") == "E", km.describe("cad_edges"))
    km.items_for("cad_edges")[0].type = 'F5'
    km.items_for("cad_edges")[0].shift = True
    state.session_active = True
    state.session_phase = 'PATCH'
    hints = dict(pr.overlay.keybinds_for(state))
    check("and the hint follows a remapped one", "Shift+F5" in hints, sorted(hints))
    check("dropping the key it replaced", "E" not in hints, sorted(hints))
    km.items_for("cad_edges")[0].type = 'E'
    km.items_for("cad_edges")[0].shift = False

check("the span pair collapses to one hint",
      pr.overlay._pair_label("span_more", "span_less") == "Ctrl+Scroll",
      pr.overlay._pair_label("span_more", "span_less"))

# `describe` has to answer even with nothing registered: --background has no
# addon keyconfig at all, and the overlay is drawn from the same code.
km.forget_all()
check("describe falls back to the declared default",
      km.describe("mirror") == "Alt+X", km.describe("mirror"))
pr.operators._register_keymaps()

# ---------------------------------------------------------------------------
# The GLOBAL keys are not the addon's outside a session
# ---------------------------------------------------------------------------
# They are dispatched by Blender rather than by the modal, so unlike the
# session's keys they are offered from the moment the addon is installed --
# and '/' , Alt+X and Shift+X all belong to something else too (Hard Ops binds
# Alt+X). A failing poll is what hands the event on, so the poll is the pin.
GLOBAL_POLLS = {
    "mirror": bpy.ops.retop.mirror.poll,
    "see_through": bpy.ops.retop.toggle_see_through.poll,
    "local_view": bpy.ops.retop.local_view.poll,
}
check("every GLOBAL action is tested here",
      {a for a in km.ACTION_IDS if km.scope_of(a) == km.GLOBAL} == set(GLOBAL_POLLS),
      sorted(a for a in km.ACTION_IDS if km.scope_of(a) == km.GLOBAL))

state.session_active = False
state.session_phase = 'OBJECT'
check("with no session, no global key is claimed",
      not any(poll() for poll in GLOBAL_POLLS.values()),
      [n for n, poll in GLOBAL_POLLS.items() if poll()])

state.session_active = True
state.session_phase = 'PATCH'
# The mirror still needs a result mesh and the isolate a 3D view, neither of
# which a background run has -- so this asserts only that the *gate* opened,
# which is the thing the change moved.
check("a session opens the gate", pr.operators._global_keys_live(bpy.context))
check("and the x-ray, which needs nothing else, is live",
      bpy.ops.retop.toggle_see_through.poll())

# The preference is the way back for anyone who wants the isolate and the
# mirror between sessions. There is no addon entry in a plain import, so the
# accessor is stood in for rather than the preference set.
state.session_active = False
_real_pref = km.global_keys_outside_session
km.global_keys_outside_session = lambda: True
try:
    check("the preference puts them back with no session",
          pr.operators._global_keys_live(bpy.context))
    check("and the x-ray with it", bpy.ops.retop.toggle_see_through.poll())
finally:
    km.global_keys_outside_session = _real_pref
check("with no addon entry the preference reads as off",
      km.global_keys_outside_session() is False)

state.session_active = False
pr.unregister()

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("=== ALL CHECKS PASSED")
    sys.exit(0)
