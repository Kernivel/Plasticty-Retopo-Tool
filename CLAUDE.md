# Plasticity Retop — working notes

Blender addon: patch-based retopology for CAD meshes imported through the
[plasticity-blender-addon](https://github.com/nkallen/plasticity-blender-addon)
bridge. Inspired by the Maya/Blender "Retop Tool" (Patreon: MayaMatters);
this is an independent implementation.

## Commands

```bash
python scripts/run_tests.py          # headless test suite (needs Blender only)
python scripts/deploy.py             # copy into Blender's addons folder
python scripts/deploy.py --list      # show detected Blender config dirs
```

Blender is found via `--blender`, `$BLENDER`, `PATH`, then usual install
paths. Plasticity itself is **not** needed to develop or test: the tests build
synthetic meshes carrying the same custom properties the bridge writes.

After deploying, use the panel's **Reload Addon Only** button — plain
"Reload Scripts" can silently half-fail when another installed addon errors
during its own reload.

Bump `version.py` (`ADDON_VERSION` / `BUILD_ID`) on every change: the panel
shows it, and it's the only reliable way to confirm a reload actually took.

## Input data contract

The bridge writes two custom properties on each imported mesh:

- `mesh["groups"]` — flat list of `[loop_start, loop_count]` pairs, polygon order
- `mesh["face_ids"]` — one Plasticity face id per group, same order

One Plasticity face = one **patch**. The bridge is only needed at import time;
nothing here talks to it at runtime.

**The bridge exports unwelded triangle soups** — vertices are not shared, even
between two triangles of the same face. Any topology work must first go through
`patch_data.build_weld_map()` (position-based KDTree merge). Skipping it makes
every internal triangulation edge look like a patch boundary.

## Architecture

| Module | Role |
|---|---|
| `patch_data.py` | mesh → patches, weld map, boundary loops |
| `sides.py` | corner detection (angle threshold), split loop into sides, merge small sides |
| `geometry.py` | Coons/transfinite grids, arc-length resampling, BVH, reprojection |
| `generators/` | one generator per patch type; `find_generator(n_sides)` picks the first match |
| `mesh_build.py` | preview object, committing into `<Source>_Retop`, span registry, appearance |
| `operators.py` | the session modal + commit/discard/reload operators |
| `overlay.py` | bottom-right keybind hints (GPU draw handler) |
| `state.py` | all scene properties; span props have live-update callbacks |
| `ui.py` | N-panel, collapsible sections |

Generator order matters: specialised ones (Wedge 2, Triangle 3, Quad 4) come
before the N-Side fallback (5+).

## Hard-won invariants — don't regress these

- **Welding across patches.** Only *corner* vertices are exact source-mesh
  vertices, so they're welded by identity (`retop_source_vid` attribute).
  Interior boundary points are span-dependent resamples: they're welded only
  by proximity, only among boundary-flagged verts, at
  `boundary_weld_distance`. An unscoped `remove_doubles` silently merges
  unrelated points and drops faces.
- **Span propagation** (`mesh_build` span registry, JSON on the result object)
  keyed by corner-id pairs is what makes matching spans — and therefore
  seam-free welds — happen automatically between neighbours.
- **Never unregister an operator class from inside its own `execute()`** —
  that crashes Blender natively. `RETOP_OT_reload_addon` defers the real work
  to a `bpy.app.timers` callback.
- **Raycasting must skip the addon's own preview/result meshes**, or the hover
  flickers (ray hits the preview → "no patch" → preview deleted → rebuilt).
  It must also skip viewport-hidden objects (Local View `/`).
- **Hover hysteresis** keeps the current patch unless a new one is clearly in
  front; coincident CAD surfaces otherwise flip-flop every mouse move.
- **`context.region` / `region_data` are unreliable inside a modal** (may be
  the N-panel's region). Use `operators.viewport_region()` and window-absolute
  mouse coords, and pass clicks/scrolls through when the cursor isn't over the
  3D view — otherwise the panel's own buttons get swallowed.
- **Session state lives in the scene but the modal doesn't.** A reload or a
  crashed modal leaves `session_active` set with nothing listening;
  `operators.session_is_running()` detects it and the panel offers a reset.
- **Cosmetic offsets are Displace modifiers, never baked.** Commit reads the
  preview's *base* mesh; the result offset sets `show_render = False`.
- **Order matters in `end_session` / `exit_session_object`:** clear the state
  first, *then* call `refresh_result_appearance` — it derives every mesh's look
  from session state, so refreshing first re-applies what you're clearing.

## Session model (`RETOP_OT_session`)

`OBJECT` → click a Plasticity object → `PATCH` → click a surface → `ADJUST`
→ commit → back to `PATCH`. Esc: `ADJUST`→`PATCH`, `PATCH`→`OBJECT`,
`OBJECT`→ end. Commit clearing `active_face_id` is the signal the modal
watches to return to picking.

Keybinds in `ADJUST`: Ctrl+wheel = span, `0-9`/Backspace = type a span,
Tab = U/V (quad/wedge), right-click or Enter = commit, Esc = clear typing then
discard. Plain wheel stays zoom.

## Status

Implemented: Quad, Triangle, Wedge (2 sides), N-Side (5+, midpoint
quadrangulation), span propagation, per-patch UVs, boundary welding, viewport
session with overlay.

Not implemented yet: **Cylinder** (bands with two boundary loops — most wanted
for tube-like fillets), **Quad Fill** with configurable loop cuts, **N-Side**
with per-side spans and manual corner placement, quad-family (solving a chain
of connected quads in one click).
