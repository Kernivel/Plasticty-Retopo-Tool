# Seeing the CAD structure

The bridge sends a triangle soup, so a Plasticity import reads as one
undifferentiated field of triangles — even though the mesh records which triangle
belongs to which CAD face.

Two overlays put that structure back. They make very different kinds of claim,
and the distinction matters.

| | Key | |
|---|---|---|
| **Plasticity edges** | <kbd>E</kbd> | exact, recovered from the face ids |
| **Surface flow** | <kbd>Ctrl</kbd>+<kbd>E</kbd> | **derived**, not imported |

Both work in every session phase — the structure is read while *choosing* a
surface as much as while adjusting one — and both are remappable. They can be
scoped to the whole object or to the patch under the cursor.

<!-- media: 12s. Toggle E on a part, then Ctrl+E, then orbit with both on. -->

## Plasticity edges are exact

A boundary half-edge `(a, b)` of one patch is matched by `(b, a)` of the patch
across it. So a **B-rep edge** is the maximal run of boundary segments whose
neighbouring face id does not change, and a **B-rep vertex** is where it does —
the same signal the topological corner test runs on.

Those vertices are also the only points patches weld to each other *by identity*,
which is why they are worth seeing.

**Show CAD Vertices** is off by default: on a real part every junction is a dot,
and a few hundred of them bury the edges they punctuate.

!!! info "One limitation"

    On an **open sheet**, a whole free boundary is one run — nothing distinguishes
    its segments. It costs nothing visually, since everything is drawn as
    segments anyway.

## Surface flow is derived

Plasticity's isoparametric curves come from each face's NURBS parameterisation,
and **none of it crosses the bridge**. The protocol carries no surface parameters
at all.

What is drawn instead is **the grid each face would be retopologized into**: the
same corner split, the same generators, at a low span, reprojected onto the
surface. On a fillet or a swept face that lands very close to the true isoparms,
because both answer the same question about the same boundary.

It is arguably the more useful of the two here, being the topology the retopology
would actually get. But it is derived, and the panel says so.

A [non-band annulus](rings.md#two-loops-is-not-the-same-thing-as-a-band) draws
its outer loop only, for the same reason it is not filled as a ring.

## Drawing through the model

**Draw Through the Mesh** is off by default.

Through-the-mesh reads well on a flat layout — a whole part's structure at a
glance — and turns a curved or enclosed part into a thicket, since the far side
shows through the near one. The readable default is the honest one.

Either way the lines are nudged very slightly towards the viewer. They lie
exactly *on* the surface they describe, so depth-testing them against it is a
coin flip per pixel and they come out as a stipple.

The B-rep vertex dots stay on top regardless — they are screen-space, so there is
no depth to test them against.

## Settings

| Setting | Default |
|---|---|
| **Show CAD Edges** | off |
| **Show CAD Vertices** | off |
| **Show Surface Flow** | off |
| **Flow Density** | 3 |
| **Show For** | object / patch under the cursor |
| **Draw Through the Mesh** | off |
| **CAD Edge Color / Width** | cyan, 2 px |
| **Surface Flow Color** | violet |
