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

## Provenance

Fill these in — they are what makes a surprising result diagnosable a year from
now, and none of it is recoverable from the file itself.

| | |
|---|---|
| Plasticity version | _TODO_ |
| Bridge addon version | _TODO_ |
| Blender that saved the file | 5.0.1 (`a3db93c5b259`) |
| Added | 2026-08-25 |

**The Blender version matters.** `.blend` is forward-compatible but not
backward: a file saved by 5.0 is not guaranteed to open correctly in 4.2, which
is what `bl_info` currently declares as the minimum. Either re-save this from
the oldest Blender actually supported, or raise `bl_info` to match what gets
tested. Right now those two numbers disagree.

## Treat the file as frozen

Never re-export the existing objects in place. A fresh export re-tessellates,
every vertex moves slightly, and every golden value in `test_fixtures.py` moves
with it — at which point a real regression is indistinguishable from a
re-export. Git also stores each re-save as a whole new blob, forever.

New cases go in as **new objects appended** to this file, or as a second file.
Adding an object leaves every existing expectation untouched.

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
