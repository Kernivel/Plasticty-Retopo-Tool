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
| `TestCases.plasticity` | 78 KB | The B-rep source. What the shapes actually *are*. |
| `TestCases.blend` | 421 KB | What the bridge made of it. What the tests read. |

Only the `.blend` is consumed by anything — nothing in the addon or the suite
opens the `.plasticity` file, and opening it needs Plasticity itself. It is
committed because it is the origin of the fixture, and without it the shapes
can never be extended or re-exported: the `.blend` is a tessellation, and a
tessellation cannot be edited back into the B-rep it came from.

Two jobs it does, both of which the frozen-file rule below otherwise makes
impossible:

- **Adding a case.** Model the new shape here, export the whole file through
  the bridge, and append *only the new object* to the `.blend`. Every existing
  object stays byte-for-byte as it was, so every golden value survives.
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

That second path is less destructive than the frozen-file rule below makes it
sound, because the tessellation comes from **Plasticity, not Blender** — the
bridge only receives a mesh. A re-export at the same settings ought therefore
to produce identical vertices and leave every golden value standing. Ought to:
that has not been verified, so treat a re-export as a change to be checked
against `test_fixtures.py` rather than assumed safe. If the goldens survive, it
was free; if they move, the tessellation is not as reproducible as it looks and
that is worth knowing on its own.

## Treat the `.blend` as frozen

Never re-export the existing objects in place *without checking*. If a fresh
export re-tessellates, every vertex moves slightly and every golden value in
`test_fixtures.py` moves with it — at which point a real regression is
indistinguishable from a re-export. Git also stores each re-save as a whole new
blob, forever.

New cases go in as **new objects appended** to the `.blend`, modelled in the
`.plasticity` file alongside the existing ones. Adding an object leaves every
existing expectation untouched, which is the whole point.

The `.plasticity` file is the opposite: it is the working file and is *meant*
to be edited. It carries no golden values, and nothing reads it.

## What each object is for

| Object | CAD faces | Exercises |
|---|---|---|
| `Cube Chamfer Edges` | 9 | All-planar. Deviation must be exactly zero at any span — the sharpest assertion available. Also holds the two pentagons that disagree (see below). |
| `Cube Bevel Edges` | 9 | Rounded edges: chordal sag, and whether the faces flanking a bevel stay Quad rather than becoming an N-Side fan. Corner patches come out Triangle. |
| `Cylinder` | 3 | `ring.is_band` saying yes. Wall = Ring (two rim loops); caps = cornerless discs given four synthesised corners. |
| `Plate` | 5 | A hole small relative to the plate — the annulus that must **not** be filled as a band. Three Rings, two Quads. |
| `Shape with holes` | 17 | Faces with five boundary loops each, i.e. past what the pipeline handles. |
| `Sphere` | 1 | A single closed periodic face — no boundary loop at all. |
| `Torus` | 1 | The same, at genus 1. |

### Not covered

- **Anything away from the origin.** Every object is at identity, unit scale,
  ~1.0 across. The `1e-5` *absolute* weld epsilon — the thing CLAUDE.md says to
  suspect first when a patch dices strangely — is therefore never exercised.
  Re-exporting `Plate` at roughly `(500, 300, 200)`, and again scaled to a few
  millimetres, is the highest-value addition to make here.
- **A fillet running tangentially into a flat face**, which is the case
  `sharp_edge_angle` exists for.
- **Nested collection hierarchy.** Everything sits directly in `Inbox`, so
  `source_collection_path` returns `[]` and the mirroring in
  `place_result_object` is barely touched.

## Known gaps recorded against these shapes

`test_fixtures.py` asserts these are *still broken*, and fails when they start
working — so fixing one forces the expectations to be updated rather than
leaving a test that quietly asserts a bug.

1. **A closed periodic face cannot be retopologized.** `Sphere` and `Torus`
   have one CAD face and no boundary loop, so `patchprep.prepare_patch`
   returns `None` and the patch is silently unpickable, with no message
   anywhere.
2. **Faces past two boundary loops are paved over.** The two 5-loop faces of
   `Shape with holes` keep only their outer boundary. This is what the 8.98%
   max deviation measures — p95 is an unremarkable 0.20%.
3. **Two symmetric pentagons resolve to different generators.** On
   `Cube Chamfer Edges`, faces `8834` and `8845` are identical by symmetry
   (3 polys, one 5-vertex loop) but come out `Quad` and `N-Side` respectively —
   `sides.dominant_corners` tipping either side of `CORNER_CLIFF`.

## About the open-edge counts

`test_fixtures.py` pins an open boundary edge count per object. Read them as a
**worst case, not a quality score**: the test commits patches in `face_id`
order, and auto-matching can only match an *already committed* neighbour
(`build_side_references` reads `committed_boundary_map`), so a patch baked
early can never weld to one baked later. Working deliberately in the viewport
does better. The numbers are pinned because the iteration order is
deterministic, so a change in them is a real change in behaviour.
