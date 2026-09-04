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

## Updating

```bash
git pull
python scripts/deploy.py
```

Then **Reload Addon Only**, and check the version string. Your settings survive a
reload — Blender stores them on the scene, keyed by name.
