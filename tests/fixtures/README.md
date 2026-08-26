# Test fixtures

`TestCases.blend` is real Plasticity output, imported through the
[plasticity-blender-addon](https://github.com/nkallen/plasticity-blender-addon)
bridge. It is the only place in the suite where the input contract is actually
tested: every other test builds its mesh from the same mental model as the
code, so none of them can catch "the bridge emits X and we assumed Y".

Consumed by `tests/test_fixtures.py` (assertions) and `scripts/benchmark.py`
(the same measurements, printed for reading by hand):

```bash
blender tests/fixtures/TestCases.blend --background --python scripts/benchmark.py -- --resolution HIGH
```

`scripts/deploy.py` skips `tests/`, so nothing here ships into Blender's addons
folder.

## The two files

| File | | |
|---|---|---|
| `TestCases.plasticity` | 166 KB | The B-rep source. What the shapes actually *are*. |
| `TestCases.blend` | 559 KB | What the bridge made of it. What the tests read. |

Only the `.blend` is consumed by anything — nothing in the addon or the suite
opens the `.plasticity` file, and opening it needs Plasticity itself. It is
committed because it is the origin of the fixture, and without it the shapes
can never be extended or re-exported: the `.blend` is a tessellation, and a
tessellation cannot be edited back into the B-rep it came from.

Two jobs it does, both otherwise impossible once the `.blend` exists:

- **Adding a case.** Model the new shape here and re-export. Appending only
  the new object to the `.blend` would preserve the golden table, but that is
  fiddly and in practice the whole file gets re-exported — which is fine, and
  what happened when the placement variants were added. Just regenerate the
  table afterwards and read the diff, as described under Provenance.
- **Re-saving the `.blend` for an older Blender** — see the version note below.

## Provenance

What makes a surprising result diagnosable a year from now.

| | |
|---|---|
| Plasticity version | 26.1.3 |
| Bridge addon version | _TODO_ |
| Blender that saved the `.blend` | 5.0.1 (`a3db93c5b259`) |
| Added | 2026-08-25 |

The Plasticity version is not a note anyone has to maintain — it is in the
`.plasticity` file itself, as a JSON header a little way in:

```bash
head -c 96 tests/fixtures/TestCases.plasticity   # ..."generator":"Plasticity 26.1.3"
```

The bridge version is the one thing genuinely unrecoverable from either file,
and it is the layer most likely to change what arrives in Blender.

**The Blender version matters.** `.blend` is forward-compatible but not
backward: a file saved by 5.0 is not guaranteed to open correctly in 4.2, which
is what `bl_info` currently declares as the minimum. Right now those two
numbers disagree — either raise `bl_info` to match what actually gets tested,
or rebuild the `.blend` by re-exporting `TestCases.plasticity` through the
bridge from the oldest Blender supported.

That second path is less destructive than it sounds, and this has now been
**measured** rather than assumed. When the placement variants were added, the
whole file was re-exported — and comparing it against the previous commit
showed that for every carried-over shape the *point set is identical*. The
tessellation really does come from Plasticity rather than Blender.

What a re-export does change:

- **Every face id is renumbered.** `Cube Bevel Edges` went from 49747… to
  357…. Since the goldens are keyed by face id, all of them had to be
  regenerated even though not one vertex moved.
- **Vertex and face ordering changes**, which changes the order patches are
  committed in — and that alone moves the result (see the note at the bottom).
- Anything actually re-modelled changes for real. `Torus` went from 2745 to
  5568 vertices.

So a re-export is safe for the *shapes* and disruptive to the *table*. Run
`scripts/gen_expectations.py` afterwards and read the diff: generator and side
count per face are what should hold steady.

## Re-exporting: safe, but regenerate the table

The original version of this file said to treat the `.blend` as frozen,
because a re-export was assumed to re-tessellate and invalidate everything.
Measurement says otherwise — the shapes survive, the bookkeeping does not.

So the rule is not "never re-export", it is **never re-export without
regenerating**:

```bash
blender tests/fixtures/TestCases.blend --background --python scripts/gen_expectations.py
```

and paste the result over `EXPECTED` in `tests/test_fixtures.py`. Then read the
diff. Generator and side count per face should be unchanged for any shape you
did not touch; if one of those moved, that is a real finding, not bookkeeping.

Two things worth keeping in mind anyway. Git stores each re-save of both files
as a whole new blob, forever, so this is not free. And the `.plasticity` file
is the working file — it is *meant* to be edited, carries no golden values, and
nothing reads it.

## What each object is for

| Object | CAD faces | Exercises |
|---|---|---|
| `Cube Chamfer Edges` | 9 | All-planar: deviation must be zero at any span, the sharpest assertion available. Holds the two pentagons that disagree. |
| `Cube Bevel Edges` | 9 | Rounded edges — chordal sag, and whether faces flanking a bevel stay Quad. Corner patches come out Triangle. It is also the only object with **tangent** patch borders (8 segments under 10°, the shallowest 2.81°). |
| `Loopsided Chamfers Cube` | 14 | Asymmetric chamfers, so the boundary turns by something other than 45° or 90°. |
| `Cylinder` | 3 | `ring.is_band` saying yes. Wall = Ring; caps = cornerless discs given synthesised corners. |
| `Cone` | 2 | A lateral face that closes on a **point**. The apex is a singularity no quad grid represents. |
| `Plate` | 5 | A hole nearly as large as the plate — a genuine band. |
| `Square Plate Small Hole` | 11 | A hole *small* relative to the plate — the annulus that must **not** be filled as a band. |
| `Square Plate Small Hole Far Away` | 11 | The same shape, modelled out at (50, 100, 20). |
| `Square Plate Small Hole Scaled Down` | 11 | The same shape again, a hundredth the size. |
| `Carved Rounded Slot` | 11 | An obround slot: a long strip curving back on itself, for `shape_corners`. |
| `Plate And Cylinder` | 14 | A filleted boss — a ring-shaped band that also joins its neighbours smoothly. |
| `Shape with holes` | 17 | Faces with five boundary loops each, past what the pipeline handles. |
| `Sphere` | 1 | A single closed periodic face — no boundary loop at all. |
| `Torus` | 1 | The same, at genus 1. |

The three `Square Plate Small Hole` variants are one shape at three placements,
and they exist to be compared with each other rather than read individually.
Because they are the same shape, any difference between their results is
attributable to placement alone — which is what makes them a measurement
rather than three separate test cases.

### Not covered

- **Nested collection hierarchy.** Everything sits directly in `Inbox`, so
  `source_collection_path` returns `[]` and the mirroring in
  `place_result_object` is barely touched.
- **Creasing at a tangent border.** `Cube Bevel Edges` has the geometry, but
  nothing asserts that `apply_result_shading` leaves a smooth fillet-to-plane
  border uncreased. That is a missing assertion, not a missing shape.
- **A tapered band.** `Cone` is a full cone, so its two-loop case never
  arises; a truncated cone would give a Ring whose rims differ in size, which
  no fixture has (every band here has rims within 11% of each other).

## Known gaps recorded against these shapes

`test_fixtures.py` asserts these are *still broken*, and fails when they start
working — so fixing one forces the expectations to be updated rather than
leaving a test that quietly asserts a bug.

1. **One shape at three placements gives three different retopologies.**
   `Square Plate Small Hole` comes out 29v/24f at the origin, 16v/14f out at
   (50, 100, 20), and 12v/10f scaled to a hundredth. The generators and side
   counts agree across all three — it is the density that moves. Neither
   absolute tolerance is scaled to the part: `boundary_weld_distance` defaults
   to 1e-4 in metres and `patch_data`'s weld epsilon is a hard-coded 1e-5.
   Scaling the weld distance to the part recovers 12v→16v on the small one but
   changes nothing on the far one, so a **second cause is still open**.
2. **A small hole is still filled as a band.** `Square Plate Small Hole` has
   its top face come back as a Ring, giving quads stretched from the outline to
   the hole at an aspect ratio around 400:1. This is the case CLAUDE.md calls
   the disaster, and `ring.is_band` does not currently catch it.
3. **A closed periodic face cannot be retopologized.** `Sphere` and `Torus`
   have one CAD face and no boundary loop, so `patchprep.prepare_patch` returns
   `None` and the patch is silently unpickable, with no message anywhere.
4. **A cone's apex is approximated badly** — 13% deviation against 0.15% for
   the cylinder beside it. The lateral face is a cornerless loop closing on a
   point, and it gets filled as a Quad.
5. **Faces past two boundary loops are paved over.** The two 5-loop faces of
   `Shape with holes` keep only their outer boundary, which is what their 8.98%
   max deviation measures against a p95 of 0.20%.
6. **Symmetric pentagons resolve to different generators.** On
   `Cube Chamfer Edges` two faces that are identical by symmetry come out
   `Quad` and `N-Side` — `sides.dominant_corners` tipping either side of
   `CORNER_CLIFF`. The test finds them by shape rather than by id, since a
   re-export renumbers ids but moves no vertices.

## Commit order changes the result

Worth knowing before reading any count in the golden table. `test_fixtures.py`
commits in the fixture's own face order, and span propagation seeds everything
downstream from whichever patch commits first — so the *same shapes in a
different order* give a legitimately different mesh:

| Object | Fixture order | Face id ascending | Face id descending |
|---|--:|--:|--:|
| `Cube Bevel Edges` | 366v / 339f | 413v / 394f | 69v / 56f |
| `Cube Chamfer Edges` | 44v / 36f | 42v / 32f | 22v / 16f |

A 7x swing on the bevelled cube, with no change to the geometry or to the
generator chosen for any face. Reversing the fixture's own order rather than
sorting descending pushes it further still, to 32v / 29f — the orderings are
different and so are the answers, which is itself the point.

That is why the golden table records generator and side count as the entries
that should hold steady, and treats vertex and face counts as regression
detectors rather than quality scores.

These figures are regenerated into `RESULTS.md` rather than maintained here;
see that file for the current run.

The open-edge counts have the same character, for a related reason:
auto-matching can only match an *already committed* neighbour
(`build_side_references` reads `committed_boundary_map`), so a patch baked
early can never weld to one baked later. Every count in the table is therefore
a worst case, and working deliberately in the viewport does better.

All of it stays pinned because the order is deterministic for a given file — a
change in these numbers with the fixture untouched is a real change in
behaviour.
