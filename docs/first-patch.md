# Your first patch

Five minutes, one CAD part, one committed quad grid.

## 1. Start the session

Open the 3D view's N-panel, **Retop** tab, and press **Start Retop Session**.

!!! note "Object Mode only"

    The session refuses to start from Edit Mode, and the panel says which mode
    to leave rather than offering a dead button.

<!-- media: 6s. Panel visible, click Start Retop Session, viewport hints appear
     along the bottom. -->

## 2. Pick an object

Click a Plasticity-imported mesh. Three things happen:

- it is **selected**, so Blender's own isolate, frame and header all agree with
  the session;
- a result mesh called **`<Object>_Retop`** is created if it does not exist;
- the phase becomes **Patch**, and the viewport hints change.

Selecting `<Object>_Retop` itself and starting a session works too — it resolves
back to the source object rather than failing on a mesh that has no patch data.

## 3. Pick a surface

Hover the model. The patch under the cursor previews in orange, already filled
by whichever generator its shape asks for. Click to take it.

<!-- media: 10s. Hover across four adjacent faces of a part so the orange
     preview jumps face to face, then click one. -->

!!! tip "Turn the CAD edges on"

    Press <kbd>E</kbd>. The borders between Plasticity faces are drawn from the
    face ids in the mesh — that is what a "patch" means, and seeing them makes
    hovering predictable instead of a guess.

## 4. Adjust

You are now in the **Adjust** phase. The patch is a live preview; nothing has
been written yet.

| | |
|---|---|
| <kbd>Ctrl</kbd> + wheel | Density up/down |
| <kbd>0</kbd>–<kbd>9</kbd> | Type a span directly |
| <kbd>Tab</kbd> | Switch U/V (quad and wedge patches) |
| <kbd>N</kbd> | N-gon mode (flat faces) |
| <kbd>Esc</kbd> | Discard |

The panel names the generator that ran and how many sides it found. Plain wheel
still zooms.

## 5. Commit

Right-click, or <kbd>Enter</kbd>, or left-click where no side is under the
cursor. The grid is welded into `<Object>_Retop` and you drop straight back to
picking the next surface.

<!-- media: 20s. Commit four adjacent patches in a row without leaving the
     Adjust/Patch loop, so the "commit drops you back to picking" rhythm is
     visible. -->

## 6. Do the neighbour

Pick the face next door and commit it too. You did not have to match anything:
**a side bordering finished retopology takes that neighbour's own vertices
automatically**, so the two patches share their boundary points exactly.

That is [side matching](guide/matching.md), and it is on by default.

## Changing your mind

Click a patch you already committed. Its faces are removed **on the spot** — you
see the patch disappear and the fresh grid take its place — and it reopens with
the spans it was committed with.

- **Commit** keeps the new version.
- **Discard** (or <kbd>Esc</kbd>, or leaving the object, or ending the session)
  puts the old patch back exactly as it was.
- <kbd>X</kbd> deletes it and commits nothing in its place.

Removing on pick rather than on commit is deliberate: if the addon picked the
wrong faces you find out immediately, instead of ending up with two overlapping
surfaces after the commit.

## Stepping back out

<kbd>Esc</kbd> goes back one level each press: **Adjust** → **Patch** →
**Object** → session ends.

<kbd>Ctrl</kbd>+<kbd>Z</kbd> is not a session key — it is Blender's, and one step
is one committed patch: press it while picking and the last patch comes back off
the result mesh. Keep pressing and you reach the state from before the session
started, which is where the session itself ends;
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> puts it all back.
