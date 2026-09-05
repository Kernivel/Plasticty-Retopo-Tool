"""Copy this addon into Blender's addons folder.

    python scripts/deploy.py            # auto-detect the newest Blender config
    python scripts/deploy.py --list     # show the config dirs it found
    python scripts/deploy.py --dest DIR # copy into a specific addons folder

Blender caches imported modules, so after deploying use the panel's
"Reload Addon Only" button (or restart Blender) to pick the new code up.
"""
import argparse
import os
import platform
import shutil
import sys

ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_NAME = os.path.basename(ADDON_DIR)

# Names never copied into Blender's addons folder -- directories and files
# alike, since shutil.copytree's ignore callback is handed both. The docs
# site lives in this repo (see docs/), and a Blender addon has no use for it.
SKIP_DIRS = {
    "__pycache__", ".git", ".github", ".gitignore", ".idea", ".junie",
    "tests", "scripts",
    "docs", "site", "mkdocs.yml", "requirements-docs.txt",
    # Release zips, written by scripts/build_zip.py. Shipping a copy of the
    # addon *inside* the addon is the kind of thing nobody notices until the
    # download is twice the size it should be -- and the builder walks this
    # same list while the zip it is writing already exists on disk.
    "dist",
}


def blender_config_roots():
    system = platform.system()
    home = os.path.expanduser("~")
    if system == "Windows":
        appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        return [os.path.join(appdata, "Blender Foundation", "Blender")]
    if system == "Darwin":
        return [os.path.join(home, "Library", "Application Support", "Blender")]
    return [
        os.path.join(home, ".config", "blender"),
        os.path.join(home, ".blender"),
    ]


def _version_key(name):
    try:
        return tuple(int(part) for part in name.split("."))
    except ValueError:
        return (-1,)


def find_addon_dirs():
    """Every <config>/<version>/scripts/addons that exists, newest last."""
    found = []
    for root in blender_config_roots():
        if not os.path.isdir(root):
            continue
        for version in sorted(os.listdir(root), key=_version_key):
            addons = os.path.join(root, version, "scripts", "addons")
            if os.path.isdir(os.path.join(root, version)):
                found.append(addons)
    return found


def deploy(dest_addons_dir):
    target = os.path.join(dest_addons_dir, ADDON_NAME)
    os.makedirs(dest_addons_dir, exist_ok=True)

    if os.path.isdir(target):
        shutil.rmtree(target)

    def ignore(_dir, names):
        return {n for n in names if n in SKIP_DIRS or n.endswith(".pyc")}

    shutil.copytree(ADDON_DIR, target, ignore=ignore)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", help="addons directory to copy into")
    parser.add_argument("--list", action="store_true", help="list detected addons directories")
    args = parser.parse_args()

    candidates = find_addon_dirs()

    if args.list:
        if not candidates:
            print("No Blender config directory found. Start Blender once, or pass --dest.")
            return 1
        for path in candidates:
            print(path)
        return 0

    dest = args.dest
    if dest is None:
        if not candidates:
            print("No Blender config directory found. Start Blender once so it creates its\n"
                  "config folder, or pass --dest <addons dir>.", file=sys.stderr)
            return 1
        dest = candidates[-1]  # newest version

    target = deploy(dest)
    print(f"Deployed {ADDON_NAME} -> {target}")
    print("Enable it in Preferences > Add-ons, then use 'Reload Addon Only' after each change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
