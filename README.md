# Plasticity Retop

A Blender addon for patch-based retopology of CAD meshes imported through the
Plasticity ↔ Blender bridge. You click a surface, it proposes clean quad
topology that follows the CAD curvature (micro-fillets included), you tune the
span counts live, and commit patch after patch into a single result mesh.

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

| Key (while adjusting) | Action |
|---|---|
| `Ctrl` + wheel | Span +/- |
| `0`–`9`, `Backspace` | Type a span directly |
| `Tab` | Switch U/V (quad and wedge patches) |
| Right click / `Enter` | Commit |
| `Esc` | Clear typing, then discard |

Wheel without `Ctrl` still zooms.

## Development

See [CLAUDE.md](CLAUDE.md) for architecture, the input-data contract, and the
invariants worth not breaking.

```bash
python scripts/run_tests.py      # headless suite
python scripts/deploy.py         # push to Blender's addons folder
```

Blender caches Python modules, so after deploying press **Reload Addon Only**
in the panel rather than Blender's global "Reload Scripts". The panel shows
`version.py`'s version/build string — bump it with every change so you can
tell at a glance whether a reload actually landed.
