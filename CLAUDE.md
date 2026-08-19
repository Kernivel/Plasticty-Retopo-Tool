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

There may be no system Python (Windows' `python` can be the Store stub, and
`py` may not exist). Both scripts are stdlib-only, so run them with Blender's
bundled interpreter — `<Blender>/<ver>/python/bin/python.exe` — or invoke a
test file straight through Blender:
`blender --background --factory-startup --python tests/test_operators.py`.
**Always confirm the panel's version string changed after deploying**: a deploy
that never ran looks exactly like a feature that doesn't work.

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
before the N-Side fallback (5+). `generators/ring.py` is **not** in that list:
a band is recognised by its patch having two boundary loops, not by a side
count, so `_generate_for_face` reaches for `generators.RING` directly.

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
- **Re-editing removes the old patch on pick, and can always put it back.**
  Every baked face carries `retop_patch_face_id` and every patch its own spans
  (`retop_patch_spans`). Picking a patch that already has geometry reopens it
  with those spans *and immediately deletes its faces*
  (`remove_patch_from_result`) after snapshotting the whole result mesh into a
  spare datablock. Removing on pick, not on commit, is deliberate: the patch
  visibly disappears, so a failure to identify it shows up at once instead of
  turning into two overlapping surfaces after the commit. Every exit that isn't
  a commit — Discard, Esc, leaving the object, `end_session`, a reload — must go
  through `restore_reedit_removal`, and commit through `keep_reedit_removal`.
  The delete uses `context='FACES'` so vertices still used by a neighbour
  survive and the new grid welds back onto them. Creating the face-id layer on a
  result mesh that predates it must stamp `NO_PATCH` on the existing faces — a
  fresh int layer defaults them to 0, i.e. "patch 0".
- **Retopology committed before face tracking existed is claimed on entry.**
  `mesh_build.adopt_untracked_faces` (called from `enter_session_object` and
  `set_active_patch`) classifies each untagged result face onto the source
  patch it sits on, by nearest source polygon, voting with the face centre
  (weighted) plus its verts. Without it those patches read as "never retopped"
  and re-editing silently doubled them up. On anything short of a strict
  majority the face keeps `NO_PATCH`: unclaimed faces are never deleted, so a
  misread degrades to a duplicate, never to a hole in a neighbour. One pass per
  result mesh, marked by `retop_patch_adoption`. Removal for a re-edit uses a
  looser rule (face centre only) since it's visible and reversible.
- **A patch can have more than one boundary loop, and their order is random.**
  `compute_boundary_loops` walks a *set* of half-edges, so "loop 0" of a face
  with a hole is as likely to be the hole as the face. Anything reducing a
  patch to one loop goes through `patch_data.sort_loops_outer_first` (largest
  extent first). Two loops = a band, filled by the Ring generator; more than
  two = only the outer loop is used, and `state.num_loops` makes the panel say
  so rather than silently paving over the holes.
- **The two loops of a ring must resample to the same point count.** Both go
  through `ring.around_count`, which floors the "around" span at each loop's
  side count (a side can't get zero segments). The commit path re-derives the
  per-side allocation with that same helper to register spans per loop —
  pairing corners cyclically across both loops' ids would invent a side running
  from the outer boundary to the hole.
- **Everything resolves through `<Source>_Retop`.** Rename or re-import the CAD
  object and its retopology becomes unreachable — a session on the new name
  starts a second result mesh that overlaps the first. `orphan_result_objects`
  exists to say so in the panel rather than let it look like a broken re-edit.
- **Creating or freeing a datablock outside an undo step crashes Ctrl+Z.**
  Blender's undo restores a memfile snapshot; an ID created between two steps
  isn't in it, and the depsgraph then walks an object whose data or material
  array was freed under it (`DepsgraphNodeBuilder::build_materials`, null read
  — that's the crash reported on 2026-08-17). So: **no ID creation from
  property update callbacks, draw handlers or hovers.** The preview object is
  created once by `enter_session_object` and only ever has its *geometry*
  rewritten afterwards (`clear_preview_object` empties it,
  `remove_preview_object` is session teardown only); materials are made by
  `ensure_materials` at the same moment, and every `refresh_*_appearance` path
  is get-only. The three structural moments — entering an object, starting a
  re-edit, ending the session — call `operators.push_undo`. `undo_post`/
  `redo_post` run `_on_undo_redo`, which drops the active patch and any re-edit
  snapshot (undo has just replaced the mesh state they described) and touches
  **scene properties only**.
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
watches to return to picking. Clicking a patch that's already committed enters
`ADJUST` in re-edit mode (`state.editing_committed`): same keybinds, but commit
replaces the existing patch.

Keybinds in `ADJUST`: Ctrl+wheel = span, `0-9`/Backspace = type a span,
Tab = U/V (quad/wedge), right-click or Enter = commit, Esc = clear typing then
discard. Plain wheel stays zoom.

## Status

Implemented: Quad, Triangle, Wedge (2 sides), N-Side (5+, midpoint
quadrangulation), Ring (two boundary loops: a face with a hole, or a tube-like
face — this is the Cylinder case), span propagation, per-patch UVs, boundary
welding, viewport session with overlay, re-selecting a committed patch to
change its spans (replaces it in place).

Not implemented yet: **Ring with corner matching** (the two loops are paired by
arc length, so a hole shaped very differently from the outer boundary distorts
the band, and spans don't propagate *into* a ring), faces with **more than one
hole** (outer loop only, panel warns), **Quad Fill** with configurable loop
cuts, **N-Side** with per-side spans and manual corner placement, quad-family
(solving a chain of connected quads in one click).
