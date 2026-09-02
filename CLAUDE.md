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

# retopologize every patch of a real bridge export and measure the result:
# deviation from the CAD surface, topology, cell quality
blender tests/fixtures/TestCases.blend --background --factory-startup --python scripts/benchmark.py
blender tests/fixtures/TestCases.blend --background --factory-startup --python scripts/benchmark.py -- --resolution HIGH --object Cylinder

# regenerate the two documents derived from that fixture
blender tests/fixtures/TestCases.blend --background --factory-startup --python scripts/gen_results.py       # RESULTS.md
blender tests/fixtures/TestCases.blend --background --factory-startup --python scripts/gen_expectations.py  # the EXPECTED table
```

**`--factory-startup` is not optional on those four**, however harmless a
read-only script looks: run without it and every installed addon loads too, and
one of them *saved the fixture over itself* on quit (it left a `.blend1` beside
it, which is the tell). The file is frozen — `git status` after any run against
it, and `git checkout` it back if it moved.

`RESULTS.md` is that benchmark written up as tables, and `gen_expectations.py`
emits the golden table `tests/test_fixtures.py` asserts on. **Both are
generated — never hand-edit either.** A re-export of the fixture renumbers
every Plasticity face id even when no vertex moves, so a stale table makes
"the fixture changed" indistinguishable from "the code regressed"; regenerate
and read the diff instead, where generator and side count per face are the
entries that should hold steady.

`tests/fixtures/TestCases.blend` is real Plasticity output imported through the
bridge — the one place the input contract is tested rather than assumed, since
every other test builds its mesh from the same mental model as the code.
`tests/test_fixtures.py` pins what comes out of it, and
`tests/fixtures/README.md` says what each shape is for, what it deliberately
does *not* cover, and why the file must be treated as frozen. **Deviation is
measured across face interiors, never at vertices** — the generators reproject
interior vertices onto the surface by construction, so a vertex-only figure
reads ~0 on every shape and proves nothing.

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
during its own reload. A reload that leaves a module stale is the one failure
the version string cannot report; see the reload invariant below.

Bump `version.py` (`ADDON_VERSION` / `BUILD_ID`) on every change: the panel
shows it, and it's the only reliable way to confirm a reload actually took.
The panel also compares the constants Python holds in memory against what
`version.py` reads *on disk* (`version.stale_load()`) and says so in red when
they differ — that is the "I deployed and nothing changed" state, and the
tracebacks it produces cite line numbers that don't match the file you're
reading. Diagnose that mismatch before anything else. It only works if the
version was bumped, which is the discipline above.

## Input data contract

The bridge writes two custom properties on each imported mesh:

- `mesh["groups"]` — flat list of `[loop_start, loop_count]` pairs, polygon order
- `mesh["face_ids"]` — one Plasticity face id per group, same order

One Plasticity face = one **patch**. The bridge is only needed at import time;
nothing here talks to it at runtime.

**That is the whole of it — there is no edge data.** The wire protocol carries
`vertices, faces, normals, groups, face_ids` and nothing else (verified in the
bridge's `client.decode_object_data` / `handler.py`), so no edge ids and no
"this segment is a real CAD edge" flag. What the bridge *does* also apply is
Plasticity's own per-loop normals, as custom split normals with
`use_smooth = True` everywhere — the true surface normals, not facet ones.

The equivalent of edge identity is derivable anyway, from `face_ids` alone:
along a patch's boundary, each half-edge's opposite polygon names the
*neighbouring* patch, and the vertex where that neighbour changes is a genuine
B-rep vertex — the junction between two CAD edges. That is what
`patch_data.build_directed_owners` / `boundary_neighbours_for_loop` recover,
and what the topological corner detector runs on.

**The bridge tessellates each face separately, so patch borders are
duplicated.** The two faces meeting along a B-rep edge each carry their own
copy of every vertex on it, at the same position under different indices. Any
topology work must therefore go through `patch_data.build_weld_map()`
(position-based KDTree merge) before it can tell a patch border from a hole:
without it no boundary half-edge ever finds its opposite, so no patch can name
its neighbour and the topological corner test and `cad_display` have nothing
to run on.

*Inside* one face is a separate question, and the code no longer assumes an
answer. `build_weld_map` welds only `patch_data.weld_candidates` — the
vertices lying on an edge Blender's own connectivity leaves unshared (fewer
than two polygons on it). A vertex strictly inside a patch has a polygon on
both sides of every edge it touches, which means its neighbours already share
its index and there is no second copy of that point to merge it with. That
makes the scoping safe whichever way the bridge behaves: where a face's
triangles are natively shared the KD-tree only sees the borders, and where
they are not, every edge carries one polygon, `weld_candidates` returns None,
and the whole mesh goes in exactly as before (`tests/test_unwelded.py` pins
that end, `tests/test_weld_scope.py` the other).

The one behaviour genuinely given up: an interior vertex coincident with
something is no longer merged. That is a T-junction, which a B-rep kernel does
not emit, and merging it never affected the loops anyway.

The epsilon is `1e-5` **absolute, in the mesh's local units, and no caller
overrides it**. On a part whose coordinates run to a few hundred units the
float32 ulp is already the same order, so two faces' independently rounded
copies of a shared vertex can miss each other — which shows up as a phantom
patch border, hence wrong corners, wrong side count, wrong generator. Suspect
this before anything else when a patch dices strangely far from the origin.

## Architecture

| Module | Role |
|---|---|
| `constants.py` | generator names and the sets built from them; imports nothing, so `overlay` can share them with `operators` |
| `patch_data.py` | mesh → patches, weld map (scoped to border candidates), boundary loops, **and the per-mesh cache all of that lives in** (`analyse`) |
| `sides.py` | corner detection (angle and/or topology), corner *ranking*, split loop into sides, merge small sides |
| `geometry.py` | Coons/transfinite grids, arc-length resampling, BVH, reprojection |
| `generators/` | one generator per patch type; `find_generator(n_sides)` picks the first match |
| `cad_display.py` | B-rep edges/vertices recovered from `face_ids`, and the derived surface flow — cached, for the overlay |
| `patchprep.py` | one face → `PreparedPatch`: corners resolved, boundary split into sides, planarity |
| `sidematch.py` | side references, what each may match, pin kinds, span-collision resolution, substitution |
| `mesh_build.py` | preview object, committing into `<Source>_Retop`, span registry, committed-boundary cache, appearance, shading, collection mirroring |
| `keymap.py` | the keybind declaration + live-item lookup; leaf, so `overlay` can read it |
| `prefs.py` | the addon preferences page: Blender's own keymap rows |
| `tweak.py` | the Edit Mode round trip: tool-setting setup and restore |
| `operators.py` | the session modal + commit/discard/reload operators |
| `overlay.py` | keybind hints (POST_PIXEL) + every kind of dot; side highlight and CAD structure lines (POST_VIEW) |
| `state.py` | all scene properties; span props have live-update callbacks |
| `ui.py` | N-panel: persistent session/patch block + icon tabs (`state.ui_tab`) |

`patchprep` and `sidematch` are **leaves**: neither imports `operators`, which
is what keeps `overlay` able to read side references directly instead of
through a late import. Anything needing a session or a preview object stays in
`operators`.

Generator order matters: specialised ones (Wedge 2, Triangle 3, Quad 4) come
before the N-Side fallback (5+). `generators/ring.py` is **not** in that list:
a band is recognised by its patch having two boundary loops, not by a side
count, so `_generate_for_face` reaches for `generators.RING` directly.
`generators/ngon.py` is out of the list for a different reason: it's a *mode*
(`state.ngon_mode`, `N` during a session), not something a side count selects.

Two boundary loops does **not** by itself mean Ring: see the band invariant.

## Hard-won invariants — don't regress these

- **Nothing derived from a mesh is recomputed per hover.** Hovering a patch
  re-prepares it, and preparing it used to re-walk every polygon, rebuild a
  KD-tree over every vertex and rebuild the directed-half-edge table — on every
  mouse move. On a 16k-triangle part that is ~85 ms a frame, i.e. a ceiling of
  about 11 fps from patch preparation alone; cached it is ~0.5 ms.
  `patch_data.analyse` is the single entry point and returns everything one
  parse produces (patches, boundary loops, polygon→face-id map, weld map,
  directed owners, vertex positions) as one consistent `MeshPatches`.
  Invalidation is by **content**, not by event: `mesh_fingerprint` CRCs the
  vertex coordinates via `foreach_get` plus the element counts, which is one C
  loop and orders of magnitude cheaper than what it guards, and which cannot go
  stale the way a "someone changed the mesh" hook can. `mesh_build`'s
  committed-boundary map and `cad_display` use the same fingerprint.
  **The cached tables are shared and must be treated as read-only** —
  `generators.base.resolve_side_points` copies every point it takes out of
  `positions`, because a generator may hand its input straight through into a
  preview mesh (`resample_polyline_by_arclength` returns the very objects it was
  given when the count already matches).
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
- **Corners come from two tests that miss opposite things.** The angle test
  (`detect_corners`) is geometric and swallows anything gentle: a 30° chamfer
  reads as a smooth stretch, lands mid-side, and every generator paves across
  it. The topological test (`detect_topological_corners`) fires where the
  *neighbouring* face id changes — a real B-rep vertex, at any angle — but a
  face whose whole boundary runs against one single neighbour has no junction
  at all, however square it looks. `resolve_corners` is the arbiter.
  **The switch is per mode** (`corner_method_spans`, default `ANGLE`;
  `corner_method_ngon`, default `BOTH`) and that split is not cosmetic: a
  grid's *side count chooses the generator*, so the extra corners topology
  finds turn a bevel — whose long side borders face after face — from a Quad
  into an N-Side, i.e. from a clean grid into a midpoint fan. An n-gon only
  follows its boundary, so extra corners cost it nothing and are the one thing
  that keeps a shallow chamfer. `TOPOLOGY` falls back to the angle test when a
  boundary yields no junction — a patch with no corners is one single side,
  which every span generator would then read as unusable.
  **`boundary_neighbours` is per loop and parallel to `boundary_loops`**, so
  anything reordering the loops (`sort_loops_outer_first`) must carry the
  neighbours with them or a hole's neighbours get handed to the outer boundary.
- **Too many corners is reduced only where the ranking shows a cliff.**
  `sides.dominant_corners` runs on five or more candidates, sorts them by how
  much the boundary bends, and cuts where consecutive scores fall off by
  `CORNER_CLIFF`. A *ratio*, never an absolute angle, because that is the only
  thing separating the two cases that both produce "more than four sides": a
  real hexagon bends the same at every corner and has no cliff anywhere, while
  a curve the angle test sampled into corners sits far below the real ones and
  the drop is unmistakable. Four is tried first so a quad wins any tie, and
  cutting all the way to a *triangle* takes a much clearer cliff
  (`CORNER_CLIFF_TO_TRIANGLE`) — a rectangle with one chamfered corner is three
  90s and two 45s, and a plain 2:1 rule called it a triangle.
  **Topological corners are exempt** and take no part in the ranking. A
  junction is a fact the mesh states outright; a gentle chamfer's junction
  bends barely at all, so ranking it would drop the very thing the topology
  test exists to catch (`tests/test_corners.py` pins that).
  What *cannot* be decided is a boundary where every vertex bends the same and
  every one is flagged — a coarsely tessellated circle and a real octagon are
  the same polyline. `sides.corners_are_uniform` only **reports** it, into
  `state.corner_warning`, and the panel says to raise the threshold. Guessing
  would round a real octagon off half the time.
- **One corner is worse than none.** `resolve_corners` used to hand back a
  single corner as-is: `split_into_sides` then returns one side, no generator
  accepts one, and the face is silently unpickable with no message anywhere.
  `sides.complete_corners` tops it up to four, *anchored on the real corner* so
  the one feature the face has lands on a side boundary rather than mid-side.
  `tests/test_corner_ranking.py` pins it on a cardioid cusp.
- **Synthesised corners are for single-loop patches only.** A **ring** never
  goes through `find_generator` — it is chosen by having two loops — so a
  cornerless rim gives it no trouble, and inventing four corners on each of its
  two loops actively breaks it: `ring.ring_from_sides` allocates points *per
  side*, so two loops whose invented corners don't face each other get their
  points paired across a shear instead of straight across the band. That is
  what a chamfer running round a circle showed. Hence
  `resolve_corners(allow_synthesis=...)`, passed `num_loops == 1` by
  `_prepare_patch`; `tests/test_ring_chamfer.py` pins it.
- **A boundary with no corner still has a shape, and it is asked first.**
  Neither corner test finds anything on a single closed curve, and without
  `sides.synthesise_corners` such a face has *one* side, `find_generator` has
  nothing that accepts one (Wedge 2, Triangle 3, Quad 4, N-Side 5+),
  `_generate_for_face` returns None, and the face reads as "not selectable"
  with no message anywhere.
  But four corners spread by arc length is only right for a *circle*. A long
  strip that curves back on itself — a rounded slot, a bore wall, a ribbon
  round a feature — has its perimeter dominated by its two long sides, so the
  quarter points land in the middle of them: the "quad" fed to the Coons patch
  is half a long side plus half an end, and it comes out as a fan.
  `shape_corners` reads the boundary instead. Turn measured **over a window**
  (`SHAPE_WINDOW`, a share of the perimeter) rather than at a vertex, because a
  tessellated rounded end is dozens of individually insignificant turns and one
  real feature. Peaks must be *local maxima* at that scale — without it the
  tangency where a straight side meets a cap gets picked, half as sharp as the
  cap but well above the flat run — and separated by `SHAPE_SEPARATION`.
  However many it finds is what decides the generator: two ends make a Wedge (a
  grid running along the strip), three a Triangle, four a Quad. A boundary
  whose turn is uniform (`SHAPE_CONTRAST`) has no shape at all — a circle — and
  only that falls back to four by arc length, spread by *length* rather than
  index because a tessellated circle is not sampled uniformly.
  `tests/test_strip.py` pins the stadium, the circle and the rounded rectangle.
- **An N-Side patch is one Coons sub-patch per side, not one quad per boundary
  vertex.** A quad mesh of an odd-sided region has to put an irregular vertex
  somewhere and the middle is where every tool puts it, so the centre is not
  the problem — its *valence* was. The old fill emitted a quad per boundary
  vertex, so the pole had `sides × span` spokes (24 on a six-sided patch at
  span 4), and the only points inside the patch were that centre and one
  midpoint per boundary segment: on a curved face the fill cut the curvature
  off as a chord, which is what "it makes a fan" looks like on screen.
  Now each side is split at its midpoint, a spoke runs from there to the
  centre, and the quad between two consecutive spokes goes through the same
  `coons_patch_grid` and BVH reprojection as every other generator. The pole's
  valence becomes the *side* count, the interior becomes a real grid, and every
  interior point sits on the surface.
  Two things follow. **Each side carries an even number of segments**, because
  it is split at one of its own vertices: `generators.nside.even_span` rounds
  up, and `_prepare_patch` applies it **before** the spans are resolved so the
  panel, a match and the mesh agree on one number — a match wanting an odd
  count is then dropped by `_honours` instead of silently resampled into a
  crack. And **those midpoints are no longer emitted on the boundary**: the old
  fill subdivided every boundary segment without telling the neighbours, i.e.
  it put a T-junction on every shared edge, which is why Cube Chamfer Edges
  went from 32 open boundary edges to 6 with its deviation unchanged.
  Per-side spans and hand-placed corners are still the reference tool's
  full N-Side mode, and still not implemented.
- **A patch can have more than one boundary loop, and their order is random.**
  `compute_boundary_loops` walks a *set* of half-edges, so "loop 0" of a face
  with a hole is as likely to be the hole as the face. Anything reducing a
  patch to one loop goes through `patch_data.sort_loops_outer_first` (largest
  extent first). Two loops = a band, filled by the Ring generator; more than
  two = only the outer loop is used, and `state.num_loops` makes the panel say
  so rather than silently paving over the holes.
- **Two boundary loops is not the same thing as a band.** The Ring generator
  gives both loops the same point count, because every quad it makes runs
  straight from one to the other. On a washer, a tube wall or a fillet round a
  boss that is right. On a 200x100 plate with a 5mm hole it is a disaster:
  either the hole gets a hundred points or the outline gets twelve, and every
  quad is stretched the width of the plate. `ring.is_band` separates them on
  how *even* the gap between the loops is (`BAND_GAP_SPREAD`, sampled around
  the outer loop) and how far apart the two perimeters are
  (`BAND_PERIMETER_RATIO`) — both deliberately generous, since calling a band a
  plate costs more than the reverse. A non-band that is flat is filled as an
  n-gon instead (`generate_holed`, which is what pressing N would give it
  anyway) and `state.generator_note` says why. A committed patch is never
  rerouted: it comes back as whatever it was built as. `tests/test_band.py`.
- **The two loops of a ring must resample to the same point count.** Both go
  through `ring.around_count`, which floors the "around" span at each loop's
  side count (a side can't get zero segments). The commit path re-derives the
  per-side allocation with that same helper to register spans per loop —
  pairing corners cyclically across both loops' ids would invent a side running
  from the outer boundary to the hole.
- **A band's rungs must run straight across it, and whole-index alignment
  cannot get them there.** Every quad runs from `outer[i]` to `inner[i]`, so
  how the loops are indexed against each other *is* the shape of the quads.
  `align_rings` searches whole offsets, which is all it can do once both loops
  are resampled — leaving up to half a step of rotation. On an annulus that
  residue is not noise but a **constant shear**, the same angle on every rung:
  half a step of 64 points is 2.8°, and of 16 points 18.6°. `ring.phase_align`
  removes it by choosing where the inner loop is *sampled from* rather than
  which sample to start at — the phase is read off the geometry (each outer
  point's nearest arc-length on the inner loop implies an offset; their
  **circular** mean is the answer, circular because 0 and L are the same
  offset and a plain average across the seam lands halfway round).
  **Only on a cornerless rim, and never on a matched one.** A corner is an
  untouched source vertex welded by identity, so moving one while keeping its
  name would make a later patch reuse a vertex that is no longer there; a hole
  with real corners keeps them and its shear. A phased rim's corner id is
  emitted as `ring.NO_CORNER` instead — in place, not by shortening the list,
  because the caller zips it against `corner_source_ids` positionally and the
  outer loop's ids come first, so a short list stamps an outer id onto the
  hole's vertex the moment it is the *outer* rim that got phased. A point with
  no id welds by proximity like every other boundary point.
  **And a phased rim has to be reprojected.** Boundary rows are normally left
  exactly where the loops put them, because they are samples of the real
  boundary that a neighbour welds to. A phased one lands nowhere near a source
  vertex by construction, so on a curved rim every point sits mid-chord, a
  sagitta inside the surface — which is what took three fixture shapes from
  ~0.002% vertex deviation to 0.05%. It is not shared with anything (its
  corner id is gone), so it gets the interior's reprojection.
  `tests/test_ring_straightness.py` measures the angle between each rung and
  the radial it should lie along, and pins the *spread* as well as the worst
  case — a fix that merely averaged the error out would otherwise pass.
- **A matched rim leads the band; it is never resampled onto the other one.**
  Matching hands a side a committed neighbour's own vertices, and every other
  generator reproduces them for free — `resample_polyline_by_arclength` returns
  the points it was given when the count already matches. A ring did not. It
  always led with `loops[0]` and phase-resampled the other rim onto it, so a
  match landing on that rim was thrown away and the two rings came back half a
  step apart — with a crack all the way round, which is what the fixture's 464
  open boundary edges on Plate And Cylinder were. Which rim is `loops[0]` is
  decided by *extent* (`sort_loops_outer_first`), and on a tube the two are
  equal: the same match worked or didn't for no reason visible on screen, which
  is the "matching is inconsistent" half of the report.
  `span_settings["locked_loops"]` (filled from `sidematch.applied_loops()`)
  names the loops carrying a match; the ring **leads with a locked one**, takes
  `around` from its point count, and phases the *free* loop onto it instead.
  A locked rim is not phased for the same reason a cornered one isn't, but not
  for the same cause: its points are not a sample of a boundary at all.
  **`align_rings` re-indexes the free loop, so its corners must be looked up
  through the map it returns** — the lead loop maps to itself. Getting that
  wrong stamps a loop's corner ids onto whatever vertices sit at those
  positions, and a corner welds by identity: the neighbours then weld to points
  on the far side of the band, which measured as a 4.9% deviation and a quad
  spanning the whole part. `tests/test_ring_match.py`.
- **Which way the band faces follows the outer loop, not whichever rim leads.**
  The two loops of a patch wind *opposite* ways — an outer boundary one way, a
  hole the other — so pairing them straight across means one of them is
  reversed, and which one decides which way every quad faces. It used to be
  the hole, always, because the outer loop always led. Once a matched hole
  leads, it is the outer row that comes back reversed and **every normal of the
  band flips**: the retopology turned inside out the moment a side was matched,
  which is what Blender's face-orientation overlay showed as a red band. The
  quads are emitted the other way round when `ring.loop_area_vector` says the
  outer row ended up running against its own walk order. No count above catches
  this — the fixture had 1610 of 2139 faces turned over with its vertex count,
  face count, deviation and open-edge count all unchanged — so
  `benchmark.flipped_faces` measures it against the *nearest source polygon*
  (a CAD import is a shell whose faces already carry the right orientation, and
  there is no other definition of right), `tests/test_fixtures.py` asserts it
  is zero on every shape, and `tests/test_ring_match.py` builds the two rims
  wound opposite ways — wound the same way, the bug is invisible.
- **A ring's two rims are keyed per loop, not against each other.** Every other
  generator collides sides that share a span, because a grid has one count per
  direction. A ring's rungs run `outer[i]` → `inner[i]`, so both rims *can* be
  reproduced at once as long as they agree on the count — and whether they
  agree is exactly what `_honours` checks once the span is resolved. Hence
  `span_u@0` / `span_u@1` and `sidematch.span_base`, which is what every reader
  of a span key (the winner-to-span loop in `_prepare_patch`, `_honours`) has
  to go through. A shared key dropped the second rim's match even when it
  wanted the very same number.
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
  is get-only. Every moment that creates or frees an ID, or writes to the
  result mesh, calls `operators.push_undo`: entering an object, opening a
  re-edit, each **commit**, each **delete**, a discard that *restored* one, and
  ending the session. `undo_post`/`redo_post` run `_on_undo_redo`, which drops
  the active patch and any re-edit snapshot (undo has just replaced the mesh
  state they described) and touches **scene properties only**.
- **One undo step per committed patch, pushed by hand.** Ctrl+Z used to roll
  the *whole session* back: the only steps below a mid-session state were
  "Retop: enter <obj>" and the re-edit ones, so one press restored the file
  state from before the session and every committed patch went at once. Commit,
  delete and discard therefore push their own step — and carry `REGISTER`
  **without** `UNDO`, because Blender pushes one of its own for an
  `OPTYPE_UNDO` operator run from the UI and two identical states on the stack
  read as a Ctrl+Z that does nothing. (The modal calls them through `bpy.ops`,
  which is the path where the automatic push was missing in the first place.)
  A discard with nothing to restore pushes nothing: it changed no datablock.
  These are also the steps that own the snapshot datablock `keep_reedit_removal`
  frees, so pushing them closes a latent case of the invariant above.
  `tests/test_undo.py` pins the count per action.
- **The undo handler defers everything it may not do to the modal.**
  `_on_undo_redo` can only write scene properties, but the step also invalidated
  the preview geometry, the hover and the cached side references — so it sets
  `operators._undo_needs_reconcile`, and `_reconcile_after_undo` runs on the
  modal's next event (the 0.1 s timer, so within a frame or two). Undoing *past*
  the session's own start restores `session_active = False`, and the modal must
  then finish rather than sit there swallowing viewport events for a session the
  panel no longer shows — with `end_session(push=False)`, since pushing a step
  straight after an undo throws away the redo the user just made available.
- **Type hints everywhere, but never `from __future__ import annotations`.**
  A Blender property is declared *as an annotation* —
  `span_u: bpy.props.IntProperty(...)`, nothing after an `=` — so the thing
  Blender reads to register it is exactly the thing PEP 563 turns into a
  string. Blender 5.0 resolves those strings back (checked: all 73 properties
  still register with the future imported), but `bl_info` says 4.2, that
  behaviour belongs to the Blender being run rather than to this code, and the
  failure mode is the silent kind — the group registers *nothing*, nothing
  raises, and the panel just draws empty. Not worth relying on: Python 3.11
  evaluates `list[int]` and `X | None` unaided, and a forward reference is
  quoted individually. For the same reason **only methods are annotated inside
  a registered class** — never its class-body attributes, which is the one
  dict the registration walk reads.
  A module needing a *new* runtime import purely for a hint puts it under
  `if TYPE_CHECKING:` and quotes the annotation instead: `sides`, `patch_data`
  and `cad_display` stay free of Blender imports, and `overlay` must not widen
  what a draw handler pulls in. `tests/test_registration.py` pins all of it,
  including that every function still carries its types.
- **Never unregister an operator class from inside its own `execute()`** —
  that crashes Blender natively. `RETOP_OT_reload_addon` defers the real work
  to a `bpy.app.timers` callback.
- **The reload must never hand-list submodules.** Reloading a package re-runs
  its imports, but those resolve straight out of `sys.modules`, so a module
  missing from `_perform_reload` keeps running its *old* code next to modules
  that are new. The crash then lands somewhere unrelated — a reloaded caller
  hitting an `AttributeError` for a function the stale module doesn't have yet
  (that's how `generators/ngon.py` broke commit after being added to a
  hand-written list). Submodules are collected from `sys.modules` under the
  package name; `tests/test_reload.py` asserts nothing is missed. The version
  string can't catch this: `version.py` reloads fine either way.
- **Local View ('/') is overridden.** `RETOP_OT_local_view` is bound to
  `SLASH`/`NUMPAD_SLASH` in the addon keyconfig; it delegates the toggle to
  `view3d.localview` and then calls `mesh_build.sync_local_view`, which pulls
  the preview and each isolated source's `<Source>_Retop` into every viewport
  that is in local view. The binding cannot follow a *scene* property, so
  `local_view_include_retop` off instead makes `sync_local_view` a no-op and
  '/' behaves exactly like stock Blender. What the binding does follow is the
  session: like every `GLOBAL` key it polls false with none open, so outside a
  session '/' is not the addon's at all (see the keys section). `local_view_set` only
  flips a per-viewport flag — no ID is created, so it is safe outside an undo
  step and can be called from `enter_session_object` (a session started while
  already isolated would otherwise build its preview invisibly).
- **Creases are patch borders, never a plain angle threshold.**
  `mesh_build.apply_result_shading` shades every face smooth and marks an edge
  sharp only when its two faces carry *different* `PATCH_ID_ATTR` values and
  their normals differ by more than `sharp_edge_angle`. One patch is one CAD
  surface, so an angle-based auto-sharpen would crease a curved patch's own
  low-span interior instead. It's re-run after **every** commit, not just the
  first: sharpness is a property of the border *between* patches, so a new
  neighbour changes the shading of an edge that already existed. It only writes
  mesh attributes, so it's safe from a property callback.
- **There is no per-object wireframe opacity in Blender.** `show_wire` is drawn
  by the viewport overlay and its strength is that overlay's
  `wireframe_opacity`, so `result_wire_opacity` writes to every 3D viewport
  (`apply_wireframe_opacity`) and the panel says outright that it affects all
  wireframes there. `result_show_wire` is scoped to *emphasized* (in-session)
  result meshes: a resting one has never shown a wireframe and still doesn't.
- **Result meshes are filed under a mirror of the Inbox hierarchy.**
  `source_collection_path` walks up from the source object's collection and
  returns the path *below* the deepest collection named `Inbox` (what the
  bridge builds above it is its own scaffolding). `place_result_object`
  rebuilds that path under `Retop`. Two consequences: `iter_result_objects`
  must use `all_objects`, not `objects`, or it finds nothing; and collections
  are IDs, so this runs only from `ensure_result_object` — never a callback.
  Mirror levels usually come out as `Name.001` because the source collection
  already owns the name; `_child_collection` matches by base name so a session
  doesn't create a new level every time. An existing result mesh is re-homed
  only if it still sits at the top of `Retop`, so a manual filing is never
  stomped.
- **Raycasting looks *through* every obstacle, it never gives up at one.** The
  addon's own preview/result meshes (or the hover flickers: ray hits the
  preview → "no patch" → preview deleted → rebuilt), viewport-hidden objects
  (Local View `/`), and non-Plasticity meshes — a stand-in or a block-out in
  front used to abort the cast and make everything behind it unpickable. The
  step past a hit scales with the distance travelled: a fixed epsilon is either
  too small to clear the surface at range (the same hit repeats until the
  attempt cap) or large enough to skip past a thin recess floor on a small
  part.
- **Hover hysteresis** keeps the current patch unless a new one is clearly in
  front; coincident CAD surfaces otherwise flip-flop every mouse move.
- **`context.region` / `region_data` are unreliable inside a modal** (may be
  the N-panel's region). Use `operators.viewport_region()` and window-absolute
  mouse coords.
- **The modal swallows nothing outside the 3D view's WINDOW region.** One
  check, `point_in_region`, at the top of `_modal`, passing *every* event
  through — not a list of them. Piecemeal per-handler checks kept leaking: the
  clicks were guarded but MOUSEMOVE was not (Blender highlights buttons from
  mouse moves, so the panel went dead while the clicks were being let through),
  and the keys were not either (a digit typed into a panel field went to
  span entry, Enter committed the patch instead of confirming the field).
  `PANEL_EVENTS` records the rule so `tests/test_raycast.py` can assert it.
  `_in_viewport` does not cover the panel — it is a *region* inside the same
  VIEW_3D area. **And the WINDOW region alone does not either**: with Region
  Overlap (Blender's default) the WINDOW region spans the whole area and the
  N-panel, toolbar and headers float *on top* of it, so a point under the panel
  is genuinely inside WINDOW. `point_in_viewport` subtracts every region in
  `OVERLAY_REGION_TYPES`; testing WINDOW on its own is what kept the panel dead
  through three separate attempts at this bug. The cost, accepted: session
  keybinds need the pointer over the viewport, like Blender's own region
  keymaps.
- **A modal cursor is set on the whole window**, so it has to be dropped the
  moment the pointer leaves the 3D view (`_update_cursor`, called before the
  area check so it also fires when the pointer moves to another editor).
  Leaving the eyedropper over the N-panel reads as "the UI is not for you".
  `_apply_phase_ui` therefore only sets the cursor when the pointer isn't known
  to be outside.
- **`gpu.state.point_size_set` cannot be trusted.** The backend ignores it
  whenever program point size is enabled — the shader has to write
  `gl_PointSize` then, and the builtin `UNIFORM_COLOR` one does not — which
  came out as 1px dots that ignored their size setting entirely. Every dot is
  screen-space geometry instead (`_discs_around`, a triangle fan each), drawn
  from the POST_PIXEL handler where the region and `region_data` are at hand to
  project with. Round rather than the two triangles it started as: a square dot
  reads as a handle you can grab, and none of these are — they mark where a
  vertex is. `DOT_SEGMENTS` stays a multiple of four so a disc still measures
  exactly the size asked for; `tests/test_overlay.py` asserts that, and that
  nothing calls `point_size_set(` again.
- **The draw handlers are the one code Blender alone invokes**, so nothing
  else notices when they break. `overlay.enable()` once shipped raising
  `NameError` on a function an over-eager edit had deleted, with the whole
  suite green: no test installed the handlers or called a callback.
  `tests/test_overlay.py` now does both, across every phase and mode
  combination — a draw callback that references a name that isn't there fails
  at the call, whatever the early exits do afterwards.
- **Session state lives in the scene but the modal doesn't.** A reload or a
  crashed modal leaves `session_active` set with nothing listening;
  `operators.session_is_running()` detects it and the panel offers a reset.
- **`show_in_front` is a setting, not a consequence of the session.**
  `result_see_through` (Shift+X, `RETOP_OT_toggle_see_through`) decides whether
  the retopology draws over the rest of the scene or is occluded like any other
  object — and turning it *off* is the only way to check the result sits on the
  surface rather than floating off it, which is something you want mid-session.
  An earlier version drove this from the viewport's own X-ray on Alt+Z; taking
  over Blender's binding cost more than it gave, and the viewport's X-ray is a
  different question anyway.
- **Cosmetic offsets are Displace modifiers, never baked.** Commit reads the
  preview's *base* mesh; the result offset sets `show_render = False`.
  **And there is only one offset, not two.** `mesh_build.result_lift` is the
  measure the committed result is pushed off the CAD surface by, and the
  preview takes the same one times `PREVIEW_LIFT_RATIO` (`preview_lift`,
  with `preview_offset` as an *extra* on top). **Both go through
  `to_blender_units`**, which the extra one did not: it was added raw, so in
  millimetres the two sliders sat on scales a thousand apart and one whole unit
  of Extra Offset was a metre — the smallest usable drag threw the preview off
  the model. Two controls that add up to one distance must agree on what a unit
  is, which is also why they now share a soft range and a precision.
  The preview used to sit at 0
  by default, i.e. on the surface and *under* every committed neighbour: a
  patch hovered before the click that removes its faces came back orange
  buried in blue, and a shared boundary showed a step that exists in neither
  mesh. Strictly more, never equal — two coplanar surfaces z-fight into a
  stipple — and only by a fraction of an offset that is itself 0.1% of the
  model, so the seam still reads as flush. `refresh_result_appearance` ends
  by refreshing the preview for the same reason, and `show_in_front` on the
  preview follows `result_see_through` (Shift+X) rather than being pinned on:
  checking the retopology against the surface has to include the patch being
  built. The preview is stamped with its source object
  (`PREVIEW_SOURCE_PROP`) so the automatic offset resolves outside a session
  too.
- **Order matters in `end_session` / `exit_session_object`:** clear the state
  first, *then* call `refresh_result_appearance` — it derives every mesh's look
  from session state, so refreshing first re-applies what you're clearing.

## Session model (`RETOP_OT_session`)

**Picking an object selects it.** `enter_session_object` ends with
`select_only`, because everything Blender does "to the object" — isolate,
frame, the header, the properties editor — reads the *selection*, not this
addon's state. Without it '/' isolated whatever happened to be selected before
the session started, or nothing at all, on the one object the session is
demonstrably about. It selects the **resolved** source, so entering by way of
`<X>_Retop` does not leave the retopology selected; selection is not an ID, so
it is safe outside an undo step, and it falls inside the session's own step
anyway.

**Context follows what the user is doing.** `resolve_session_object` maps a
`<Something>_Retop` object to `Something`, so selecting the retopology and
starting a session carries on with the source rather than failing on a mesh
that has no patch data and never will; `enter_session_object` and the operator's
`invoke` both go through it, and the panel offers it as a button instead of the
useless "no Plasticity face data" warning. And **Blender leaving Object Mode
hands the viewport back**: the modal passes everything through and
`_leave_for_other_mode` drops to the `OBJECT` phase, because entering Edit Mode
on the retopology is the normal way to hand-tweak it. One exception, and it is
not optional: if the mesh being edited *is* the result mesh a re-edit took
faces from, the session stays put — `restore_reedit_removal` writes to that
mesh, and anything written while Blender owns it in edit mode is discarded on
exit, so the patch would be gone for good.

`OBJECT` → click a Plasticity object → `PATCH` → click a surface → `ADJUST`
→ commit → back to `PATCH`. Esc: `ADJUST`→`PATCH`, `PATCH`→`OBJECT`,
`OBJECT`→ end. Commit clearing `active_face_id` is the signal the modal
watches to return to picking. Clicking a patch that's already committed enters
`ADJUST` in re-edit mode (`state.editing_committed`): same keybinds, but commit
replaces the existing patch.

**Starting resolution.** `state.resolution` (Very Low … Extreme, powers of two)
scales what `generator.default_spans` computed, via
`state.scale_default_spans`. Every factor carries a `RESOLUTION_TRIM` of 0.75
on top of its power of two: what the generators compute from edge lengths reads
about a quarter too dense in practice, and each preset was inheriting that.
The ratios between presets are unchanged — High is still exactly twice Mid. Order matters and is asserted: the preset is
applied **first**, then propagation from a committed neighbour, then the spans
a patch was committed with — scaling either of those would break the welds they
exist to make, and would re-shape finished work on re-edit. Never below 1 span.
The n-gon has no span to scale; its resolution is `ngon_angle`, which Ctrl+wheel
drives directly (inverted, and multiplicatively — a 2° step is nothing at 90°
and everything at 4°).

Keybinds in `ADJUST`: Ctrl+wheel = span (or N-gon detail), `0-9`/Backspace = type a span,
Tab = U/V (quad/wedge), `N` = n-gon mode, `M` = match a neighbour,
`X` = delete the patch (re-edit only), right-click or Enter = commit,
Esc = clear typing then discard. Plain wheel stays zoom.

Ctrl+Z is deliberately *not* one of them: the modal passes it through to
Blender, and the session's own undo steps (one per committed patch) are what
make that mean "take the last patch back" instead of "roll the session back".

**Tab is per phase, and every phase of a session answers it.**
In `PATCH` it opens the hand-edit round trip below; in `OBJECT` it opens the
*selected* object's retopology (see `tweak._session_source`) — it used to fall
through to Blender there, which put the CAD **source** into Edit Mode, the one
mesh nothing here ever wants edited by hand. In `ADJUST` it is U/V — and it
is still swallowed on a single-span generator, because a patch is open there
and letting Blender toggle Edit Mode would take the session out from under it,
but it now *reports* that instead of doing nothing. A key that does nothing and
says nothing reads as a captured key, which is exactly how the unconditional
version of that line got reported as "the addon eats Tab".

**The session refuses to start outside Object Mode** (`RETOP_OT_session.poll`).
It used to run the whole entry path from Edit Mode — create the result mesh,
create the preview object, push an undo step — and only *then* have the modal
hand the viewport straight back, since it does nothing in another mode. Two
datablocks created from inside an edit session, for a session that never
opened: that is the shape of the Ctrl+Z crash the undo invariant exists to
prevent. The panel says which mode to leave rather than offering a dead button.

**Deleting a patch** (`X`, `RETOP_OT_delete_patch`) falls straight out of the
re-edit model: picking a committed patch already took its faces out and
snapshotted the result mesh, so deleting is `keep_reedit_removal` — dropping
that snapshot instead of restoring it — with nothing committed in its place.
Hence the poll on `editing_committed`: there is nothing to delete on a patch
that was never committed. The removal used `context='FACES'`, so the shared
boundary vertices a neighbour still uses survive and its welds hold.
`forget_patch_settings` clears the patch's own entry, but the **span registry
is deliberately left alone** — its entries are keyed by corner pair, i.e. they
describe a shared boundary whose other side is still committed, and dropping
them would break that neighbour's propagation to describe a patch that no
longer exists. Shading is re-applied because a crease belongs to the border
*between* patches, so losing one changes the edges of the ones around it.

**Matching a neighbour.** The patch's sides are drawn in the viewport
throughout `ADJUST` — green where a committed neighbour can be matched, grey
where there is nothing to match, orange under the cursor. `match_mode` is on by
default and `M` toggles the highlight; it is a *preference*, so it survives
between patches and sessions (`_clear_match_state` resets the pins and the
hover, never the mode). A left click has no other job while adjusting a patch,
so it takes the side under the cursor, and **commits when it is pointing at
none** — same as right-click and Enter. The picker deliberately does not take
`Esc`: it is always on, and swallowing `Esc` would leave no way to discard.

Hit-testing is in *screen* space (`nearest_side_to_cursor`): the sides are
polylines lying exactly on the surface, so a raycast hits the surface beside
them as often as the line.

**A match copies vertices, not a count.** Copying the neighbour's segment count
is not enough to weld to it and the difference is invisible until you look at
the vertices: the two patches only coincide if they also divide the *same*
polyline the same way, and they often don't — a neighbour committed as an n-gon
put its points where the boundary curves, not at even spacing, so a grid
resampling evenly to the same count lands between them every time.
`mesh_build.committed_boundary_points` therefore gathers the neighbours' own
committed vertices — once per patch, not once per side, since it walks the
whole result mesh and a patch with eight sides was walking it eight times per
hover — and `match_side_to_points` picks out the ones lying along a side. It
returns `None` unless they cover both endpoints of the side (a neighbour
touching half of it has nothing to align the rest against — matching a count
there *is* the half-cell offset).

**How far it reaches is two answers, not one.** `side_match_tolerance` is float
slack by default: both patches usually resample the same polyline, so the real
distance is ~0, and that strict answer is what the *automatic* matching uses —
it fires without being asked, so it must never reach for something that merely
happens to be nearby. `margin=True` widens it by `match_margin`, and that
is the picker's answer: pointing at a side says which neighbour you mean, so it
can reach one that has drifted — a coarse neighbour whose chords sag off a
curved boundary, two CAD edges tessellated slightly differently.
`SideReference` carries both, and `apply_side_matches` takes the strict one for
automatic matching and the generous one only for sides you pinned.

Both are a share of `reference_length`, which `build_side_references` sets to
the **patch's longest side**, not the side being matched. A neighbour's drift
is an absolute distance; scaling by the side made a short side's reach vanish,
so a stub between two retopped faces refused while the long side beside it
matched without trouble. And "found one point" is reported as its own reason
rather than "no neighbour": a side shorter than the neighbour's vertex spacing
genuinely has nothing to follow, and saying which of the two it is matters.

**A closed side has one endpoint, not two.** A cornerless loop — a ring's rims,
a disc's boundary — comes back from `resolve_side_points` as `loop + [loop[0]]`,
so requiring a committed vertex "at both ends" asks for two in the same place
and always refuses: a bore's rim read as unmatchable while visibly bordering
finished retopology. `_close_matched_ring` handles that case instead.

Coverage becomes the largest *gap* between consecutive matched points, and it
has to be both a large share of the loop **and** far bigger than the others
(`CLOSED_SIDE_GAP_RATIO`): a merely coarse neighbour has every gap the same
size — a square inscribed in a circle already leaves 22% between points — while
one covering half the rim leaves one huge gap among small ones. Testing the
share alone refused coarse but perfectly matchable neighbours.

A neighbour vertex on the side's *start* is deliberately not required. That
start is arbitrary — a cornerless loop begins wherever the half-edge walk
happened to — so it is not a B-rep vertex and nothing else in the model agrees
on it; a disc committed as a Quad puts its points at arc-length resamples from
its own synthesised corners, which land nowhere near. The match is rotated to
lead with whichever point is nearest, and `apply_side_matches` then **drops
that side's corner id**: a corner welds by *identity*, so leaving the name on a
point that has moved would make a later patch reuse a vertex somewhere else, or
drag this one onto it. It welds by proximity instead, like every other boundary
point.

**How far a match reaches off a side is not how close two vertices have to be
to be the same one.** Both were `tolerance`, and on a real part the two numbers
cross: the picker's margin is a share of the *patch's longest side*, which on a
ring is a whole rim, so deduping at that distance merged the neighbour's own
consecutive vertices — 61 points came back as 31, and the side was asked to
reproduce half the count it should have. `match_side_to_points` takes `merge`
separately, and every caller passes the strict tolerance for it: two copies of
one welded vertex are coincident, two different ones are a segment apart.

**And a neighbour's second row is not the edge under the cursor.** A committed
patch is a grid, so there is another row of its vertices one cell behind the
one it shares; on a narrow band that row is well inside a pinned side's reach,
and taking both rows is what "the match spreads over the surface instead of
following the edge I pointed at" looks like. Two rules keep it out.
`rivals` — the patch's other sides — drops a candidate that is nearer to one of
them than to this side, which is what settles a band's two rims. And
`_nearest_row` cuts the rest by a **gap**: within one row the distances vary
smoothly (that variation *is* the drift the margin exists to reach), so a step
larger than everything the row has varied by so far is a different row. No
constant says how far a neighbour may drift — only that a jump is not drift.

**A side may only match the faces it actually borders.** This used to be pure
proximity — one pool of every committed vertex in the result mesh, keep
whatever falls within the tolerance — and proximity cannot tell "the patch
across this edge" from "a patch that happens to run close by". A face stacked a
fraction above another, a thin wall, two sheets meeting at a shallow angle: all
of them put committed vertices well inside a side's reach without touching it,
and the side came back with a run of vertices tracing a loop through its
neighbourhood instead of the edge it shares. The mesh already says which face
is across each boundary segment, so `patchprep.side_neighbours` returns the
whole list per side (`[0]` is the majority, which is only what the picker
*names*), `mesh_build.committed_boundary_map` groups the result mesh by owning
patch, and `sidematch._match_pool` intersects the two.

A side is still matched against **every** face it borders, not just the
majority one: a side runs against two committed patches whenever the boundary
between them falls mid-side, which is the normal case when the angle test
didn't put a corner there. Untracked retopology (`NO_PATCH`, predating patch
ids) belongs to no named face and so stays in every pool. When a side's
neighbours are named but none is committed, the pool is **empty** rather than
falling back to the rest of the mesh, and the reason names the patch it is
waiting for. `tests/test_match_specificity.py` builds the stacked-sheet case
and asserts both that it is refused and that plain proximity would have taken
it — otherwise the test proves nothing.

**Exclude the patch being generated, not the "active" one.** Picking a
committed patch generates it *before* recording it as active, so reading
`state.active_face_id` in `build_side_references` left the patch's own
committed geometry in its own pool and it matched itself: a re-edit came back
with whatever spans reproduced what was already there instead of the ones it
was committed with. `build_side_references` takes the face id explicitly.

**A grid cannot honour two counts in one direction.** Two sides driving the
same span used to both get substituted, with the second silently winning the
count — leaving the loser's points resampled to a number that was not theirs,
i.e. the exact crack matching exists to close. `sidematch.span_key_for` names
the span a side drives (an n-gon gets a key per side and a ring one per *loop*,
so neither collides with itself), `_winning_matches` keeps one per key — a pin
beats an automatic match, then the denser one wins — and only the winner is
substituted. The rest keep the boundary the CAD drew, and
`state.match_conflicts` tells the panel how many were outvoted. Every reader of
a key goes through `sidematch.span_base`, since a ring's is qualified by its
loop.

**An automatic match seeds a span; a pin decides it.** Spans are resolved
*before* any side is rewritten, and `sidematch._honours` then drops any match
the resolved span can no longer reproduce. Without that split, scrolling the
span on a side bordering a committed neighbour did nothing at all — the match
put its own count straight back every regeneration and the control looked
broken. Changing the count away from the neighbour's is how you say "don't weld
here"; a pin is immune, because it was asked for.

**A click on a matched side turns the match off.** It used to release the
*pin*, which with automatic matching on — the default — is invisible: the
automatic match put itself straight back on the next regeneration and the side
stayed green, so the click read as broken. `PIN_EXCLUDED` records "leave this
side alone" and `_match_candidates` honours it over the automatic pass, making
the gesture a plain two-state toggle. Clicking an excluded side matches it
again.

**Three kinds of pin.** `PIN_NEIGHBOUR` follows the committed patch across the
side. `PIN_SOURCE` (Ctrl+click) follows the side's **own CAD tessellation**,
thinned by curvature with the same rule n-gon mode uses — no neighbour needed,
so it works on the first patch of a model and on any side facing nothing yet.
`PIN_EXCLUDED` is the third, above. `state.side_overrides` stores the *kind*,
not the count: the count is recomputed from live geometry every regeneration,
so a stored copy could only disagree.

Every refusal carries a `reason`, surfaced in the click warning and the panel,
and the viewport **brightens a side's own colour on hover** rather than
replacing it — a single hover colour hid the one thing worth knowing before
clicking, which is whether the side can be matched at all.

**Green means a side is being matched, not that it could be.** Those are
different answers and the picker used to give only the second: a side that had
lost a span collision, or whose span the user had typed since, drew exactly the
same green as one the preview was welding to. `SideReference.applied` (set by
`apply_side_matches`, which is the only place that knows) and `.outvoted` carry
the difference; `overlay._side_appearance` maps it — green for a match being
reproduced, amber for one following its own CAD edge, grey for everything else,
whether it *could* be matched or not. What tells those last two apart is the
**tooltip by the cursor**: `sidematch.status_of` returns the one wording the
overlay and the panel both use ("Selected / Not selected for surface matching",
plus why), so the two can't disagree about the side under the pointer. The
tooltip needs the mouse and a draw handler has no event to read it from, so the
modal leaves it in `overlay.cursor_window` — the same arrangement as
`hover_committed`, cleared the moment the pointer leaves the viewport.

What makes those points cheap to use is `resample_polyline_by_arclength`:
asked for exactly as many points as it was given, it returns them untouched. So
`apply_side_matches` substitutes them for the side's polyline in `prepared`,
and every generator — Quad, Triangle, Wedge, N-Side, Ring, N-gon, **none of
them modified** — reproduces them exactly, as long as it puts `len - 1`
segments along that side. That count is what the pin stores
(`state.side_overrides`, JSON, cleared by `set_active_patch` because a pin
names a side *by index* on the patch it was picked on).

`auto_match_neighbours` (default on) applies the same substitution
automatically to **every** generator, not just n-gons: a grid that copies only
the segment count still lands between the neighbour's vertices whenever the
neighbour didn't space them evenly. Automatic matching takes only the strict
answer; the margin is for sides you pointed at. The commit re-runs the
substitution before registering, or the registry would advertise a curvature
count on a side that was actually matched.

The overlay draws **which vertices a match would take** — dots on the hovered
side's candidates and on every pinned side's, green from a neighbour and amber
from the CAD edge. Knowing a side *can* be matched is only half of it; a match
going to the wrong neighbour or stopping short is invisible from a coloured
line lying on the boundary. `SideReference` carries world-space copies for
exactly that, computed at generation time — a draw handler has no business
transforming points on every redraw.

`sidematch._active_sides` is a module global holding Vectors describing a
preview: rebuilt on every generation, dropped on every session exit, and empty
after a reload — the overlay must cope with that.

**N-gon mode** replaces the span grid with one face following the boundary,
for flat faces where a grid is only wasted geometry. A patch committed as an
n-gon reopens as one whatever the current mode — same rule as its spans.
Toggling the mode goes through the property's update callback, and
`regenerate_active_preview` writes `generator_name`/`num_sides`/`num_loops`
back so the panel and overlay follow.

`operators.ngon_blocker` decides whether a patch may take one at all, and
writes `ngon_available`/`ngon_unavailable_reason` for the panel and the `N`
key to explain themselves instead of doing nothing. Two blockers:

- **Not flat.** `patch_is_planar` compares every polygon of the patch against
  their average normal (`ngon_planar_tolerance`, 5° default). One face across
  a bevel or a fillet is a flat lid over it — the shape is simply gone. This
  runs on every hover, so it uses polygon normals only: no boundary walk, no
  KD-tree.
- **More than one hole.** One hole is fine: `generate_holed` bridges it to the
  outer boundary with two edges and emits **two** n-gons. That is forced —
  a Blender n-gon carries a single loop, and the one-face "keyhole" alternative
  needs the bridge vertices duplicated, which the boundary weld then merges
  back and destroys the face. Two faces need no duplicates and stay manifold.
  The hole loop is wound opposite to the outer one (both are half-edges of the
  same patch), which is why both arcs are walked *forward*. Corner indices are
  emitted outer-loop-first to match `PreparedPatch.corner_source_ids`, and the
  commit registers spans per loop like a ring does.

The mode gate and the corner method interact: the method depends on which
generator will run, so `_generate_for_face` decides the mode *first* and
re-prepares the patch if a blocker only shows up once the loop count is known.

**Its boundary is *selected*, never resampled** (`ngon.side_points`): it walks
the source boundary accumulating turn and keeps a vertex every `ngon_angle`
degrees. This is not a cosmetic choice. `sides.py` only calls a vertex a corner
past `corner_angle_threshold` (45° of deviation), so a chamfer — typically
20-40° — is *not* a corner and sits in the middle of a side; arc-length
resampling, which is what this did first, put points wherever the even spacing
fell and cut a straight chord across it. Accumulating turn keeps the chamfer's
own vertex, and every kept point is a genuine CAD boundary vertex.

The cost: a curvature-selected n-gon side does not line up point-for-point with
a *grid* neighbour along a shared edge, so only their shared corners weld. Side
matching buys that back exactly — a matched side is handed the neighbour's own
vertices — and `ngon_match_neighbours` does it without being asked.

## Keys (`keymap.py`, `prefs.py`)

The session's keys were `event.type == 'X'` comparisons inside `_modal`. That
leaves nothing to remap and nothing in Blender's keymap editor to find either,
because a modal operator reads raw events and never goes near a keymap. The
first attempt at fixing that was a table plus a capture modal plus a panel to
edit it in — a second, worse keymap editor next to the real one.

**They are real `KeyMapItem`s on real operators now, and Blender owns all of
it**: the editing UI, the conflict display, the per-item restore, the
persistence in the user's preferences. `keymap.py` only *declares* what to
register; `prefs.py` draws the rows with `rna_keymap_ui.draw_kmi` on the
addon's preferences page, and the panel's Keybinds tab is a button that opens
it (`RETOP_OT_open_keymap_prefs`) plus a read-only list of what isn't
remappable. The same items show up under Preferences > Keymap > Add-ons.

**Who dispatches them differs by scope, and that split is not belt-and-braces.**
`GLOBAL` actions (isolate, mirror, x-ray) are dispatched by Blender like any
keymap item, because they must work with no session. `SESSION` actions are
dispatched by the **modal**, which resolves the event against the live items
(`keymap.session_action_for`) and runs the operator itself.

Letting them fall through to the keymap does not work: an item in the `3D View`
keymap does not reliably beat one in a *mode* keymap, and the session's keys
collide with those constantly — `X` is `object.delete` in Object Mode, `Tab` is
`object.editmode_toggle` in Object Non-modal. Registering each action in
whichever keymap owns its competitor is unmaintainable and still loses to the
next addon that claims the key; MACHIN3 puts its own `Alt+X` in `Mesh` rather
than `3D View` for exactly this reason. The modal sits above every keymap, so
dispatching there always wins, and the items stay real — Blender's rows edit
them, the keymap editor lists them, the preferences save them.

The failure that forced this was not cosmetic: with `X` falling through,
pressing it on a patch that turned out not to be committed reached
`object.delete` and took the CAD object with it. Hence `_MUST_CONSUME`: a
session action whose poll *fails* is still consumed for the two keys Blender
claims (`delete_patch`, `hand_edit`) and says why; everything else falls
through on purpose, so `N` outside `ADJUST` still opens the sidebar.

**No key is spelled out in `_modal`.** `tests/test_keymap.py` greps its source
for the event types it must not test — a hardcoded `event.type == 'X'` is what
made them unremappable in the first place, and it comes back one line at a
time.

**The `poll` is where the phase logic lives.** Every action is offered whether
a session is running or not, so each operator polls `session_active` and its
phases. Three actions share `TAB` — U/V in `ADJUST`, hand-edit in `PATCH` and
`OBJECT`, back-from-hand-edit in `TWEAK` — with mutually exclusive polls, so
the first whose poll passes is the one that runs. That is the "one key, two
meanings" design expressed as data instead of spelled out. With no session, all
three fail and `Tab` belongs to Blender again.

**And the modal resolves a shared key the way Blender does: first poll that
passes, not first match.** `keymap.session_actions_for` returns *every* action
bound to the event and `_dispatch_bound` walks them. Returning only the first
match resolved every `Tab` to U/V, whose poll fails outside `ADJUST`; the key
then fell through to the keymap and was answered by whichever item happened to
be registered first. It worked — but by an ordering nothing states, it made
`_modal_tweak`'s own `end_tweak` branch dead code, and in the `OBJECT` phase it
reached Blender's `object.editmode_toggle`. When none of the candidates polls,
a key Blender claims is still consumed (`_MUST_CONSUME`) and the refusal
reported, so `Tab` can never leak mid-session.

**No key of the addon's is live outside a session.** The session's keys never
were — every one of those operators polls `session_active` — but the three
`GLOBAL` ones (`/`, `Alt+X`, `Shift+X`) were claimed from the moment the addon
was installed, and all three are keys something else wants: Hard Ops binds
`Alt+X`, and `/` is Blender's own isolate. An addon that has to be *disabled*
to give a key back is not self-contained, so `operators._global_keys_live`
gates those polls on a session being open, and **a failing poll is what hands
the event on** — Blender skips the item and the next handler down (the other
addon, or Blender's own binding) runs it, unchanged.
`keymap.global_keys_outside_session`, an addon *preference* (per user, not per
file), is the way back for anyone who wants the isolate and the mirror between
sessions.
Panel buttons are unaffected: the mirror's UI goes through
`retop.mirror_axis` / `retop.apply_mirror`, which are bound to nothing and
still poll on having a result mesh. `tests/test_keymap.py` pins that every
`GLOBAL` action is gated — by comparing against the scope in `ACTIONS`, so a
new one added there fails the test until it is considered.

**Two things stay outside the keymap**: the **digits and Backspace** (numeric
entry, not a shortcut — they must stay instantaneous and only make sense as a
block), and the mirror's **`Alt+X` then `X`/`Y`/`Z`**, a key *sequence*, which
Blender's keymap cannot express.

**The left click is split, not fixed.** Taking the side under the cursor is
`retop.pin_side`, two normal bindings differing by a `source` property (plain
click follows the committed neighbour, `Ctrl` the CAD edge). What stays in
`_modal_match` is only the *fallback* — nothing under the cursor, so commit —
which genuinely depends on the hover; the picker returns `PASS_THROUGH` the
moment a side is under the cursor and the binding takes it from there. Ctrl+
click was fixed for a while purely because it had been lumped in with that
fallback, which it never shared.

**`typed_span` moved to the scene.** The keys that clear it — U/V, N-gon, the
span wheel — are operators now, and an operator has no way to reach the running
modal's attributes. The overlay echoes the same property.

**`RETOP_OT_back` asks for the session to end; it does not end it.** The timer,
the modal cursor and the draw handlers belong to the modal instance, so the
operator clears `session_active` and the modal acts on it at the top of
`_modal`. Same shape as the undo reconciliation.

**The modal catches up with phases it did not cause.** `retop.back`,
`retop.tweak_mesh` and the panel's buttons all move the phase without telling
the instance, leaving a stale hover and a cursor describing the phase before.
One `session_phase != self._last_phase` check covers every route in — and it
clears the hover only when the new phase is `PATCH` or `OBJECT`, because
entering `ADJUST` is the modal's own click handler and the hover it just built
*is* the preview.

**The overlay reads the live items** (`keymap.describe`), never the
declaration: a hint that says `E` when the key is now `Ctrl+E` is worse than no
hint, since it is the one place a user checks before deciding the feature is
broken. It falls back to the declared default when nothing is registered, which
is the `--background` case. `items_for` drops wrappers Blender has freed under
it — a draw handler is the worst place to find that out. `commit` is the one
action whose hint lists *all* its bindings; the right-click is the
Plasticity-style affordance people arrive expecting.

**The registry keys on the action, not the operator.** Two items share
`retop.nudge_span` and differ only by a `delta` property, so matching them back
by idname would pair them up wrong.

**A reload does not lose settings, and nothing here saves them.** Blender keeps
a PropertyGroup's values as ID properties on the scene, keyed by name, so
`del bpy.types.Scene.plasticity_retop` and re-declaring it re-attach to the
same stored data. `tests/test_reload.py` asserts it rather than trusting it: it
is a fact about Blender's storage, not about this code. The same test pins that
a reload neither stacks the app handlers (removed *by name*, since a reload
leaves a new function object) nor orphans keymap items (the unregister happens
*before* the modules reload, or the session's keys would fire twice per press).

## Symmetry (`mesh_build`, `RETOP_OT_mirror`)

`Alt+X` then `X`/`Y`/`Z` mirrors the retopology — the Hard Ops reflex, which is
why the retopo x-ray moved to `Shift+X`. **Not `Alt+Z`**: that is Blender's own
viewport X-ray, and the note under `result_see_through` about not taking it
over still stands.

**It is a Mirror modifier on the result object, never baked geometry**, and
that is not merely non-destructiveness. Every piece of bookkeeping here reads
the result mesh's *base* data — commit and re-edit through `PATCH_ID_ATTR`,
matching through `committed_boundary_map`, `apply_result_shading`,
`adopt_untracked_faces` — so a modifier is invisible to all of it by
construction. Baked mirror faces would carry the same patch ids as the
originals, and `remove_patch_from_result` deletes *every* face carrying the id
being re-edited: re-editing one patch would take both halves out and rebuild
one, tearing a hole in the mirrored side that nothing would put back.

**The plane is the source object's origin** (`mod.mirror_object = source_obj`),
not the result object's. Plasticity drops every import at the world origin so
the two coincide today, but that is a fact about the current bridge, and the
source object is what "the object" means to the user.

**Which axes are on lives on the modifier, not in scene state.** They belong to
one object, and two objects retopped in the same file have no reason to agree.
`mirror_axes` reads them back for the panel; only *how* the mirror behaves
(`mirror_clip`, `mirror_merge_distance`) is a scene preference. A modifier is
not an ID, so all of this is safe from a property callback and outside an undo
step — the same reason `_apply_offset_modifier` is.

**Applying it has to stamp `NO_PATCH` on the copies**, which is the whole
reason `bake_mirror` exists instead of a note pointing at the modifier
dropdown. Untracked is the right resting state: unclaimed faces are never
deleted, and `adopt_untracked_faces` hands each copy to the Plasticity face it
sits on the next time the object is entered — which, on the symmetric part this
was used for, is the real face on the other side. The copies are told from the
originals by **face centre**, not by index: the originals come through the
apply untouched so their centres match exactly, while assuming Blender appends
the mirrored half is an ordering detail that could change under a silent
corruption.

That hand-off is **only correct because the part is symmetric**, and the
degenerate case is worth naming: mirror a patch out over empty space, apply it,
and adoption has only the *original* patch to offer the copies — they join it,
and re-editing it then takes them with it. That is mirroring something that
isn't symmetric, which is a user error the adoption rule degrades on rather
than a case to defend against; `tests/test_mirror.py` builds the symmetric part
deliberately and says why.

**A modal on top of the session modal is how the axis prompt avoids a
collision.** `X` in `ADJUST` deletes a patch, and a modal handler sits *above*
the keymap `Alt+X` is bound in — so the session modal now requires a bare `X`
(no alt/shift/ctrl), and once `RETOP_OT_mirror` is armed it sees the axis keys
first anyway. The prompt cancels on anything that isn't an axis: an armed
prompt nobody can get out of is worse than one that gives up easily. Modifier
*releases* are ignored, or letting go of Alt would cancel it before it started.

## Hand-editing the result (`tweak.py`)

Sometimes the generators get a boundary wrong — a side whose neighbour could
not be matched, two boundaries that ended up one vertex apart, a merge that did
not take — and the fix is a few vertex moves and one extra edge. Every tool for
that already exists in Blender, and **all of them are Edit Mode operators**:
merge by distance, vertex snapping, knife, loop cut, connect-vertex-path. There
is no version of this that stays in Object Mode; an object-mode
reimplementation would be a worse knife and a worse snap, written twice.

So `Tab` from the `PATCH` phase hands the viewport over. `enter_tweak` selects
`<Source>_Retop`, makes it active, snapshots the tool settings and replaces
them with what manual retopology wants, and enters Edit Mode; the phase becomes
`TWEAK` and `_modal_tweak` passes **everything** through except the `Tab` that
ends the trip. Blender's own keys are the feature: `K` knife, `Ctrl+R` loop
cut, `J` connect, `G` move, `Ctrl+Tab` select mode. The addon owns only the two
ends of the trip, and each is there for a reason:

- **The setup.** Vertex snapping with `use_snap_self` **on** — the whole point
  is dragging a vertex onto its twin in the *same* mesh, which Blender's
  default (other objects only) makes impossible — plus auto-merge at
  `tweak_merge_distance`, so closing a seam is a drag rather than a drag
  followed by a Merge by Distance that gets forgotten once and leaves a crack
  nobody sees until export. `tweak_snap_surface` adds `FACE_NEAREST` so a
  dragged vertex stays on the CAD surface. Settings are read on the way **in**,
  so changing one mid-edit does nothing until the next trip; the panel says so.
- **The repair** (`mesh_build.repair_manual_edits`), because Blender knows
  nothing about this addon's attributes and the two it gets wrong are the two
  read back later. A knife cut leaves faces carrying `NO_PATCH` — the patch
  then reads as partly "never retopped" and a re-edit stacks a second grid on
  it — and vertices that *inherited* a neighbour's `retop_source_vid`, i.e.
  claim to be a CAD corner they are nowhere near, which the next commit would
  weld onto that corner by identity. Faces go back through
  `adopt_untracked_faces`; ids go through `clear_stray_source_ids`.

**A stray source id is decided three ways, and "it moved" is the weakest.**
Out of range for the source mesh is certain (an interpolated int between two
real ids is not an index). Two vertices naming the same source vertex is
certain too — one CAD corner is one result vertex — and the nearer one keeps
it. Distance alone only fires past `STRAY_SOURCE_ID_RATIO` of the model's
bounding box, deliberately generous: **nudging a corner by hand is what this
mode is for**, and stripping its identity for having moved a hair would undo
the fix on the next commit that touched it. Clearing is always the safe
direction — a vertex with no id welds by proximity like every other boundary
point, which is what a hand-placed vertex should do.

**The tool settings are the user's, and every exit path restores them**:
`restore_tool_settings` is called by a failed `enter_tweak`, by `exit_tweak`,
and by `end_session`. The snapshot lives on a scene property rather than a
module global so an addon reload mid-edit doesn't lose it. It is JSON, so sets
(`snap_elements`) and `bpy_prop_array`s (`mesh_select_mode`) round trip through
`_jsonable`; every key is read and written through `getattr`/`setattr`, since
`snap_elements` and friends have been renamed and split more than once across
Blender versions and a missing name must be skipped symmetrically in both
directions.

**From `PATCH` and from `OBJECT`, never from `ADJUST`, and that last one is
not a convenience.** A re-edit has the patch's faces *out* of the result mesh
with only a snapshot datablock to put them back, and anything written to a mesh
Blender holds in Edit Mode is discarded on exit — the patch would be gone for
good. That is the same rule `_leave_for_other_mode` already enforces for the
reverse direction, and `can_tweak` is where the key and the panel button both
read it, so they refuse with the same reason instead of one of them silently
doing nothing.

**In `OBJECT` the session holds no object, so the selection names one.**
`_session_source` resolves it the way `operators.resolve_session_object` does
(pointing at `<X>_Retop` means X), active object first. Two things then have to
survive the trip, because neither is derivable on the way back: which source it
was about — `repair_manual_edits`, the whole reason `Tab` is ours rather than
Blender's, needs it — and which phase it started from, since landing in `PATCH`
would claim the session had entered an object it never did
(`tweak_source_object` / `tweak_return_phase`).

**The trip has to be closed even when Tab didn't close it.** Leaving Edit Mode
by the mode dropdown, by a script or by an undo fires no event of its own, so
the `TWEAK` dispatch sits *before* the `TIMER` early-out in `_modal` and
`_modal_tweak` checks `context.mode` first: the repair runs once per trip
whichever way the trip ended. `Ctrl+Tab` is deliberately left to Blender (the
select-mode pie, used constantly while retopping), and the modal cursor is
*restored* rather than set in this phase — a cursor pinned on the window would
sit on top of the knife's own.

## Seeing the CAD structure (`cad_display.py`)

The bridge sends a triangle soup, so a Plasticity import reads as one
undifferentiated field of triangles even though the mesh records which triangle
belongs to which CAD face. Two overlays put that structure back; they make very
different kinds of claim and the distinction matters.

**Plasticity edges are exact.** A boundary half-edge `(a, b)` of one patch is
matched by `(b, a)` of the patch across it, so a B-rep edge is the maximal run
of boundary segments whose neighbouring face id does not change, and a B-rep
vertex is where it does — the same signal the topological corner test runs on.
`_edge_runs` splits a loop at those junctions. Each shared edge is walked by
*both* its faces, and the lower face id emits it: settled by comparison rather
than by remembering what has been seen, since a set of welded vertex indices is
a much larger thing to carry around than one `<`. An outer boundary (no face
across it) always emits. On an **open sheet** a whole free boundary is one run,
because nothing distinguishes its segments — that is a real limitation, and it
costs nothing visually since everything is drawn as segments anyway.

**Surface flow is derived, and the panel says so.** Plasticity's isoparametric
curves come from each face's NURBS parameterisation and *none of it crosses the
bridge* — the protocol carries no surface parameters at all. What is drawn
instead is the grid each face would be retopologized into: the same corner
split, the same generators, at a low span, reprojected through one shared BVH.
On a fillet or a swept face that lands very close to the true isoparms, because
both answer the same question about the same boundary. It is also the more
useful of the two here, being the topology the retopology would actually get.
A non-band annulus draws its outer loop only, for the same reason
`_generate_for_face` refuses to ring it.

Everything is cached on the same fingerprint as `patch_data.analyse`, per
`(product, face id)`. A draw handler runs on every redraw and may not walk a
mesh. Both displays are drawn as **one LINES batch each**, since a CAD part has
hundreds of edges and a draw call apiece is what turns an overlay into a
stutter.

**Whether they draw through the model is `cad_display_xray`, on by default.**
Through is what makes a whole part's layout readable at a glance; off is what
makes a *curved or enclosed* one readable, because the far side stops showing
through the near side. The reason it was `depth_test_set('NONE')`
unconditionally still holds, though: the lines lie exactly *on* the surface
they describe, so depth-testing them against it is a coin flip per pixel and
they come out as a stipple. `_towards_viewer` is the answer — every point is
nudged along the view axis by `DEPTH_NUDGE` of its distance to the viewpoint,
proportional for the same reason the raycast's step past a hit is (a fixed
epsilon is either too small to clear the surface at range or big enough to lift
a line off a small part visibly). One view direction for the whole batch, not a
per-point eye vector: at that magnitude the difference at the edge of frame is
far below a pixel, and a draw handler has no business normalising a vector per
point. It reads the region's own matrix, so the handler still imports nothing
it didn't already.

The **B-rep vertex dots stay on top regardless**: they are screen-space quads
(POST_PIXEL), so there is no depth to test them against. Said in the property
description rather than left to be noticed.

`E` toggles the edges, `Ctrl+E` the flow, in every session phase: the structure
is read while *choosing* a surface as much as while adjusting one. Both are
remappable — see `keymap.py`.

## Status

Implemented: Quad, Triangle, Wedge (2 sides), N-Side (5+, one Coons
sub-patch per side around a centre), Ring (two boundary loops: a face with a hole, or a tube-like
face — this is the Cylinder case), N-gon mode for flat faces, topological
corner detection, span propagation,
per-patch UVs, boundary welding, smooth shading with sharp patch borders,
Inbox collection mirroring, viewport session with overlay, re-selecting a
committed patch to change its spans (replaces it in place).

Also implemented: matching a committed neighbour along a shared side, by
pointing at it (`M`) or automatically, for every generator and confined to the
faces the side actually borders; pinning a side to its own CAD tessellation
(`Ctrl`+click); corner ranking, which keeps a quad a quad when the angle test
also flags a tessellated curve; the Plasticity edge / B-rep vertex / surface
flow overlay (`E`, `Ctrl`+`E`); the hand-edit round trip into Blender's Edit
Mode (`Tab` from `PATCH`), set up for retopology and repaired on the way back;
symmetry as a Mirror modifier planed on the source origin (`Alt+X` then an
axis, with an Apply that keeps re-editing safe); every key as a real
`KeyMapItem`, edited in Blender's own rows on the addon preferences page; and a
per-mesh cache under all of it, without which none of the above is affordable
on every hover.

Not implemented yet: **N-gon on a face with several holes** (the pipeline
truncates past two loops, so only one bridge pair is ever possible),
**Ring with corner matching** (the two loops are paired by
arc length, so a hole shaped very differently from the outer boundary distorts
the band, and spans don't propagate *into* a ring), faces with **more than one
hole** (outer loop only, panel warns), **Quad Fill** with configurable loop
cuts, **N-Side** with per-side spans and manual corner placement, quad-family
(solving a chain of connected quads in one click).

Known rough edge: matching one side of a **multi-side ring** sets that loop's
whole "around" count from that side alone — `span_key_for` now keys a ring per
*loop* (so its two rims no longer knock each other out), but not per side.
Correct for the common case, where a rim is one cornerless side; wrong when a
ring's loop has several, and it wants the allocation logic
`ring.allocate_segments` already has, threaded back through the match.
