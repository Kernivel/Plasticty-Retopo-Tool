"""Build the installable addon zip -- what a release attaches and what a user
drags into Blender.

    python scripts/build_zip.py                 # dist/plasticity_retop-<version>.zip
    python scripts/build_zip.py --dest DIR      # somewhere else
    python scripts/build_zip.py --check         # verify only, write nothing

The zip holds **one top-level folder**, named after the package, with the addon
inside it. That shape is not cosmetic: Blender installs a zip by extracting it
into the addons folder, so a zip whose files sit at the root scatters
`operators.py` and friends loose among every other addon, and the import
`from . import keymap` then has no package to be relative to.

What it leaves out is exactly what `deploy.py` leaves out, imported from there
rather than listed again -- two copies of that list would disagree the first
time a directory was added, and the failure (a release carrying the test suite,
the fixture .blend and the built docs site) is one nobody would notice.

Stdlib only, like every script here: there may be no system Python, so this
runs under Blender's own interpreter too --
`<Blender>/<ver>/python/bin/python.exe scripts/build_zip.py`.
"""
import argparse
import os
import re
import sys
import zipfile

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.dirname(_SCRIPTS)
ADDON_NAME = os.path.basename(ADDON_DIR)
sys.path.insert(0, _SCRIPTS)

import deploy  # noqa: E402 -- the skip list, so there is only one of it

_BL_INFO_VERSION = re.compile(r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
_ADDON_VERSION = re.compile(r'^ADDON_VERSION\s*=\s*"([^"]*)"', re.MULTILINE)


def read_versions():
    """(bl_info version, version.py version), both as "x.y.z" strings.

    Read out of the files as text rather than by importing them: `__init__.py`
    imports bpy on the very next line, and this script has to run under a plain
    Python as well as under Blender's.
    """
    with open(os.path.join(ADDON_DIR, "__init__.py"), encoding="utf-8") as handle:
        match = _BL_INFO_VERSION.search(handle.read())
    bl_info = ".".join(match.groups()) if match else ""

    with open(os.path.join(ADDON_DIR, "version.py"), encoding="utf-8") as handle:
        match = _ADDON_VERSION.search(handle.read())
    declared = match.group(1) if match else ""
    return bl_info, declared


def check_versions():
    """Refuse to build a zip whose two version numbers disagree.

    `bl_info["version"]` is what Blender's add-on list shows and what it
    compares when you install over an existing copy; `version.ADDON_VERSION` is
    what the N-panel shows and what every "did my deploy take?" check reads.
    They are two literals in two files and they drift silently -- bl_info sat
    at 0.1.0 through fifty-odd releases of the other one. Nothing can keep them
    in step automatically (Blender parses bl_info as source, before any of this
    code runs), so the build is where the disagreement has to be caught.
    """
    bl_info, declared = read_versions()
    if not bl_info or not declared:
        return f"could not read a version: bl_info={bl_info!r} version.py={declared!r}"
    if bl_info != declared:
        return (f"bl_info says {bl_info} but version.py says {declared} -- "
                f"set bl_info[\"version\"] to ({declared.replace('.', ', ')})")
    return ""


def iter_files():
    """Every path that goes into the zip, relative to the addon directory."""
    for root, dirs, names in os.walk(ADDON_DIR):
        dirs[:] = sorted(d for d in dirs if d not in deploy.SKIP_DIRS)
        for name in sorted(names):
            if name in deploy.SKIP_DIRS or name.endswith(".pyc"):
                continue
            path = os.path.join(root, name)
            yield path, os.path.relpath(path, ADDON_DIR)


def build(dest_dir):
    _bl_info, declared = read_versions()
    os.makedirs(dest_dir, exist_ok=True)
    out = os.path.join(dest_dir, f"{ADDON_NAME}-{declared}.zip")

    # Deterministic: sorted entries and a fixed timestamp, so rebuilding the
    # same commit gives the same bytes and a re-uploaded asset is provably the
    # same thing rather than merely the same size.
    # Listed before the archive is opened, never while: the output lives under
    # `dist/`, and a walk that starts after `ZipFile(...)` has created the file
    # finds it and packs the zip into itself.
    members = list(iter_files())
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, relative in members:
            info = zipfile.ZipInfo(f"{ADDON_NAME}/{relative.replace(os.sep, '/')}",
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as handle:
                archive.writestr(info, handle.read())
            count += 1
    return out, count


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", default=os.path.join(ADDON_DIR, "dist"),
                        help="directory to write the zip into (default: dist/)")
    parser.add_argument("--check", action="store_true",
                        help="verify the versions agree and write nothing")
    args = parser.parse_args()

    problem = check_versions()
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1

    _bl_info, declared = read_versions()
    if args.check:
        print(f"ok: version {declared}, {sum(1 for _ in iter_files())} files")
        return 0

    out, count = build(args.dest)
    size = os.path.getsize(out)
    print(f"wrote {out}")
    print(f"  version {declared}, {count} files, {size / 1024:.0f} KB")
    print("  install: drag it into Blender, or Edit > Preferences > "
          "Add-ons > Install from Disk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
