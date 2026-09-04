# N-gon mode

<kbd>N</kbd>, while adjusting a patch.

A flat face gains nothing from a grid — the quads are all coplanar and all
identical. N-gon mode replaces the span grid with **one face following the
boundary**.

A patch committed as an n-gon reopens as one whatever the current mode, the same
rule as its spans.

## The boundary is *selected*, never resampled

This is the part worth understanding, because it is what makes n-gon mode useful
rather than merely cheap.

The boundary is walked accumulating turn, keeping a vertex every
**N-gon Detail Angle** degrees (20° by default). Every point kept is a genuine
CAD boundary vertex.

Arc-length resampling — which is what this did first — cannot do that. A chamfer
is typically 20–40°, which is *not* a corner by the angle test, so it sits in the
middle of a side; even spacing puts points wherever they fall and cuts a straight
chord across it. Accumulating turn keeps the chamfer's own vertex.

<kbd>Ctrl</kbd>+wheel drives the detail angle directly — inverted, and
multiplicatively, because a 2° step is nothing at 90° and everything at 4°.

!!! note "The cost, and how it is paid back"

    A curvature-selected n-gon side does not line up point-for-point with a
    *grid* neighbour along a shared edge, so on their own only the shared corners
    weld. [Side matching](matching.md) buys that back exactly — a matched side is
    handed the neighbour's own vertices — and it is on by default.

## When a patch cannot take one

The <kbd>N</kbd> key and the panel both explain themselves rather than doing
nothing. Two blockers:

**Not flat.** Every polygon of the patch is compared against their average
normal, against **N-gon Flatness Tolerance** (5° by default). One face across a
bevel or a fillet would become a flat lid over it — the shape simply gone.

**More than one hole.** One hole is fine: the outer boundary is bridged to the
hole with two edges and **two** n-gons are emitted.

!!! note "Why two faces and not one"

    A Blender n-gon carries a single loop. The one-face "keyhole" alternative
    needs the bridge vertices duplicated, and the boundary weld then merges them
    back and destroys the face. Two faces need no duplicates and stay manifold.

## Related settings

| Setting | Default | |
|---|---|---|
| **N-gon Detail Angle** | 20° | how much turn between kept boundary vertices |
| **N-gon Flatness Tolerance** | 5° | how far from flat a patch may be and still qualify |
| **Show N-gon Vertices** | on | draw a dot on each kept boundary vertex |
| **Match Neighbour** | on | apply side matching to n-gons without being asked |
