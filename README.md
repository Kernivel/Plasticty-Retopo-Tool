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
| Right click / `Enter` | Commit |
| `Esc` | Clear typing, then discard |

Wheel without `Ctrl` still zooms.

## Faces with a hole

A CAD face bounded by two loops — a slot cut through a panel, or a tube-like
face with two rims (a fillet running all the way round, a cylinder wall) — is
filled with a band of quads running **around** the loops and **across** the gap
between them. Those are the two spans; `Tab` switches which one the wheel
drives. The panel names it `Ring (2 loops, N corners)`.

The two loops are matched by arc length rather than by pairing their corners,
so it does its best work when the hole roughly follows the outer boundary. A
hole of a very different shape (or tucked into a corner) comes out distorted —
splitting the face along an isoparm in Plasticity and refreshing through the
bridge remains the better answer there, and the addon handles the pieces
normally. Spans are propagated *out* of a ring to its neighbours, but not into
it, since "around" is one number for the whole loop.

More than one hole in a single face isn't handled: only the outer boundary is
used and the panel says so, rather than quietly paving over the holes.

## Development

See [CLAUDE.md](CLAUDE.md) for architecture, the input-data contract, and the
invariants worth not breaking.

```bash
python scripts/run_tests.py      # headless suite
python scripts/deploy.py         # push to Blender's addons folder
```

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
