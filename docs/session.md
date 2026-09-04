# Workflow

Retopologizing with this addon includes jumping back and forth between different
phases: picking a mesh, picking a patch, adjusting the patch, and (optionally)
tweaking the retopology in Edit Mode.

| Phase | You are | Left click | <kbd>Esc</kbd> |
|---|---|---|---|
| **Object** | choosing which mesh to retop | enter that object | end the session |
| **Patch** | choosing a surface | open that patch | leave the object |
| **Adjust** | tuning one patch | take the side under the cursor, or commit | clear typing, then discard |
| **Tweak** | in Blender's Edit Mode | Blender's | Blender's |

The viewport draws the keybinds that currently apply to the phase.

**One Plasticity face is one patch**, which is why hovering follows the CAD faces
exactly rather than an angle threshold — the mesh states the answer outright. See
[How it works](guide/generators.md) for where that comes from.

## Where the result goes

Committed geometry is written to a second object named **`<Source>_Retop`**,
filed under a `Retop` collection that mirrors the Inbox hierarchy the bridge
built.

!!! warning "The name is the link"

    Everything resolves through `<Source>_Retop`. Rename or re-import the CAD
    object and its retopology becomes unreachable — a session on the new name
    starts a *second* result mesh that overlaps the first. The panel says so
    rather than letting it look like a broken re-edit.

## Starting density

**Resolution** Presets are available for the starting density of the retopology
to avoid manually scrolling the spans too much.

| | Very Low | Low | Mid | High | Extreme |
|---|---|---|---|---|---|
| relative to computed | ¼ | ½ | 1 | 2 | 4 |


## The session and the rest of Blender

- **Outside the viewport, the session is not listening.** Move the pointer over
  the N-panel, the toolbar, or another editor and every event goes where it
  normally would. Session keybinds need the pointer over the 3D view, like
  Blender's own region keymaps.
- **Leaving Object Mode hands the viewport back.** Entering Edit Mode on the
  retopology is the normal way to hand-tweak it. The one exception: if the mesh
  being edited is the result mesh a re-edit took faces from, the session stays
  put, because those faces exist only in a snapshot and Blender discards writes
  to a mesh it holds in Edit Mode.
- **No key of the addon's is live outside a session.** Even the global three
  (<kbd>/</kbd>, <kbd>Alt</kbd>+<kbd>X</kbd>, <kbd>Shift</kbd>+<kbd>X</kbd>)
  hand the event straight on when no session is open, so Hard Ops' `Alt+X` and
  Blender's own isolate behave normally. An addon preference turns that off if
  you want them always live.

## When the session gets stuck

Session state lives on the scene, but the modal does not. A reload or a crashed
modal can leave the state set with nothing listening — the panel detects it and
offers a **reset**. See [Troubleshooting](reference/troubleshooting.md).
