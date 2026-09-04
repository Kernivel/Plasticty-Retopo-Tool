# How it works

A Plasticity model arrives in Blender as a triangle soup, but it is not one:
every triangle still records which CAD face it came from. Plasticity Retop reads
that back and gives you the model as **patches** — one Plasticity face, one
patch — that you hover, pick, and fill with clean quads one at a time.

## From a triangle soup to patches

The bridge writes two custom properties on the imported mesh: a list of polygon
groups, and one Plasticity face id per group. That is the whole input — there is
no edge data at all.

Everything else is derived from it:

- **The patch** is the set of triangles sharing a face id.
- **Its boundary** is the set of edges with a triangle on one side only.
- **Its neighbours**: along that boundary, each edge's opposite polygon names the
  patch across it.
- **Its corners** are the vertices where that neighbour *changes* — a genuine
  B-rep vertex, the junction between two CAD edges.

Two details of the import make this less direct than it sounds, and both are
handled before anything else runs.

**Patch borders are duplicated.** The bridge tessellates each face separately, so
the two faces meeting along a CAD edge each carry their own copy of every vertex
on it, at the same position under different indices. They are merged by position
first — without that, no boundary edge ever finds its opposite and no patch can
name its neighbour.

**The two sides do not always tessellate an edge the same way.** The finer side
drops vertices in the *middle* of the coarser side's segments, so those segments
have no opposite to pair with. On one real part, 2327 of 4857 boundary segments
came back unpaired that way. Whatever the exact pairing misses is resolved
geometrically instead — the patch whose own boundary this segment *lies along*.

## Filling a patch

The corners split the boundary into **sides**, and **the number of sides chooses
the generator**:

| Sides | Generator | What it makes |
|---|---|---|
| 2 | **Wedge** | A grid running along a strip: two ends, two long sides |
| 3 | **Triangle** | A three-way Coons fill |
| 4 | **Quad** | A Coons grid, `Span U` × `Span V` |
| 5+ | **N-Side** | One Coons sub-patch per side around a central pole |
| — | **Ring** | Two boundary loops: a band of quads across the gap |
| — | **N-gon** | One face following the boundary, for flat patches |

The panel names the generator and the side count for the patch under the cursor.

Ring is not selected by side count — it is chosen by the patch having *two
boundary loops* — and [N-gon](ngon.md) is a mode you turn on with `N`, not
something a side count picks.

Every generator builds a grid by Coons interpolation between its sides, then
**reprojects the interior onto the original CAD surface**, so a curved patch
follows its curvature instead of chording across it. Boundary rows are
deliberately left where the loops put them: they are samples of the real
boundary, and a neighbour welds to them.

## Committing

Committed geometry goes into a second object, `<Source>_Retop`, and the two
patches on either side of a CAD edge weld to each other there:

- **Corners weld by identity.** They are untouched source vertices, so both
  patches name the same one and Blender merges them exactly.
- **Everything else welds by proximity**, and only among boundary points, at
  *Boundary Weld Distance*. An unscoped merge would silently pull unrelated
  points together and drop faces.

That is why [matching a neighbour](matching.md) matters: two patches only weld if
their shared boundary carries the *same vertices*, not merely the same count.

Every committed face is tagged with the patch it belongs to, which is what makes
a patch re-editable: click it again and its faces are found, removed, and
regenerated.

## Where corners come from

Two tests run, and they miss opposite things.

**The angle test** flags a boundary vertex that turns sharper than
*Corner Angle Threshold* (135° of deviation by default). It is geometric, so it
swallows anything gentle: a 30° chamfer reads as a smooth stretch, lands
mid-side, and every generator paves straight across it.

**The topological test** flags the vertex where the neighbouring Plasticity face
changes. That is a real B-rep vertex, at any angle — but a face whose whole
boundary runs against one single neighbour has no junction at all, however square
it looks.

The **Corners** setting picks between them, and there are **two of them**, because
the two modes want opposite things:

**Corners (Grid)** — default *Angle*. A grid's side count *chooses the
generator*, so every extra corner is an extra side. Turn topology on and a
bevel — whose long side borders face after face — goes from a Quad with a clean
grid to an N-Side with a pole in the middle of it.

**Corners (N-gon)** — default *Both*. An n-gon only *follows* its boundary, so
extra corners cost it nothing, and they are the one thing that keeps a shallow
chamfer the angle test cannot see.

*Topology* falls back to the angle test on a boundary that yields no junction: a
patch with no corners is one single side, which every span generator would read
as unusable.

## When there are too many corners

A tessellated curve can flag corner after corner, and a five-sided patch is
filled very differently from a four-sided one. So candidates are **ranked** by how
much the boundary bends there, and cut where consecutive scores fall off a cliff.

It is a *ratio*, never an absolute angle — that is the only thing separating the
two cases that both produce "more than four sides". A real hexagon bends the same
at every corner and has no cliff anywhere, so nothing is cut; a curve the angle
test over-sampled sits far below the real corners, and the drop is unmistakable.

Four is tried first, so a quad wins any tie, and cutting all the way down to a
triangle takes a much clearer cliff — a rectangle with one chamfered corner is
three 90° turns and two 45° ones, and a plain 2:1 rule called it a triangle.

**Topological corners are exempt** and take no part in the ranking. A junction is
a fact the mesh states outright, and a gentle chamfer's junction barely bends —
ranking it would drop the very thing the topology test exists to catch.

!!! note "\"Corners look uniform\""

    A coarsely tessellated circle and a real octagon are the same polyline. There
    is no way to tell them apart, so the addon does not guess: it says so in the
    panel and suggests raising the threshold.

## Boundaries with no corner at all

A single closed curve — a disc, a bore rim — has no corners by either test, one
side, and no generator that accepts one. Four corners are synthesised, but
**where** they go is read off the shape rather than spread evenly.

Turn is measured over a *window* rather than at a vertex, because a tessellated
rounded end is dozens of individually insignificant turns and one real feature.
However many features it finds decides the generator: two ends make a **Wedge**,
three a Triangle, four a Quad. Only a boundary whose turn is genuinely uniform —
a circle — falls back to four points spread by arc length.

That matters most on a long strip curving back on itself (a rounded slot, a bore
wall, a ribbon around a feature). Its perimeter is dominated by its two long
sides, so evenly spaced quarter points land in the *middle* of them, and the
"quad" handed to the Coons patch is half a long side plus half an end — which
comes out as a fan.

Rings never get synthesised corners: a cornerless rim gives them no trouble, and
inventing four corners on each of two loops would pair their points across a
shear instead of straight across the band.

## The N-Side patch

A quad mesh of an odd-sided region has to put an irregular vertex somewhere, and
the middle is where every tool puts it.

Each side is split at its midpoint, a spoke runs from there to the centre, and
the quad between two consecutive spokes goes through the **same Coons grid and
surface reprojection as every other generator**. The pole's valence is the *side*
count, the interior is a real grid, and every interior point sits on the surface.

The sides do not share one span — a side is bounded by the spokes of its two
*neighbours* — so several sides of one N-Side patch can be
[matched](matching.md) at once. What cannot be fitted is **refused** rather than
approximated: a match returning a count nobody asked for is a crack that looks
like a weld.
