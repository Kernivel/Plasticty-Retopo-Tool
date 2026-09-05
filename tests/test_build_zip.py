"""Run inside Blender: blender --background --python tests/test_build_zip.py

The release zip: its shape, and the version check that guards it.

Two things here are the kind that rot silently. `bl_info["version"]` and
`version.ADDON_VERSION` are two literals in two files -- bl_info sat at 0.1.0
while the panel said 0.56.0 -- and Blender parses bl_info as *source*, before
any addon code runs, so nothing can derive one from the other. And the zip's
exclusion list lives in `deploy.py`; a second copy of it in the builder would
disagree the first time a directory was added, and a release quietly carrying
the test suite, the fixture .blend and the built docs site is not something
anyone would notice from the download page.
"""
import importlib
import os
import sys
import tempfile
import zipfile

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ADDON_DIR, "scripts"))

build_zip = importlib.import_module("build_zip")

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


# ===========================================================================
#  The two version literals
# ===========================================================================
bl_info, declared = build_zip.read_versions()
check("bl_info declares a version", bool(bl_info), bl_info)
check("version.py declares one too", bool(declared), declared)
check("and they agree -- otherwise Blender's add-on list and the N-panel "
      "disagree about what is installed",
      build_zip.check_versions() == "", build_zip.check_versions())


# ===========================================================================
#  The zip's shape
# ===========================================================================
with tempfile.TemporaryDirectory() as tmp:
    out, count = build_zip.build(tmp)
    check("it built something", os.path.isfile(out), out)
    check("named for the version in version.py", declared in os.path.basename(out),
          os.path.basename(out))

    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()

    # One top-level folder. Blender installs a zip by extracting it into the
    # addons folder, so files at the root scatter loose among every other
    # addon and `from . import keymap` has no package to be relative to.
    roots = {name.split("/")[0] for name in names}
    check("everything sits under one top-level folder", len(roots) == 1, roots)
    check("named after the package", roots == {build_zip.ADDON_NAME}, roots)

    check("the addon's entry point is in it",
          f"{build_zip.ADDON_NAME}/__init__.py" in names)
    check("and its generators package",
          any(name.startswith(f"{build_zip.ADDON_NAME}/generators/") for name in names))

    # What must never ship. The list is deploy.py's, imported rather than
    # restated -- this asserts the import actually took effect.
    unwanted = [name for name in names
                if "/tests/" in name or "/docs/" in name or "/site/" in name
                or "/scripts/" in name or "__pycache__" in name
                or name.endswith(".zip") or name.endswith(".pyc")]
    check("no tests, docs, scripts, caches or nested zips", not unwanted, unwanted)
    check("and nothing from dist/", not any("/dist/" in name for name in names))

    check("the file count matches what was written", count == len(names),
          f"{count} vs {len(names)}")

    # Deterministic, so re-running the same commit gives the same bytes and a
    # re-uploaded asset is provably the same thing rather than the same size.
    with open(out, "rb") as handle:
        first = handle.read()
    os.remove(out)
    build_zip.build(tmp)
    with open(out, "rb") as handle:
        second = handle.read()
    check("building it twice gives identical bytes", first == second,
          f"{len(first)} vs {len(second)}")


print()
if FAILURES:
    print(f"=== {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("=== ALL CHECKS PASSED")
