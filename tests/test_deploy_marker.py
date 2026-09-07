"""Run inside Blender: blender --background --python tests/test_deploy_marker.py

Deploying from a checkout turns Developer Mode on by itself.

Deploying *is* the statement that this is a working copy, so ticking a box
afterwards is a step that knows nothing the deploy did not already know -- and
forgetting it looks exactly like a deploy that never landed, which is the one
failure the version string exists to report.

The mechanism is a marker file `scripts/deploy.py` writes into the copy it
makes, and `prefs.seed_developer_mode` reads on registration. That name is
spelled in **two** files and cannot be shared: `scripts/` is excluded from the
deploy, so the installed addon has no deploy.py to import it from. Two literals
in two files is exactly the shape of the bl_info/version drift that
`build_zip.py --check` exists to catch, so it is checked here the same way.
"""
import ast
import importlib
import os
import shutil
import sys
import tempfile

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ADDON_DIR))
sys.path.insert(0, os.path.join(_ADDON_DIR, "scripts"))

import bpy

pr = importlib.import_module(os.path.basename(_ADDON_DIR))
deploy = importlib.import_module("deploy")

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


# ===========================================================================
# The two literals
# ===========================================================================
check("the deploy script and the addon agree on the marker's name",
      deploy.DEV_MARKER_NAME == pr.prefs.DEV_MARKER_NAME,
      f"{deploy.DEV_MARKER_NAME!r} vs {pr.prefs.DEV_MARKER_NAME!r}")

# Read as source too, so this still fails if one of them is ever computed at
# import time from the other's absence rather than simply declared.
with open(os.path.join(_ADDON_DIR, "scripts", "deploy.py"), encoding="utf-8") as handle:
    tree = ast.parse(handle.read())
literals = [node.value.value for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "DEV_MARKER_NAME" for t in node.targets)
            and isinstance(node.value, ast.Constant)]
check("and it is a plain literal in the deploy script", literals == [".deployed"], literals)

# A marker shipped in a release would turn Developer Mode on for someone who
# installed a zip -- the exact audience the mode is hidden from.
check("the marker is excluded from what a release ships",
      deploy.DEV_MARKER_NAME in deploy.SKIP_DIRS, sorted(deploy.SKIP_DIRS))

# ===========================================================================
# Deploying really writes one
# ===========================================================================
temp = tempfile.mkdtemp(prefix="retop_deploy_")
try:
    target = deploy.deploy(temp)
    marker = os.path.join(target, deploy.DEV_MARKER_NAME)
    check("a deploy leaves a marker in the copy it made", os.path.isfile(marker), marker)
    with open(marker, encoding="utf-8") as handle:
        stamp = handle.read().strip()
    check("carrying a stamp, not an empty flag", stamp != "", repr(stamp))
    # Two deploys must differ, or Developer Mode could only ever come back on
    # once: the second deploy would look like the one already seeded.
    second = deploy.deploy(temp)
    with open(os.path.join(second, deploy.DEV_MARKER_NAME), encoding="utf-8") as handle:
        check("and a different one each deploy", handle.read().strip() != stamp, stamp)
    check("the scripts folder is not deployed, which is why the name is duplicated",
          not os.path.isdir(os.path.join(target, "scripts")))
finally:
    shutil.rmtree(temp, ignore_errors=True)

# ===========================================================================
# What the addon reads
# ===========================================================================
# This checkout is not a deployed copy, so there is nothing to read.
check("an undeployed checkout reports no stamp", pr.prefs.deploy_stamp() == "",
      pr.prefs.deploy_stamp())

written = os.path.join(_ADDON_DIR, pr.prefs.DEV_MARKER_NAME)
try:
    with open(written, "w", encoding="utf-8") as handle:
        handle.write("2026-09-07T12:00:00.000000\n")
    check("and a deployed one reports what the deploy wrote",
          pr.prefs.deploy_stamp() == "2026-09-07T12:00:00.000000", pr.prefs.deploy_stamp())
    # Headless there is no addon entry, so `keymap.preferences()` is None and
    # the seeding has nothing to write to. It must be quiet about that rather
    # than raise: register() calls it on every load, deployed or not.
    try:
        pr.prefs.seed_developer_mode()
        seeded = True
    except Exception as exc:  # noqa: BLE001
        print(f"    seed_developer_mode raised: {exc!r}")
        seeded = False
    check("seeding is silent with no preferences to seed", seeded)
    check("and nothing headless starts reading as developer mode",
          pr.prefs.developer_mode() is False)
finally:
    if os.path.exists(written):
        os.remove(written)

check("the marker is cleaned up after the test", not os.path.exists(written))

print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
