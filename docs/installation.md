# Installation

## Requirements

| | |
|---|---|
| **Blender** | 4.2 or newer (developed against 5.1) |
| **Plasticity** | Only to *import* a model — not to retop one |
| **Bridge** | [plasticity-blender-addon](https://github.com/nkallen/plasticity-blender-addon), also import-time only |

The bridge writes two custom properties on every mesh it imports, and those are
the entire input. Once a mesh is in your `.blend` it is self-sufficient: no live
connection, no Plasticity install, no bridge.

!!! warning "A mesh not imported through the bridge has no patches"

    Modelled-in-Blender geometry, an STL, an OBJ — none of them carry the
    Plasticity face ids, so there is nothing to divide into patches. The session
    says so rather than silently offering you a single patch.

## Installing the addon

Download the `.zip` from the
[latest release](https://github.com/Kernivel/Plasticty-Retopo-Tool/releases)
and **drag it into Blender**, or use `Edit > Preferences > Add-ons >
Install from Disk`. Then enable **Plasticity Retop** in the add-ons list.

To update, install the newer zip over it. There is nothing else to do and no
reload to remember: Blender replaces the installed copy and re-imports it.

!!! tip "The rest of this page is for working *on* the addon"

    Installing from a release zip is the whole story for using it. Everything
    below — deploying from a checkout, the reload buttons, the version string —
    is the development loop, and the reload buttons are hidden until you turn on
    **Developer Mode** in the addon's preferences.

## Working from a checkout

```bash
git clone https://github.com/Kernivel/Plasticty-Retopo-Tool.git
cd Plasticty-Retopo-Tool
python scripts/deploy.py
```

`deploy.py` finds Blender's addons folder and copies the package into it, leaving
out the tests, the scripts and this documentation. Then enable **Plasticity
Retop** in `Preferences > Add-ons`.

To pick a specific Blender:

```bash
python scripts/deploy.py --list          # show the config dirs it found
python scripts/deploy.py --dest "<addons dir>"
```

**No system Python?** Windows' `python` is often the Store stub, and `py` may not
exist. The script is stdlib-only, so Blender's own interpreter runs it:

```bash
"C:/Program Files/Blender Foundation/Blender 5.0/5.0/python/bin/python.exe" scripts/deploy.py
```

## Confirming it landed

Open the 3D view's N-panel, **Retop** tab, and look at the **System** tab's
version string.

!!! danger "A deploy that never ran looks exactly like a feature that doesn't work"

    Blender caches Python modules, so a fresh copy on disk is not a fresh copy in
    memory. **Always check the version string changed.** The panel also compares
    what Python is running against what `version.py` reads *on disk* and says so
    in red when they differ — and while that mismatch stands, every traceback
    cites line numbers that do not match the file you are reading.

After deploying, use the panel's **Reload Addon Only** button rather than
Blender's global *Reload Scripts*: the latter can quietly half-fail when another
installed addon errors during its own reload.

**Both buttons, and the red stale-code warning, are behind Developer Mode** —
`Preferences > Add-ons > Plasticity Retop > Developer Mode`, off by default.
Installed from a release zip there is nothing to reload against: one copy of the
code, replaced when you install the next zip.

## Updating a checkout

```bash
git pull
python scripts/deploy.py
```

Then **Reload Addon Only**, and check the version string. Your settings survive a
reload — Blender stores them on the scene, keyed by name.

## Building a release zip

```bash
python scripts/build_zip.py          # dist/<name>-<version>.zip
python scripts/build_zip.py --check  # verify only, write nothing
```

The zip holds one top-level folder with the addon inside — the shape Blender's
installer expects — and excludes exactly what `deploy.py` excludes. It refuses to
build when `bl_info["version"]` and `version.py` disagree, because those are the
two numbers Blender's add-on list and the N-panel each show.

Pushing a `v<version>` tag runs `.github/workflows/release.yml`, which builds the
same zip and attaches it to the GitHub release.
