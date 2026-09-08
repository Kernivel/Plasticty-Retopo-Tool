# 2. Choosing a generator

Step 1 handed over a boundary. This step turns it into **sides**, and the sides
are what choose the generator — so everything about how a patch is filled is
decided by where its corners land.

## Corners, then sides

Two corner tests run, and they miss opposite things.

**The angle test** flags a boundary vertex that turns sharper than *Corner Angle
Threshold* (135° of deviation by default). It is purely geometric, so it swallows
anything gentle: a 30° chamfer reads as a smooth stretch, lands mid-side, and
every generator paves straight across it.

**The topological test** flags the vertex where the neighbouring Plasticity face
changes — a real B-rep vertex, at any angle. But a face whose whole boundary runs
against one single neighbour has no junction at all, however square it looks.

Which one runs is set **per mode**, and that split is not cosmetic:

| Mode | Method | Why |
|---|---|---|
| Grid generators | *Angle* | A grid's side count **chooses the generator**, so every extra corner is an extra side. With topology on, a bevel — whose long side borders face after face — goes from a Quad with a clean grid to an N-Side with a pole in the middle of it. |
| [N-gon](../guide/ngon.md) | *Both* | An n-gon only *follows* its boundary, so extra corners cost it nothing, and they are the one thing that keeps a shallow chamfer the angle test cannot see. |

*Topology* falls back to the angle test on a boundary that yields no junction: a
patch with no corners is one single side, which every span generator would read
as unusable.

!!! info "You do not choose this — the rows are behind Developer Mode"

    Measured rather than asserted. Across the whole fixture at Mid resolution the
    method changes the result on **two objects out of sixteen** in either mode,
    and on those two the shipped default is the better one:

    | | Angle | Both / Topology |
    |---|--:|--:|
    | Cube Bevel Edges, *grid* | **0.221%**, 9 Quad + 2 Triangle + 2 Wedge | 0.838%, two faces fanned into N-Sides |
    | Carved Rounded Slot, *n-gon* | 96v/36f, **91 open edges** | **48v/28f, 0 open edges** |

    Every other object is identical under all three, and *Both* and *Topology*
    give the same result on **every** object in **both** modes — three values, two
    outcomes, and each mode already ships with the right one. If a `.blend` saved
    before this was hidden still carries a non-default, the settings tab says so
    and offers a **Reset Corner Detection** button.

### Too many corners

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
a fact the mesh states outright, and a gentle chamfer's junction barely bends, so
ranking it would drop the very thing the topological test exists to catch.

Sides shorter than *Small Side Tolerance* are then merged into their neighbour,
which is what keeps a two-triangle sliver from counting as a side of its own.

### Too few corners

A single closed curve — a disc, a bore rim — has no corners by either test, so it
is one side, and no generator accepts one. Four corners are synthesised, but
**where** they go is read off the shape rather than spread evenly: turn is
measured over a *window* of the perimeter, because a tessellated rounded end is
dozens of individually insignificant turns and one real feature.

However many features it finds decides the generator: **two ends make a Wedge**,
three a Triangle, four a Quad. Only a boundary whose turn is genuinely uniform —
a circle — falls back to four points spread by arc length.

That matters most on a long strip curving back on itself (a rounded slot, a bore
wall, a ribbon around a feature). Its perimeter is dominated by its two long
sides, so evenly spaced quarter points land in the *middle* of them, and the
"quad" handed to the fill is half a long side plus half an end — which comes out
as a fan.

One corner is worse than none, so a boundary that yields exactly one is topped up
to four, *anchored on the real corner* — the one feature the face has lands on a
side boundary rather than mid-side.

Rings never get synthesised corners: a cornerless rim gives them no trouble, and
inventing four on each of two loops would pair their points across a shear
instead of straight across the band.

## The side count picks the generator

<figure class="diagram" markdown="0">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 280" role="img" aria-label="The six generators and the shapes they produce">
  <g fill="none" stroke="#2980b9" stroke-width="1.5">
    <g transform="translate(20,10)">
      <rect x="6" y="30" width="88" height="30" fill="#eef5fb"/>
      <path d="M28 30V60M50 30V60M72 30V60M6 45H94"/>
      <g fill="#e6473d" stroke="none"><circle cx="6" cy="45" r="4"/><circle cx="94" cy="45" r="4"/></g>
    </g>
    <g transform="translate(160,10)">
      <path d="M10 78L50 12L90 78Z" fill="#eef5fb"/>
      <path d="M30 45L50 52M70 45L50 52M50 78L50 52"/>
      <g fill="#e6473d" stroke="none"><circle cx="10" cy="78" r="4"/><circle cx="50" cy="12" r="4"/><circle cx="90" cy="78" r="4"/></g>
    </g>
    <g transform="translate(300,10)">
      <rect x="12" y="14" width="76" height="64" fill="#eef5fb"/>
      <path d="M31 14V78M50 14V78M69 14V78M12 35H88M12 56H88"/>
      <g fill="#e6473d" stroke="none"><circle cx="12" cy="14" r="4"/><circle cx="88" cy="14" r="4"/><circle cx="88" cy="78" r="4"/><circle cx="12" cy="78" r="4"/></g>
    </g>
  </g>

  <g font-family="sans-serif" font-size="12" fill="#14405c" text-anchor="middle">
    <text x="70" y="104">Wedge — 2 sides</text>
    <text x="210" y="104">Triangle — 3</text>
    <text x="350" y="104">Quad — 4</text>
  </g>

  <g fill="none" stroke="#2980b9" stroke-width="1.5">
    <g transform="translate(20,130)">
      <path d="M50 7L86 33L72 76L28 76L14 33Z" fill="#eef5fb"/>
      <path d="M68 20L50 45M79 55L50 45M50 76L50 45M21 55L50 45M32 20L50 45"/>
      <circle cx="50" cy="45" r="3" fill="#8e44ad" stroke="none"/>
      <g fill="#e6473d" stroke="none"><circle cx="50" cy="7" r="4"/><circle cx="86" cy="33" r="4"/><circle cx="72" cy="76" r="4"/><circle cx="28" cy="76" r="4"/><circle cx="14" cy="33" r="4"/></g>
    </g>
    <g transform="translate(160,130)">
      <circle cx="50" cy="45" r="38" fill="#eef5fb"/>
      <circle cx="50" cy="45" r="18" fill="#ffffff"/>
      <path d="M88 45H68M76.9 71.9L62.7 57.7M50 83V63M23.1 71.9L37.3 57.7M12 45H32M23.1 18.1L37.3 32.3M50 7V27M76.9 18.1L62.7 32.3"/>
    </g>
    <g transform="translate(300,130)">
      <path d="M25 14H75L90 45L75 76H25L10 45Z" fill="#eef5fb"/>
      <g fill="#e6473d" stroke="none"><circle cx="25" cy="14" r="3"/><circle cx="75" cy="14" r="3"/><circle cx="90" cy="45" r="3"/><circle cx="75" cy="76" r="3"/><circle cx="25" cy="76" r="3"/><circle cx="10" cy="45" r="3"/></g>
    </g>
  </g>

  <g font-family="sans-serif" font-size="12" fill="#14405c" text-anchor="middle">
    <text x="70" y="224">N-Side — 5+</text>
    <text x="210" y="224">Ring — 2 loops</text>
    <text x="350" y="224">N-gon — a mode</text>
  </g>

  <g font-family="sans-serif" font-size="11" fill="#666">
    <text x="20" y="252">Red dots are corners. The N-Side pole's valence is the side count, not the</text>
    <text x="20" y="268">span; the Ring's rungs run straight across the band, one per point of each rim.</text>
  </g>
</svg>
</figure>

| Sides | Generator | What it makes |
|---|---|---|
| 2 | **Wedge** | a grid running along a strip: two ends, two long sides |
| 3 | **Triangle** | a three-way Coons fill |
| 4 | **Quad** | a Coons grid, `Span U` × `Span V` |
| 5+ | **N-Side** | one Coons sub-patch per side around a central pole |
| — | **Ring** | *two boundary loops*: a band of quads across the gap |
| — | **N-gon** | one face following the boundary, for flat patches |

The first two rows of that table are the ones that make the corner method matter:
the count is looked up in order, and specialised generators are tried before the
N-Side fallback.

The last two are **not** chosen by a side count, and that is where the order of
the decisions shows:

1. **Is it committed already?** A patch in the result mesh comes back as whatever
   it was built as — same rule as its spans. Hovering finished work must show
   what is there, not what the current mode would build.
2. **Does the mode ask for an n-gon?** <kbd>N</kbd>, or a patch committed as one.
3. **Can it take one?** Two hard blockers: a patch that is not flat (a bevel
   would get a flat lid over it), and more than one hole (the two-edge bridge can
   only handle one). The panel names the blocker rather than the key doing
   nothing.
4. **Does it have two boundary loops?** Then it is a Ring candidate — but two
   loops is not the same thing as a band. A 200×100 plate with a 5 mm hole is an
   annulus too, and a Ring has to give both loops the same point count. So the
   gap between the loops is checked for evenness; a non-band that is flat is
   filled as an n-gon instead, and the panel says why. See
   [Faces with a hole](../guide/rings.md).
5. **Otherwise the side count decides.**

More than two loops is not handled: only the outer loop is used, and the panel
warns rather than silently paving over the holes.

## What a generator actually does

Every generator except the n-gon builds a grid by **Coons interpolation** between
its sides — the surface implied by the four (or three, or two) boundary curves —
and then **reprojects the interior onto the original CAD surface** through a BVH
built from that patch's own triangles.

<figure class="diagram" markdown="0">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 190" role="img" aria-label="A Coons grid between the sides, and its interior reprojected onto the surface">
  <g font-family="sans-serif" font-size="11" fill="#555">
    <text x="10" y="18">the grid the sides imply</text>
    <text x="300" y="18">seen edge-on</text>
  </g>

  <g transform="translate(20,36)">
    <path d="M0 12C40 0 90 0 130 12" fill="none" stroke="#27ae60" stroke-width="2.5"/>
    <path d="M130 12C142 40 142 76 130 104" fill="none" stroke="#27ae60" stroke-width="2.5"/>
    <path d="M130 104C90 116 40 116 0 104" fill="none" stroke="#27ae60" stroke-width="2.5"/>
    <path d="M0 104C-12 76 -12 40 0 12" fill="none" stroke="#27ae60" stroke-width="2.5"/>
    <g fill="none" stroke="#7fa8c4" stroke-width="1">
      <path d="M32.5 5C36 40 36 76 32.5 111"/>
      <path d="M65 2C67 40 67 76 65 114"/>
      <path d="M97.5 5C95 40 95 76 97.5 111"/>
      <path d="M-4 35C40 27 90 27 134 35"/>
      <path d="M-6 58C40 52 90 52 136 58"/>
      <path d="M-4 81C40 89 90 89 134 81"/>
    </g>
    <g fill="#e6473d"><circle cx="0" cy="12" r="4"/><circle cx="130" cy="12" r="4"/><circle cx="130" cy="104" r="4"/><circle cx="0" cy="104" r="4"/></g>
  </g>

  <g transform="translate(310,50)">
    <path d="M0 60Q100 0 200 60" fill="none" stroke="#2c3e50" stroke-width="2"/>
    <path d="M0 60H200" fill="none" stroke="#b9c4cc" stroke-width="1" stroke-dasharray="4 3"/>
    <g stroke="#8e44ad" stroke-width="1.2">
      <path d="M40 58V43"/><path d="M80 58V33"/><path d="M120 58V33"/><path d="M160 58V43"/>
    </g>
    <g fill="#8e44ad">
      <circle cx="40" cy="40.8" r="3.5"/><circle cx="80" cy="31.2" r="3.5"/>
      <circle cx="120" cy="31.2" r="3.5"/><circle cx="160" cy="40.8" r="3.5"/>
    </g>
    <g fill="#e6473d"><circle cx="0" cy="60" r="4"/><circle cx="200" cy="60" r="4"/></g>
    <text x="0" y="92" font-family="sans-serif" font-size="10" fill="#666">interpolation puts interior points on the chord;</text>
    <text x="0" y="106" font-family="sans-serif" font-size="10" fill="#666">reprojection puts them back on the surface</text>
  </g>
</svg>
</figure>

Two consequences worth holding on to:

- **Boundary rows are left exactly where the loops put them.** They are samples
  of the real CAD boundary, and a neighbour welds to them — moving them would
  break the weld. (The one exception is a ring rim that had to be phase-aligned:
  it lands nowhere near a source vertex by construction, so it is reprojected
  like the interior.)
- **Deviation is an interior question.** Interior vertices are on the surface by
  construction, so measuring a patch's accuracy at its vertices reads ~0 on every
  shape and proves nothing. The benchmark measures across face *interiors*.

## Where the spans come from

The generator is chosen; how many segments it puts along each direction is
settled separately, and **the order is fixed** because each step exists to
survive the one before it:

1. **The generator's own default**, computed from the patch's edge lengths.
2. **The resolution preset** scales that (Very Low ¼ … Extreme ×4).
3. **Propagation** from an already-committed neighbour, keyed by the pair of
   corner ids the shared side runs between. Scaling *this* by the preset would
   break the weld it exists to make.
4. **The spans the patch was committed with**, if it is being re-edited. These
   beat both of the above, or re-opening a patch would silently re-shape work you
   had already tuned.
5. **Anything you typed or scrolled** for this patch.
6. **The winning matches** — see the next step. A pin always decides the span; an
   automatic match only seeds it the first time, so scrolling a span on a side
   that happens to border a committed neighbour is not silently undone.

Never below 1 segment. An N-Side is a special case here: its sides do not share
one span, so the allocation is solved across the whole ring of sides at once, and
whatever cannot be fitted is refused rather than approximated.

[Next: matching a neighbour →](matching.md)
