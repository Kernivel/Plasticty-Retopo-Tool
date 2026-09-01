"""Run inside Blender: blender --background --python tests/test_reload.py

The reload has one failure mode and it is nasty: a submodule left out of the
reload keeps running its *old* code while everything around it is new, so the
crash surfaces later, somewhere unrelated, as a reloaded module calling a
function the stale one has never heard of. That is exactly what happened when
generators/ngon.py was added to a hand-written reload list that didn't mention
it -- commit blew up on `ngon.loop_allocation`, in code that was fine.

So this asserts the invariant directly: every module of the package gets
reloaded, whatever it is called and whenever it was added.
"""
import os
import sys
import importlib

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

import bpy

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
PACKAGE = pr.__name__

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


def package_modules():
    return {name for name, module in sys.modules.items()
            if name.startswith(f"{PACKAGE}.") and module is not None}


before = package_modules()
check("the package has submodules to reload", len(before) > 5, len(before))
check("including the generators", any(".generators." in name for name in before))
check("and generators.ngon specifically -- the one that was missed",
      f"{PACKAGE}.generators.ngon" in before)

# Record what _perform_reload actually reloads. It does `import importlib` and
# then `importlib.reload(...)`, so the attribute is looked up at call time and
# wrapping it here is enough.
# Settings the reload must not eat. Blender keeps a PropertyGroup's values as
# ID properties on the scene, keyed by name, so deleting and re-declaring
# Scene.plasticity_retop re-attaches to the same stored data -- but that is a
# fact about Blender's storage, not about this code, and it is exactly the kind
# of thing that quietly stops being true. Asserted rather than assumed: a
# reload that reset the corner threshold would change every patch's side count,
# hence its generator, and finished retopology would stop resolving.
state_before = bpy.context.scene.plasticity_retop
state_before.corner_angle_threshold = 61.5
state_before.resolution = 'HIGH'
state_before.result_color = (0.9, 0.2, 0.1)

reloaded = []
real_reload = importlib.reload


def recording_reload(module):
    reloaded.append(module.__name__)
    return real_reload(module)


importlib.reload = recording_reload
try:
    pr.operators._perform_reload()
finally:
    importlib.reload = real_reload

missed = sorted(before - set(reloaded))
check("every package submodule was reloaded", not missed, missed)
check("no module was reloaded twice in one pass",
      len(reloaded) == len(set(reloaded)),
      [name for name in reloaded if reloaded.count(name) > 1])

# Reloading must leave a working addon behind, not just touched modules.
check("the panel is still registered", hasattr(bpy.types, "VIEW3D_PT_retop"))
check("the operators are still registered", hasattr(bpy.ops.retop, "session"))
check("scene state survives", hasattr(bpy.context.scene, "plasticity_retop"))

state_after = bpy.context.scene.plasticity_retop
check("a tuned corner threshold survives the reload",
      abs(state_after.corner_angle_threshold - 61.5) < 1e-4,
      state_after.corner_angle_threshold)
check("so does the resolution preset", state_after.resolution == 'HIGH',
      state_after.resolution)
check("and a colour", abs(state_after.result_color[0] - 0.9) < 1e-3,
      tuple(state_after.result_color))

# Handlers are removed by *name*, because a reload leaves the previous function
# object registered and it is no longer identical to the new one. Get that
# wrong and every reload stacks another copy, so one Ctrl+Z runs the undo
# reconciliation as many times as the addon has been reloaded that session.
handler_counts = {
    name: [h.__name__ for h in getattr(bpy.app.handlers, name)].count(func)
    for name, func in (("undo_post", "_on_undo_redo"),
                       ("redo_post", "_on_undo_redo"))
}
check("a reload does not stack the app handlers",
      all(count == 1 for count in handler_counts.values()), handler_counts)

# Same for the keymap items: _addon_keymaps is a module global, so it is wiped
# by the reload -- which is only safe because the unregister happens *before*
# the modules are reloaded. Get that order wrong and every reload orphans a set
# of keymap items nothing can ever remove, and the session's keys start firing
# two and three times per press.
pr_reloaded = sys.modules[PACKAGE]
if bpy.context.window_manager.keyconfigs.addon is not None:
    expected = sum(len(pr_reloaded.keymap.default_bindings(a))
                   for a in pr_reloaded.keymap.ACTION_IDS)
    registered = len(pr_reloaded.operators._addon_keymaps)
    check("nor orphan a set of keymap items", registered == expected,
          f"{registered} registered vs {expected} declared")
    # The overlay names its keys off these; a stale wrapper there is a draw
    # handler dereferencing freed data.
    check("and the overlay's view of them is rebuilt too",
          all(pr_reloaded.keymap.items_for(a)
              for a in pr_reloaded.keymap.ACTION_IDS),
          [a for a in pr_reloaded.keymap.ACTION_IDS
           if not pr_reloaded.keymap.items_for(a)])

# The stale-module symptom itself: functions added to a submodule must be
# reachable from the reloaded package.
pr_after = sys.modules[PACKAGE]
check("a generator submodule exposes its current API after a reload",
      hasattr(pr_after.generators.ngon, "loop_allocation"))
check("and the caller that needs it can reach it",
      hasattr(pr_after.operators, "register_spans_for"))

# A second reload must be just as complete (module objects have been swapped).
reloaded.clear()
importlib.reload = recording_reload
try:
    pr_after.operators._perform_reload()
finally:
    importlib.reload = real_reload
missed_again = sorted(package_modules() - set(reloaded))
check("a second reload misses nothing either", not missed_again, missed_again)


# ===========================================================================
# Detecting the state this whole file exists because of: files on disk that
# the running interpreter has never read.
# ===========================================================================
version_mod = sys.modules[PACKAGE].version

check("in-memory and on-disk agree in a clean checkout",
      version_mod.deployed_version() == version_mod.running_version(),
      f"{version_mod.deployed_version()} vs {version_mod.running_version()}")
check("so nothing is reported as stale", version_mod.stale_load() is None)

# Simulate a deploy landing under a running Blender: the file changes, the
# module in memory does not.
version_path = os.path.join(_ADDON_DIR, "version.py")
with open(version_path, "r", encoding="utf-8") as handle:
    original_source = handle.read()
try:
    bumped = original_source.replace(
        f'ADDON_VERSION = "{version_mod.ADDON_VERSION}"', 'ADDON_VERSION = "99.0.0"')
    check("the simulated deploy actually changed the file",
          bumped != original_source)
    with open(version_path, "w", encoding="utf-8") as handle:
        handle.write(bumped)

    version_mod._disk_cache = (0.0, None)  # the panel's 2s throttle
    check("the newer file on disk is read", version_mod.deployed_version()[0] == "99.0.0",
          version_mod.deployed_version())
    check("the constants in memory are untouched",
          version_mod.ADDON_VERSION != "99.0.0", version_mod.ADDON_VERSION)
    check("and the mismatch is reported",
          version_mod.stale_load() is not None, version_mod.stale_load())
    check("naming what is on disk, which is what the user just deployed",
          version_mod.stale_load()[0] == "99.0.0")
finally:
    with open(version_path, "w", encoding="utf-8") as handle:
        handle.write(original_source)
    version_mod._disk_cache = (0.0, None)

check("restoring the file clears the warning", version_mod.stale_load() is None,
      version_mod.stale_load())

# An unreadable version.py must not raise inside a panel draw, and must not be
# reported as a mismatch either -- an unknown is not a disagreement.
real_open = version_mod.open if hasattr(version_mod, "open") else open
import builtins
def exploding_open(*args, **kwargs):
    raise OSError("simulated unreadable file")
builtins.open = exploding_open
try:
    version_mod._disk_cache = (0.0, None)
    check("an unreadable version.py yields no reading", version_mod.deployed_version() is None)
    check("and is not called stale", version_mod.stale_load() is None)
finally:
    builtins.open = real_open
    version_mod._disk_cache = (0.0, None)

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
