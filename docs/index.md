# Plasticity Retop

**Patch-based retopology for CAD meshes in Blender.**

Plasticity already offers a few export options that can help with topology,
but the assets could still be optimized to be more game-ready.
This addon aims to make the process of retopologizing those Plasticity CAD meshes in Blender
easier, with tools to create and edit patches.

<video autoplay loop muted playsinline poster="assets/img/overview.jpg">
  <source src="assets/video/overview.webm" type="video/webm">
</video>

**Click to create/edit patches.** The plugin identifies plasticity patches, you
can then click them to select them. Plasticity Retopo will then try to select the
best geometry generator to fill the path.

**Match neighbour patches.** Plasticity Retopo will try to figure out how to
connect the currently selected patch to its neighbours, welding their vertices
together.

**Plasticity-like controls.** The plugin intends to be easy to use, with a
control scheme familiar to Plasticity and access to Blender's tools for editing
meshes. The keybinds are re-mappable in the plugin settings.

## Start here

- [**Installation**](installation.md) – Blender 4.2+, the bridge, and the deploy script.
- [**Your first patch**](first-patch.md) - session start to committed quad grid, in five minutes.
- [**General Knowledge**](general.md) – information about the workings of the plugin.
- [**How it works**](how-it-works/index.md) – the whole pipeline, from hovering a surface to committing it.
- [**Keymap**](reference/keymap.md) – every binding, and where to remap it.

## What it is not

!!! note "Independent project"

    Plasticity Retop is not affiliated with [Plasticity](https://www.plasticity.xyz/)
    or with the [plasticity-blender-addon](https://github.com/nkallen/plasticity-blender-addon)
    bridge. It reads what the bridge writes; it never talks to Plasticity itself.

    It is inspired by the Maya/Blender *Retop Tool* (MayaMatters) and is an
    independent implementation of that idea.

**Plasticity does not have to be running.** The bridge is needed once, at import
time. After that the mesh carries everything this addon reads, and you can retop
a file on a machine that has never seen Plasticity.
