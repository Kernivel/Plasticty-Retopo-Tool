"""Run the addon's test suite inside Blender, headless.

    python scripts/run_tests.py
    python scripts/run_tests.py --blender /path/to/blender
    python scripts/run_tests.py tests/test_retop.py      # a single file

Blender is located in this order: --blender, the BLENDER env var, PATH, then
the usual install locations. No Plasticity install is needed: every test
builds its own synthetic meshes carrying the same custom properties the
Plasticity bridge writes.

The tests import the addon straight from this checkout, so they exercise the
working copy -- not whatever is currently deployed into Blender.
"""
import argparse
import glob
import os
import platform
import shutil
import subprocess
import sys

ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(ADDON_DIR, "tests")


def candidate_blender_paths():
    system = platform.system()
    if system == "Windows":
        roots = [
            r"C:\Program Files\Blender Foundation",
            r"C:\Program Files (x86)\Blender Foundation",
            r"D:\Blender",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Blender Foundation"),
        ]
        exe = "blender.exe"
    elif system == "Darwin":
        roots = ["/Applications"]
        exe = os.path.join("Blender.app", "Contents", "MacOS", "Blender")
        return [os.path.join(r, exe) for r in roots]
    else:
        roots = ["/usr/bin", "/usr/local/bin", "/snap/bin", os.path.expanduser("~/blender")]
        exe = "blender"

    paths = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        direct = os.path.join(root, exe)
        if os.path.isfile(direct):
            paths.append(direct)
        for entry in sorted(os.listdir(root)):
            nested = os.path.join(root, entry, exe)
            if os.path.isfile(nested):
                paths.append(nested)
    return paths


def find_blender(explicit=None):
    if explicit:
        return explicit
    env = os.environ.get("BLENDER")
    if env:
        return env
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    for path in candidate_blender_paths():
        return path
    return None


def run_one(blender, test_path):
    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python", test_path],
        capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    passed = "=== ALL CHECKS PASSED" in output
    return passed, output


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tests", nargs="*", help="test files (default: all of tests/)")
    parser.add_argument("--blender", help="path to the Blender executable")
    parser.add_argument("-v", "--verbose", action="store_true", help="print each test's full output")
    args = parser.parse_args()

    blender = find_blender(args.blender)
    if not blender or not os.path.isfile(blender):
        print("Blender not found. Install it, or pass --blender <path>, or set BLENDER=<path>.",
              file=sys.stderr)
        return 2
    print(f"Using Blender: {blender}\n")

    tests = args.tests or sorted(glob.glob(os.path.join(TESTS_DIR, "test_*.py")))
    if not tests:
        print("No tests found.", file=sys.stderr)
        return 2

    failures = []
    for test_path in tests:
        name = os.path.basename(test_path)
        passed, output = run_one(blender, test_path)
        print(f"{name:<24} {'PASS' if passed else 'FAIL'}")
        if args.verbose or not passed:
            # Only the check lines matter; Blender is noisy about other addons.
            for line in output.splitlines():
                if line.startswith(("[PASS]", "[FAIL]", "===")) or "Error" in line:
                    print("   ", line)
        if not passed:
            failures.append(name)

    print()
    if failures:
        print(f"{len(failures)} failing: {', '.join(failures)}")
        return 1
    print(f"All {len(tests)} test files passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
