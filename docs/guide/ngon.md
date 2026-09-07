# N-gon mode

<kbd>N</kbd>, while adjusting a patch.

If you're not looking to Subdivide a surface, using and N-gon usually is the best approach.
N-gon mode replaces the span grid with **one face following the boundary**.

A patch committed as an n-gon reopens as one whatever the current mode, the same
rule as its spans.

## When a patch cannot take one

The <kbd>N</kbd> key and the panel both explain themselves rather than doing
nothing. Two blockers:

**Not flat.** Every polygon of the patch is compared against their average
normal, against **N-gon Flatness Tolerance** (5° by default). One face across a
bevel or a fillet would become a flat lid over it — the shape simply gone.

**More than one hole.** One hole is fine: the outer boundary is bridged to the
hole with two edges and **two** n-gons are emitted.

## NGon samples


<kbd>Ctrl</kbd>+wheel drives the detail angle directly.

When not using matching, this can be helpful to drive the details of the n-gon.


## Related settings

| Setting | Default | |
|---|---|---|
| **N-gon Detail Angle** | 20° | how much turn between kept boundary vertices |
| **N-gon Flatness Tolerance** | 5° | how far from flat a patch may be and still qualify |
| **Show N-gon Vertices** | on | draw a dot on each kept boundary vertex |
| **Match Neighbour** | on | apply side matching to n-gons without being asked |
