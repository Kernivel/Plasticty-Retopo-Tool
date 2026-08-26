# Benchmark results

Every patch of every fixture shape, retopologized and measured at **MID** resolution.

Generated — do not hand-edit:

```bash
blender tests/fixtures/TestCases.blend --background --python scripts/gen_results.py
```

| | |
|---|---|
| Generated | 2026-08-26 |
| Blender | 5.0.1 |
| Addon | 0.34.0 (2026-08-25-a) |
| Resolution | MID |
| Fixture | `tests/fixtures/TestCases.blend`, 14 objects |

**Deviation is a percentage of each object's bounding-box diagonal, sampled across face interiors** — never at vertices, which the generators put on the surface by construction and which therefore read ~0 on every shape. The `vertex` column is shown only to make that point: it is the number a naive measurement would report.

## Overview

| Object | Source tris | CAD faces | Generators | Result | Deviation max | Open edges |
|---|--:|--:|---|--:|--:|--:|
| `Carved Rounded Slot` | 116 | 11 | 9&nbsp;Quad, 1&nbsp;Ring, 1&nbsp;Wedge | 104v / 75f | 1.7634% | 60 |
| `Cone` | 92 | 2 | 2&nbsp;Quad | 172v / 144f | 13.0024% | 56 |
| `Cube Bevel Edges` | 108 | 9 | 7&nbsp;Quad, 2&nbsp;Triangle | 366v / 339f | 1.0094% | 73 |
| `Cube Chamfer Edges` | 20 | 9 | 8&nbsp;Quad, 1&nbsp;N-Side | 44v / 36f | 0.0001% | 32 |
| `Cylinder` | 204 | 3 | 2&nbsp;Quad, 1&nbsp;Ring | 709v / 670f | 0.1506% | 78 |
| `Loopsided Chamfers Cube` | 28 | 14 | 14&nbsp;Quad | 16v / 14f | 0.0001% | 0 |
| `Plate` | 398 | 5 | 3&nbsp;Ring, 2&nbsp;Quad | 398v / 323f | 0.1828% | 150 |
| `Plate And Cylinder` | 1201 | 14 | 10&nbsp;Quad, 4&nbsp;Ring | 931v / 865f | 2.8593% | 166 |
| `Shape with holes` | 412 | 17 | 15&nbsp;Quad, 2&nbsp;Ring | 261v / 184f | 8.9809% | 150 |
| `Sphere` | 4970 | 1 | 1&nbsp;unusable | — | — | — |
| `Square Plate Small Hole` | 28 | 11 | 10&nbsp;Quad, 1&nbsp;Ring | 29v / 24f | 0.0001% | 18 |
| `Square Plate Small Hole Far Away` | 28 | 11 | 10&nbsp;Quad, 1&nbsp;Ring | 16v / 14f | 0.0007% | 0 |
| `Square Plate Small Hole Scaled Down` | 28 | 11 | 10&nbsp;Quad, 1&nbsp;Ring | 12v / 10f | 0.0661% | 0 |
| `Torus` | 11136 | 1 | 1&nbsp;unusable | — | — | — |

## Deviation from the CAD surface

| Object | mean | rms | p95 | max | vertex max |
|---|--:|--:|--:|--:|--:|
| `Carved Rounded Slot` | 0.0239% | 0.1246% | 0.1117% | **1.7634%** | 0.0000% |
| `Cone` | 0.2207% | 0.8876% | 0.8311% | **13.0024%** | 0.0000% |
| `Cube Bevel Edges` | 0.0767% | 0.2344% | 0.6948% | **1.0094%** | 0.0013% |
| `Cube Chamfer Edges` | 0.0000% | 0.0000% | 0.0000% | **0.0001%** | 0.0000% |
| `Cylinder` | 0.0385% | 0.0568% | 0.1099% | **0.1506%** | 0.0002% |
| `Loopsided Chamfers Cube` | 0.0000% | 0.0000% | 0.0000% | **0.0001%** | 0.0000% |
| `Plate` | 0.0192% | 0.0427% | 0.1097% | **0.1828%** | 0.0000% |
| `Plate And Cylinder` | 0.0410% | 0.0978% | 0.1744% | **2.8593%** | 0.0004% |
| `Shape with holes` | 0.0543% | 0.2510% | 0.1317% | **8.9809%** | 0.0000% |
| `Square Plate Small Hole` | 0.0000% | 0.0000% | 0.0000% | **0.0001%** | 0.0000% |
| `Square Plate Small Hole Far Away` | 0.0000% | 0.0001% | 0.0000% | **0.0007%** | 0.0000% |
| `Square Plate Small Hole Scaled Down` | 0.0059% | 0.0172% | 0.0441% | **0.0661%** | 0.0001% |

A large `max` against a modest `p95` means a few samples are far out rather than the whole surface being off — which is the signature of a hole being paved over, or an apex no grid represents.

## Topology

| Object | Verts | Faces | Face sizes | Open edges | Non-manifold | Unwelded | Interior poles |
|---|--:|--:|---|--:|--:|--:|--:|
| `Carved Rounded Slot` | 104 | 75 | 2&times;3-gon, 73&times;4-gon | 60 | 0 | 0 | 2 |
| `Cone` | 172 | 144 | 144&times;4-gon | 56 | 0 | 0 | 0 |
| `Cube Bevel Edges` | 366 | 339 | 11&times;3-gon, 328&times;4-gon | 73 | 0 | 0 | 2 |
| `Cube Chamfer Edges` | 44 | 36 | 36&times;4-gon | 32 | 0 | 0 | 5 |
| `Cylinder` | 709 | 670 | 670&times;4-gon | 78 | 0 | 0 | 4 |
| `Loopsided Chamfers Cube` | 16 | 14 | 14&times;4-gon | 0 | 0 | 0 | 8 |
| `Plate` | 398 | 323 | 323&times;4-gon | 150 | 0 | 0 | 0 |
| `Plate And Cylinder` | 931 | 865 | 865&times;4-gon | 166 | 0 | 0 | 4 |
| `Shape with holes` | 261 | 184 | 184&times;4-gon | 150 | 0 | 0 | 8 |
| `Square Plate Small Hole` | 29 | 24 | 24&times;4-gon | 18 | 0 | 0 | 8 |
| `Square Plate Small Hole Far Away` | 16 | 14 | 14&times;4-gon | 0 | 0 | 0 | 8 |
| `Square Plate Small Hole Scaled Down` | 12 | 10 | 10&times;4-gon | 0 | 0 | 0 | 8 |

**Non-manifold and unwelded are zero everywhere**, which is the pair worth being strict about. Open-edge counts are a worst case rather than a quality score: this run commits in the fixture's own face order, and auto-matching can only match an *already committed* neighbour, so a patch baked early can never weld to one baked later.

## Cell quality

| Object | Aspect p50 | p95 | max | Skew p50 | p95 | max | Edge cv |
|---|--:|--:|--:|--:|--:|--:|--:|
| `Carved Rounded Slot` | 2.29 | 10.00 | **11.8** | 0.0° | 54.5° | 86.5° | 0.75 |
| `Cone` | 1.19 | 3.78 | **5.8** | 31.4° | 67.1° | 78.1° | 0.50 |
| `Cube Bevel Edges` | 1.23 | 4.00 | **7.1** | 0.0° | 39.1° | 88.2° | 0.72 |
| `Cube Chamfer Edges` | 1.77 | 14.08 | **14.1** | 0.0° | 61.1° | 90.0° | 0.35 |
| `Cylinder` | 1.07 | 1.15 | **1.2** | 1.2° | 37.7° | 80.4° | 0.10 |
| `Loopsided Chamfers Cube` | 4.95 | 11.06 | **11.1** | 26.6° | 44.0° | 44.0° | 0.51 |
| `Plate` | 1.19 | 1.63 | **1.6** | 12.8° | 49.5° | 79.3° | 0.23 |
| `Plate And Cylinder` | 1.04 | 1.81 | **8.0** | 2.0° | 7.4° | 75.6° | 1.66 |
| `Shape with holes` | 1.20 | 1.39 | **9.2** | 1.3° | 3.6° | 3.6° | 2.10 |
| `Square Plate Small Hole` | 3.10 | 400.00 | **400.0** | 0.0° | 45.0° | 45.0° | 0.76 |
| `Square Plate Small Hole Far Away` | 5.00 | 798.92 | **798.9** | 0.0° | 45.0° | 45.0° | 0.81 |
| `Square Plate Small Hole Scaled Down` | 3.54 | 7.07 | **7.1** | 0.0° | 45.0° | 45.0° | 0.68 |

Percentiles and worst, never means: the failure mode is a handful of degenerate cells from a fan or a stretched band, and a mean hides exactly that. `Edge cv` is the coefficient of variation of edge length — how uneven the mesh is overall.

## One shape, three placements

The same CAD shape, modelled three times in Plasticity: at the origin, out at (50, 100, 20), and scaled to a hundredth. Because the geometry is identical, **any difference here is attributable to placement alone**.

| Placement | Result | Generators | Deviation max | Open edges | Aspect max |
|---|--:|---|--:|--:|--:|
| `Square Plate Small Hole` | 29v / 24f | 10&nbsp;Quad, 1&nbsp;Ring | 0.0001% | 18 | 400 |
| `Square Plate Small Hole Far Away` | 16v / 14f | 10&nbsp;Quad, 1&nbsp;Ring | 0.0007% | 0 | 799 |
| `Square Plate Small Hole Scaled Down` | 12v / 10f | 10&nbsp;Quad, 1&nbsp;Ring | 0.0661% | 0 | 7 |

The generators and side counts agree across all three — corner detection and generator selection are scale-stable. It is the density that moves, because neither absolute tolerance is scaled to the part: `boundary_weld_distance` defaults to 1e-4 *in metres*, and `patch_data`'s weld epsilon is a hard-coded 1e-5. Scaling the weld distance to the part recovers some of the difference on the small one and none of it on the far one, so a second cause is still open.

## Commit order changes the result

Same geometry, same generator chosen for every face — only the order patches are committed in differs. Span propagation seeds everything downstream from whichever patch commits first.

| Object | Fixture order | Face id ascending | Face id descending |
|---|--:|--:|--:|
| `Cube Chamfer Edges` | 44v / 36f | 42v / 32f | 22v / 16f |
| `Cube Bevel Edges` | 366v / 339f | 413v / 394f | 69v / 56f |

This is why the golden table in `tests/test_fixtures.py` treats generator and side count as the entries that should hold steady, and vertex and face counts as regression detectors rather than quality scores.

## Known gaps

Each is asserted in `tests/test_fixtures.py` as *still broken*, so it fails when it starts working and forces the expectations to be updated. See `tests/fixtures/README.md` for the full write-up.

| # | Gap | Where it shows |
|--:|---|---|
| 1 | One shape at three placements gives three different retopologies | `Square Plate Small Hole` &times;3 |
| 2 | A small hole is still filled as a band, stretching quads from the outline to the hole | `Square Plate Small Hole` |
| 3 | A closed periodic face has no boundary loop, so it is silently unpickable | `Sphere`, `Torus` |
| 4 | A cone's apex is a singularity no quad grid represents | `Cone` |
| 5 | Faces past two boundary loops have every hole but the outer boundary paved over | `Shape with holes` |
| 6 | Symmetric pentagons resolve to different generators | `Cube Chamfer Edges` |
