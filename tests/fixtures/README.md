# Test fixtures

`TestCases.blend` is real Plasticity output, imported through the
[plasticity-blender-addon](https://github.com/nkallen/plasticity-blender-addon)
bridge. It is the only place in the suite where the input contract is actually
tested: every other test builds its mesh from the same mental model as the
code, so none of them can catch "the bridge emits X and we assumed Y".

`scripts/deploy.py` skips `tests/`, so nothing here ships into Blender's addons
folder.

## Running it yourself

Everything runs headless. Blender is found via `--blender`, `$BLENDER`, `PATH`,
then the usual install paths; **Plasticity is not needed**. There may be no
system Python, so if `python` is the Windows Store stub use Blender's own:
`<Blender>/<ver>/python/bin/python.exe`.

**Pass/fail — did I break something?**

```bash
python scripts/run_tests.py                         # all 32 files
python scripts/run_tests.py tests/test_fixtures.py  # just the fixture goldens
```

`test_fixtures.py` is the one that reads this folder. It asserts, per object:
the generator and side count chosen for every CAD face, the result mesh size,
deviation under a recorded ceiling, the open-edge count, and that nothing is
non-manifold, unwelded, wire, or facing into the surface.

**Numbers — how accurate is it right now?**

```bash
blender tests/fixtures/TestCases.blend --background --factory-startup --python scripts/benchmark.py
blender tests/fixtures/TestCases.blend --background --factory-startup --python scripts/benchmark.py -- --resolution HIGH --object Cylinder
```

The benchmark retopologizes every patch and measures deviation from the CAD
surface, topology and cell quality. `scripts/gen_results.py` is the same run
written up as `RESULTS.md` at the repo root — read that for the current
figures rather than trusting any number quoted in this file.

**`--factory-startup` is not optional on any of those**, however read-only the
script looks. Without it every installed addon loads too, and one of them has
*saved this fixture over itself* on quit (the tell is a `.blend1` appearing
beside it). Run `git status` afterwards, and `git checkout` the file back if it
moved.

## Changing the fixture

Model in `TestCases.plasticity` — that is the working file, it carries no
golden values and nothing reads it — then re-export the whole thing through the
bridge over `TestCases.blend`. **Then regenerate the golden table**, because a
re-export renumbers every Plasticity face id even when no vertex moves:

```bash
blender tests/fixtures/TestCases.blend --background --factory-startup --python scripts/gen_expectations.py
blender tests/fixtures/TestCases.blend --background --factory-startup --python scripts/gen_results.py
```

The first prints a table to stdout; paste it over `EXPECTED` in
`tests/test_fixtures.py`. The second rewrites `RESULTS.md`. Neither file is
ever hand-edited.

**Read the diff, don't just accept it.** Generator and side count per face are
what should hold steady for any shape you did not touch — those moving is a
real finding. Vertex and face counts are order-sensitive (see the last section)
and move for reasons that are not regressions.

Re-exporting is safe for the *shapes*: when the placement variants were added
the whole file went through it, and every carried-over shape came back with an
identical point set. The tessellation genuinely comes from Plasticity, not from
Blender. What it disrupts is the bookkeeping. Note also that git stores each
re-save of both files as a whole new blob, forever.

## Provenance

| | |
|---|---|
| Plasticity | 26.1.3 |
| Bridge addon | 2.2.1 |
| Blender that saved the `.blend` | 5.1 |
| Added | 2026-08-25 |

The Plasticity version is recoverable from the file itself
(`head -c 96 tests/fixtures/TestCases.plasticity`); the bridge version is the
one thing neither file records, and it is the layer most likely to change what
arrives in Blender.

**The Blender version matters.** `.blend` is forward-compatible but not
backward, and `bl_info` still declares 4.2 as the minimum while the fixture is
saved by 5.1. Those two numbers disagree: either raise `bl_info` to match what
is actually tested, or rebuild the `.blend` from the oldest supported Blender.

## What each object is for

| Object | CAD faces | Exercises |
|---|--:|---|
| `Cube Chamfer Edges` | 9 | All-planar: deviation must be ~zero at any span, the sharpest assertion available. Holds the two pentagons that disagree. |
| `Cube Bevel Edges` | 13 | Rounded edges — chordal sag, and whether faces flanking a bevel stay Quad. The only object with **tangent** patch borders. |
| `Loopsided Chamfers Cube` | 14 | Asymmetric chamfers, so the boundary turns by something other than 45° or 90°. |
| `Cylinder` | 3 | `ring.is_band` saying yes. Wall = Ring; caps = cornerless discs given synthesised corners. |
| `Truncated Cone` | 3 | A **tapered** band: rims 2.29:1, by far the widest ratio here (next is 1.46). Comes out clean — 0.08% deviation, worst aspect ratio 1.8. |
| `Cone` | 2 | A lateral face that closes on a **point**. The apex is a singularity no quad grid represents. |
| `Plate` | 5 | A hole nearly as large as the plate — a genuine band. |
| `Flat Loop` | 4 | A flat annulus whose two rims are both cornerless. The shape that shows a band's rungs leaning; see `ring.phase_align` and `tests/test_ring_straightness.py`. |
| `Square Plate Small Hole` | 11 | A hole *small* relative to the plate — the annulus that must **not** be filled as a band. |
| `Square Plate Small Hole Far Away` | 11 | The same shape, modelled out at (50, 100, 20). |
| `Square Plate Small Hole Scaled Down` | 11 | The same shape again, a hundredth the size. |
| `Carved Rounded Slot` | 11 | An obround slot: a long strip curving back on itself, for `shape_corners`. |
| `Plate And Cylinder` | 14 | A filleted boss — a ring-shaped band that also joins its neighbours smoothly. |
| `Shape with holes` | 17 | Faces with five boundary loops each, past what the pipeline handles. |
| `Sphere` | 1 | A single closed periodic face — no boundary loop at all. |
| `Torus` | 1 | The same, at genus 1. |

The three `Square Plate Small Hole` variants are one shape at three placements,
and exist to be compared with each other rather than read individually: any
difference between their results is attributable to placement alone, which
makes them a measurement rather than three test cases.

### Not covered

- **Nested collection hierarchy.** Everything sits directly in `Inbox`, so
  `source_collection_path` returns `[]` and the mirroring in
  `place_result_object` is barely touched.
- **Creasing at a tangent border.** `Cube Bevel Edges` has the geometry, but
  nothing asserts that `apply_result_shading` leaves a smooth fillet-to-plane
  border uncreased. A missing assertion, not a missing shape.

## Known gaps recorded against these shapes

`test_fixtures.py` asserts these are *still broken*, and fails when they start
working — so fixing one forces the expectations to be updated rather than
leaving a test that quietly asserts a bug.

1. **One shape at three placements gives three different retopologies.** The
   generators and side counts agree across all three; it is the density that
   moves. Neither absolute tolerance is scaled to the part —
   `boundary_weld_distance` defaults to 1e-4 in metres and `patch_data`'s weld
   epsilon is a hard-coded 1e-5. Scaling the weld distance to the part recovers
   some of it but not all, so a **second cause is still open**.
2. **A small hole is still filled as a band.** `Square Plate Small Hole` has
   its top face come back as a Ring, quads stretched from the outline to the
   hole at an aspect ratio around 800:1. `ring.is_band` does not catch it.
3. **A closed periodic face cannot be retopologized.** `Sphere` and `Torus`
   have one CAD face and no boundary loop, so `patchprep.prepare_patch` returns
   `None` and the patch is silently unpickable, with no message anywhere.
4. **A cone's apex is approximated badly** — two orders of magnitude worse than
   the cylinder beside it. The lateral face is a cornerless loop closing on a
   point, and gets filled as a Quad.
5. **Faces past two boundary loops are paved over.** The two 5-loop faces of
   `Shape with holes` keep only their outer boundary, which is what their ~9%
   max deviation measures against a p95 two orders of magnitude below it.
6. **Symmetric pentagons resolve to different generators.** On
   `Cube Chamfer Edges` two faces identical by symmetry come out `Quad` and
   `N-Side` — `sides.dominant_corners` tipping either side of `CORNER_CLIFF`.
   The test finds them by shape rather than by id, since a re-export renumbers
   ids but moves no vertices.

## Commit order changes the result

Worth knowing before reading any count in the golden table. `test_fixtures.py`
commits in the fixture's own face order, and span propagation seeds everything
downstream from whichever patch commits first — so the *same shapes in a
different order* give a legitimately different mesh. On `Cube Bevel Edges` that
is currently a 6x swing in vertex count with no change to the geometry or to
the generator chosen for any face (the table is in `RESULTS.md`).

Open-edge counts have the same character, for a related reason: auto-matching
can only match an *already committed* neighbour (`build_side_references` reads
`committed_boundary_map`), so a patch baked early can never weld to one baked
later. Every count is a worst case, and working deliberately in the viewport
does better.

That is why the golden table records generator and side count as the entries
that should hold steady, and treats vertex and face counts as regression
detectors rather than quality scores. All of it stays pinned because the order
is deterministic for a given file — a change in these numbers with the fixture
untouched is a real change in behaviour.
