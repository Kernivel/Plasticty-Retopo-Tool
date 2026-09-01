# Plasticity Retop

A Blender addon for patch-based retopology of CAD meshes imported through the
Plasticity ↔ Blender bridge.

## Setting up on a new machine

1. **Install Blender** (4.2+; developed against 5.1).
2. **Get this folder** onto the machine (git clone, or copy the directory).
3. **Deploy it:**
   ```bash
   python scripts/deploy.py
   ```
   Then enable *Plasticity Retop* in `Preferences > Add-ons`.
4. **Check everything works:**
   ```bash
   python scripts/run_tests.py
   ```
   This needs Blender only — no Plasticity, no bridge.

To actually retopologize your own models you additionally need Plasticity and
the [plasticity-blender-addon](https://github.com/nkallen/plasticity-blender-addon)
bridge to import meshes. The bridge is only required at import time; once a
mesh is in Blender it carries everything this addon reads.

## Using it

Open the **Retop** tab in the 3D view's N-panel and hit **Start Retop Session**:

1. **Pick an object** — click a Plasticity-imported mesh. Its retopology mesh
   (`<Object>_Retop`) is created if needed and highlighted.
2. **Pick a surface** — hover to preview, click to select a patch.
3. **Adjust & commit** — tune the spans, then commit. You drop straight back to
   picking the next surface.

Esc steps back out one level at a time (patch → object → end session).

**Changing a patch you already committed:** click it again. Its existing faces
are removed on the spot — you see the patch disappear and the fresh grid take
its place — and it reopens with the spans it was committed with. Commit to keep
the new version, or **Discard** to put the old patch back exactly as it was
(same for Esc, leaving the object, or stopping the session mid-edit).

The panel says how many faces were removed. If it says it couldn't find them,
committing would leave the old surface overlapping the new one — that means the
retopology in the viewport doesn't belong to the `<Object>_Retop` mesh this
session writes to (the panel names it, with its face and patch count, while
you're picking surfaces).

Already-committed neighbours keep their own spans, so a shared edge whose span
you changed can show a crack until you re-edit the neighbour to match.

Retopology committed by an older version of the addon carries no per-face patch
tag, so it is claimed back automatically the first time you enter its object in
a session (the console logs how many faces were adopted). Those patches reopen
on their propagated spans rather than the exact ones you originally typed.

| Key (while adjusting) | Action |
|---|---|
| `Ctrl` + wheel | Span +/- |
| `0`–`9`, `Backspace` | Type a span directly |
| `Tab` | Switch U/V (quad and wedge patches) |
| `M` | Side highlight on/off |
| Click a side | Match the committed neighbour across it |
| `Ctrl` + click a side | Match that side's own CAD edge instead |
| Right click / `Enter` | Commit |
| `Esc` | Clear typing, then discard |

| Key (while picking a surface) | Action |
|---|---|
| Click | Pick a surface — again on a done one to re-edit it |
| `Tab` | Hand-edit the mesh (see below) |
| `Esc` | Leave the object |

| Key (any phase) | Action |
|---|---|
| `E` | Plasticity edges on/off |
| `Ctrl` + `E` | Surface flow on/off |
| `Alt` + `X`, then `X`/`Y`/`Z` | Mirror the retopology on that axis |
| `Shift` + `X` | Draw the retopology through everything on/off |
| `/` | Isolate, retopology included |

Wheel without `Ctrl` still zooms.

**Every key above is a normal Blender keymap item.** Change them in the addon's
preferences — the panel's Keybinds tab has a button that opens it, or find them
under Preferences > Keymap > Add-ons > 3D View. They're ordinary rows: click
the key field, press a new key, and the restore arrow puts one back. Three of
them share `Tab` and the phase picks which applies.

Not remappable: the digits and Backspace (numeric entry, not a shortcut), and
the mirror's `Alt`+`X` then an axis, which is a key *sequence* Blender's keymap
can't express. A left click only falls back to committing when there's no side
under the cursor — taking the side is a normal binding like any other.

`Ctrl`+`Z` is Blender's own and isn't listed in the viewport hints — but it's
worth knowing what one step means here:

**Undo** — one step is one patch: `Ctrl`+`Z` while picking
takes the last committed patch back off the result mesh, again for the one
before it, and so on. Deleting a patch and discarding a re-edit are steps of
their own too. Keep pressing and you eventually reach the state from before the
session started, which is where the session itself ends — `Ctrl`+`Shift`+`Z`
puts everything back, and you can start a new session on the same object and
carry on.

## Matching a neighbour

Two patches only weld if their shared boundary carries the *same vertices*, not
merely the same count — a neighbour committed as an n-gon put its points where
the boundary curves, and a grid resampling evenly to the same count lands
between them every time. So a side takes the neighbour's own committed
vertices, and the generator is told the count that reproduces them.

With **Match Committed Neighbours** on (the default), that happens by itself on
every side whose neighbour is already retopologized, for every generator. It
only ever takes an exact match; the **Match Margin** is for sides you point at,
where you have said which neighbour you mean.

A side can only match the Plasticity faces it actually borders — the mesh
records which face is across each boundary segment, so a patch running close by
but not touching is never picked up. When a side's neighbour isn't
retopologized yet, the panel and the status bar say which one it is waiting for.

A grid has one span per *direction*, so two sides wanting different counts along
the same axis cannot both be honoured: the pinned one wins, then the denser one,
and the panel reports how many were outvoted. Only the winner's vertices are
substituted, so a side that lost keeps the boundary the CAD drew rather than a
resampled version of someone else's.

Changing a span away from a neighbour's count releases that match — asking for a
different count is asking not to weld — while a side you pinned by hand keeps
its count regardless.

`Ctrl` + click pins a side to its **own CAD tessellation** instead, thinned by
curvature the way n-gon mode does it. That needs no neighbour at all, so it
works on the first patch of a model and on any side facing nothing yet.

## Mirroring

`Alt`+`X`, then `X`, `Y` or `Z`: the retopology is mirrored across that axis of
the **source object's** origin. Press the same axis again to turn it off; the
three are cumulative. The Output tab shows which are on and lets you click them
directly.

It's a Mirror modifier on `<Object>_Retop`, not baked geometry, and that is
what keeps it out of everything else's way: commit, re-edit, neighbour matching
and shading all read the mesh's real data, so the mirrored half is invisible to
them. The flip side is that **the mirrored half isn't real** — you can't pick a
patch on it, re-edit it, or match a side against it. Retop one half; the other
follows.

*Clip at the Plane* (on by default) stops a vertex being dragged across the
centre line while hand-editing and holds the ones already on it there, and
*Mirror Merge Distance* closes the seam down the middle.

When the retopology is done, **Apply Mirror** turns it into real geometry. Use
that button rather than the modifier dropdown: a mirrored face copies the patch
id of the face it came from, and re-editing that patch would then delete both
halves and rebuild only one. The button leaves the copies untracked instead, so
nothing deletes them, and entering the object again hands each one to the
Plasticity face it actually sits on — which, on a symmetric part, is the real
face on the other side, so the mirrored half becomes patches you can re-edit
like any other. Mirror a patch out over *empty space* and there is no face
there to claim it, so it joins the patch it was copied from and a later re-edit
of that patch takes it along.

## Fixing it by hand

Matching does not always find what you meant — a neighbour too coarse to
follow, two CAD edges tessellated differently, a side that came back one vertex
short. `Tab`, while picking a surface, hands `<Object>_Retop` to Blender's own
Edit Mode with everything a manual pass needs already set up:

- **vertex snapping, including onto the mesh being edited** — the default snaps
  to *other* objects only, which is exactly the case you don't want here;
- **auto-merge**, so dragging a vertex onto its twin welds it on the spot
  instead of leaving a seam for a Merge by Distance you have to remember;
- **Face Nearest** on top, so a dragged vertex stays on the CAD surface (turn
  *Snap to CAD Surface* off when the surface is in your way);
- **vertex select mode**.

From there it is all Blender: `K` knife, `Ctrl`+`R` loop cut, `J` to connect
selected vertices, `G` to move, `M` to merge. `Tab` comes back to the session.

Your own snapping and auto-merge settings are saved on the way in and put back
on the way out — including when the session ends mid-edit. The two settings the
panel exposes (*Auto Merge*, *Auto-Merge Distance*, *Snap to CAD Surface*, on
the Picker tab) are read when Edit Mode opens, so changing one mid-edit takes
effect on the next trip.

On the way back, the addon re-adopts the faces the knife created onto the patch
they sit on, and drops the corner identities the new vertices inherited — a
vertex the knife made carries a copy of a neighbour's "I am CAD corner N" tag,
and without clearing it the next commit that touched that corner would weld
onto the wrong point. The status line says how many of each it dealt with.

Only while *picking* a surface, not while adjusting one: a patch open for
adjustment has its faces out of the result mesh with only a snapshot to put
them back, and Blender discards writes to a mesh it holds in Edit Mode. Commit
or `Esc` first.

## Faces with a hole

A CAD face bounded by two loops — a slot cut through a panel, or a tube-like
face with two rims (a fillet running all the way round, a cylinder wall) — is
filled with a band of quads running **around** the loops and **across** the gap
between them. Those are the two spans; `Tab` switches which one the wheel
drives. The panel names it `Ring (2 loops, N corners)`.

Two loops is not the same thing as a band, though. A plate with a small hole is
also bounded by two loops, and a band across it is a disaster: both loops must
end up with the same number of points, so either the hole gets a hundred of them
or the outline gets twelve, and every quad is stretched the width of the plate.
Those faces are filled as an n-gon instead (outer boundary plus hole, bridged
with two edges) and the panel says why.

For a genuine band, the two loops are matched by arc length rather than by
pairing their corners, so it does its best work when the hole roughly follows
the outer boundary. Spans are propagated *out* of a ring to its neighbours, but
not into it, since "around" is one number for the whole loop.

More than one hole in a single face isn't handled: only the outer boundary is
used and the panel says so, rather than quietly paving over the holes.

## Seeing the CAD structure

The bridge sends a triangle soup, so a Plasticity import reads as one
undifferentiated field of triangles even though the mesh records which triangle
belongs to which CAD face. Two overlays put that structure back (Display tab, or
`E` / `Ctrl`+`E` during a session):

- **CAD edges** — the borders between Plasticity faces, with a dot on every
  B-rep vertex (the junctions where two CAD edges meet, which are also the only
  points patches weld to each other by). Rebuilt from the face ids in the mesh:
  exact, and needing no live bridge connection.
- **Surface flow** — the grid each face would be retopologized into, at a low
  density. Plasticity's own isoparametric curves are *not* in the bridge data;
  the protocol carries no surface parameters at all. These are derived from each
  face's boundary by the same Coons interpolation the generators use, which on a
  fillet or a swept face lands very close to the real isoparms — but they are
  derived, not imported.

Both can be scoped to the whole object or to the patch under the cursor.

## Development

See [CLAUDE.md](CLAUDE.md) for architecture, the input-data contract, and the
invariants worth not breaking.

```bash
python scripts/run_tests.py      # headless suite
python scripts/deploy.py         # push to Blender's addons folder
```

**[RESULTS.md](RESULTS.md)** is the current benchmark: every patch of every
fixture shape retopologized and measured — deviation from the CAD surface,
topology, cell quality — plus the known gaps. It is generated, never
hand-written:

```bash
blender tests/fixtures/TestCases.blend --background --python scripts/gen_results.py
```

The fixtures behind it are real Plasticity output imported through the bridge;
[tests/fixtures/README.md](tests/fixtures/README.md) says what each shape is
for and what it deliberately does not cover.

No system Python? Both scripts are plain stdlib, so Blender's own interpreter
runs them — on Windows:

```bash
"C:/Program Files/Blender Foundation/Blender 5.0/5.0/python/bin/python.exe" scripts/deploy.py
```

(and `blender --background --factory-startup --python tests/test_operators.py`
runs a test file directly). Check the version string in the panel afterwards:
if it hasn't changed, the deploy didn't land and you're still running old code.

Blender caches Python modules, so after deploying press **Reload Addon Only**
in the panel rather than Blender's global "Reload Scripts". The panel shows
`version.py`'s version/build string — bump it with every change so you can
tell at a glance whether a reload actually landed.
