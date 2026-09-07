# Installation

## Requirements

| |                                                                                                        |
|---|--------------------------------------------------------------------------------------------------------|
| **Blender** | 4.2 or newer (developed against 5.1)                                                                   |
| **Plasticity** | Only to *import* a model                                                                               |
| **Bridge** | [plasticity-blender-addon](https://github.com/nkallen/plasticity-blender-addon), also import-time only |

!!! warning "A mesh not imported through the bridge has no patches"

    Modelled-in-Blender geometry, an STL, an OBJ — none of them carry the
    Plasticity face ids, so there is nothing to divide into patches. The session
    says so rather than silently offering you a single patch.

## Installing the addon

Download the `.zip` from the
[latest release](https://github.com/Kernivel/Plasticty-Retopo-Tool/releases)
and **drag it into Blender**, or use `Edit > Preferences > Add-ons >
Install from Disk`. Then enable **Plasticity Retop** in the add-ons list.

To update, install the newer zip over it.

!!! tip "The rest of this page is for working *on* the addon"

    Instead of re-zipping when working on the addon you can use the `deploy.py`
    script and the reload button in the N-panel. Both belong to **Developer
    Mode**, which a deploy switches on for you -- see below.

## Working from a checkout

```bash
git clone https://github.com/Kernivel/Plasticty-Retopo-Tool.git
cd Plasticty-Retopo-Tool
python scripts/deploy.py
```

`deploy.py` finds Blender's addons folder and copies the package into it, leaving
out the tests, the scripts and this documentation. Then enable **Plasticity
Retop** in `Preferences > Add-ons`.

It also leaves a marker in the copy it made, and the addon reads that on load:
**Developer Mode turns itself on** the next time Blender loads the deployed
code, and again after every later deploy. Deploying is the statement that this
is a working copy, so there is nothing further to tick. You can still turn it
off, and it stays off until the next deploy.

!!! note "The first time, Blender has to load the addon again"

    Nothing can switch a preference on in a Blender that is already running --
    the deploy only copies files. So on the very first deploy, restart Blender
    or re-enable the addon; from then on the panel's **Reload Addon Only** is
    there and does it.

To pick a specific Blender:

```bash
python scripts/deploy.py --list          # show the config dirs it found
python scripts/deploy.py --dest "<addons dir>"
```

**No system Python?** You can still use Blender's own interpreter to run it:

```bash
"C:/MyBlenderInstallFolder/Blender <version>/python/bin/python.exe" scripts/deploy.py
```

For instance:
```bash
"C:/Program Files/Blender Foundation/Blender 5.0/5.0/python/bin/python.exe" scripts/deploy.py
```

## Confirming it landed

Open the **Retop** tab 3D view's **N-panel**,*and look at the **version number**.

After deploying, use the panel's **Reload Addon**

**Both buttons, and the red stale-code warning, are behind Developer Mode** —
`Preferences > Add-ons > Plasticity Retop > Developer Mode`, off by default.

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
