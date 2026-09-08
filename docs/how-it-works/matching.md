# 3. Matching a neighbour

Two patches weld only if their shared boundary carries the **same vertices**. Not
the same count — the same points. Matching is the machinery that makes that
happen, and it runs on every regeneration, between choosing the generator and
building the grid.

This page is the mechanism. [Matching a neighbour](../guide/matching.md) in the
Guide is the part you drive.

## Why a count is not enough

<figure class="diagram" markdown="0">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 620 234" role="img" aria-label="Copying a neighbour's segment count leaves an offset; copying its vertices does not">
  <g font-family="sans-serif" font-size="11" fill="#555">
    <text x="20" y="18">same count, resampled evenly</text>
    <text x="260" y="18">the neighbour&#39;s own vertices</text>
  </g>

  <g transform="translate(110,36)">
    <rect x="-90" y="0" width="86" height="130" fill="#dce9f5"/>
    <rect x="4" y="0" width="86" height="130" fill="#fdf0ee"/>
    <text x="-78" y="150" font-family="sans-serif" font-size="10" fill="#666">committed</text>
    <text x="16" y="150" font-family="sans-serif" font-size="10" fill="#666">the new patch</text>
    <g fill="#3ddc84"><circle cx="-4" cy="0" r="4"/><circle cx="-4" cy="22" r="4"/><circle cx="-4" cy="50" r="4"/><circle cx="-4" cy="88" r="4"/><circle cx="-4" cy="130" r="4"/></g>
    <g fill="#e6473d"><circle cx="4" cy="0" r="4"/><circle cx="4" cy="32.5" r="4"/><circle cx="4" cy="65" r="4"/><circle cx="4" cy="97.5" r="4"/><circle cx="4" cy="130" r="4"/></g>
    <g stroke="#e6473d" stroke-width="1" stroke-dasharray="3 2">
      <path d="M-4 22H4V32.5"/><path d="M-4 50H4V65"/><path d="M-4 88H4V97.5"/>
    </g>
    <text x="-90" y="172" font-family="sans-serif" font-size="10" fill="#a03028">five points either side, three of them nowhere</text>
    <text x="-90" y="186" font-family="sans-serif" font-size="10" fill="#a03028">near each other — the boundary cracks</text>
  </g>

  <g transform="translate(350,36)">
    <rect x="-90" y="0" width="86" height="130" fill="#dce9f5"/>
    <rect x="4" y="0" width="86" height="130" fill="#eef7f0"/>
    <text x="-78" y="150" font-family="sans-serif" font-size="10" fill="#666">committed</text>
    <text x="16" y="150" font-family="sans-serif" font-size="10" fill="#666">the new patch</text>
    <g fill="#3ddc84">
      <circle cx="-4" cy="0" r="4"/><circle cx="-4" cy="22" r="4"/><circle cx="-4" cy="50" r="4"/><circle cx="-4" cy="88" r="4"/><circle cx="-4" cy="130" r="4"/>
      <circle cx="4" cy="0" r="4"/><circle cx="4" cy="22" r="4"/><circle cx="4" cy="50" r="4"/><circle cx="4" cy="88" r="4"/><circle cx="4" cy="130" r="4"/>
    </g>
    <text x="-90" y="172" font-family="sans-serif" font-size="10" fill="#1f7a4a">the side is handed the points themselves,</text>
    <text x="-90" y="186" font-family="sans-serif" font-size="10" fill="#1f7a4a">so the weld is exact whatever their spacing</text>
  </g>
</svg>
</figure>

A neighbour committed as an n-gon put its points where the boundary *curves*, not
at even spacing; a matched side has to reproduce that. So a match copies the
neighbour's own committed vertices, and the side's polyline is **replaced** by
them before the generator ever sees it.

What makes that cheap is one property of the resampler: asked for exactly as many
points as it was given, it returns them untouched. So every generator — Quad,
Triangle, Wedge, N-Side, Ring, N-gon, **none of them modified** — reproduces a
matched side exactly, as long as it puts `len - 1` segments along it.

## The five steps

Matching is not one operation. In order, on every regeneration:

**1. Build the side references.** One per side, holding: which committed patches
are across it, which of their vertices this side could take, whether it is
pinned, and — if it cannot be matched — the reason why. This is what the overlay
draws and the tooltip reads; nothing here changes any geometry yet.

**2. Collect the winners.** A grid has one span per *direction*, so two sides can
drive the same count. One winner per span key: a pin beats an automatic match,
then the denser one wins. The rest are reported as outvoted.

**3. Settle the spans.** The winning matches feed into the span resolution from
[step 2](generators.md#where-the-spans-come-from), a pin deciding outright and an
automatic match only seeding.

**4. Apply.** Each winning side's polyline is swapped for the neighbour's points.

**5. Re-check.** Any match the *resolved* span can no longer reproduce is
dropped. That is what makes scrolling a span release a match instead of being
silently overwritten by it on the next frame.

The split between 3 and 5 is the whole reason matching feels responsive: a match
both drives a span and depends on it, so the spans have to be settled before any
side is rewritten, and the matches re-checked after.

## Which vertices a side is even allowed to see

This used to be pure proximity — one pool of every committed vertex in the result
mesh, keep whatever falls inside the tolerance — and proximity cannot tell "the
patch across this edge" from "a patch that happens to run close by". A face
stacked a fraction above another, a thin wall, two sheets meeting at a shallow
angle: all of them put committed vertices well inside a side's reach without
touching it, and the side came back tracing a loop through its neighbourhood.

Three filters, in order:

- **Only the faces the side borders.** Step 1 recorded the Plasticity face across
  every boundary segment, so a side's pool is the committed vertices of *those*
  patches and nothing else. A side is matched against **every** face it borders,
  not just the majority one — a side straddles two committed patches whenever the
  boundary between them falls mid-side. Untracked retopology, predating patch
  ids, belongs to no named face and stays in every pool.
- **Not the rival sides.** A candidate nearer to one of this patch's *other*
  sides belongs to that one. This is what settles a band's two rims.
- **Not the neighbour's second row.** A committed patch is a grid, so there is
  another row of its vertices one cell behind the shared one, and on a narrow
  band that row is well inside a pinned side's reach. It is cut off by a **gap**:
  within one row the distances vary smoothly — that variation *is* the drift the
  margin exists to reach — so a step larger than anything the row has varied by
  so far is a different row.

And the patch being generated is excluded from its own pool, by face id rather
than by "the active patch": a committed patch is generated *before* being
recorded as active, so a re-edit used to match itself and come back with whatever
spans reproduced what was already there.

## How far a match reaches

Two answers, for two different questions:

| | Reach | Used by |
|---|---|---|
| **Strict** | float slack — both patches usually resample the same polyline, so the real distance is about zero | automatic matching, which fires without being asked and must never take something that merely happens to be nearby |
| **With margin** | plus *Match Margin* (2% by default) | a side you **pointed at** — that says which neighbour you mean, so it may reach one that has drifted |

Both are a share of the **patch's longest side**, not of the side being matched.
A neighbour's drift is an absolute distance; scaling by the side made a short
side's reach vanish, so a stub between two retopped faces refused while the long
side beside it matched without trouble.

A third distance, kept separate on purpose: how close two vertices have to be to
be *the same vertex* when de-duplicating a match. That is always the strict one.
Using the margin there merged a neighbour's own consecutive vertices on a ring —
61 points came back as 31, and the side was asked for half the count it should
have had.

## When two sides collide

<figure class="diagram" markdown="0">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 200" role="img" aria-label="Two opposite sides of a quad driving the same span">
  <g transform="translate(150,30)">
    <rect x="0" y="0" width="150" height="120" fill="#eef5fb"/>
    <g stroke="#7fa8c4" stroke-width="1">
      <path d="M0 20H150M0 40H150M0 60H150M0 80H150M0 100H150"/>
      <path d="M50 0V120M100 0V120"/>
    </g>
    <path d="M0 0V120" stroke="#3ddc84" stroke-width="4" fill="none"/>
    <path d="M150 0V120" stroke="#e6473d" stroke-width="4" fill="none"/>
    <g fill="#e6473d"><circle cx="0" cy="0" r="4"/><circle cx="150" cy="0" r="4"/><circle cx="150" cy="120" r="4"/><circle cx="0" cy="120" r="4"/></g>
  </g>

  <g font-family="sans-serif" font-size="11">
    <text x="10" y="80" fill="#1f7a4a">matched: 6</text>
    <text x="10" y="96" fill="#666">it drives Span V</text>
    <text x="320" y="80" fill="#a03028">wanted 4</text>
    <text x="320" y="96" fill="#666">outvoted — this edge</text>
    <text x="320" y="112" fill="#666">will crack</text>
    <text x="150" y="176" fill="#555">One count runs the whole direction, so only one of the two</text>
    <text x="150" y="192" fill="#555">can be honoured. The loser keeps the boundary the CAD drew.</text>
  </g>
</svg>
</figure>

The loser is **not** resampled to the winner's count. It keeps the boundary the
CAD drew, because a match returning a count nobody asked for is a crack that
looks like a weld. The panel reports how many sides were outvoted, and the side
draws **red**: there is a committed patch across it that is not being matched,
which is exactly where a crack ends up.

Two refinements on that rule:

- **A tie is not a conflict.** If both sides want the same number, both are
  handed their own neighbour's vertices — they agree on the count, not on where
  the points are.
- **An N-Side does not have one span at all.** Each side is bounded by the spokes
  of its two *neighbours*, so several sides of one patch can be matched at once,
  and the allocation is solved over the whole ring. A **Ring** keys its two rims
  separately, so they no longer knock each other out.

## Sides nothing agrees on

Two cases where the corners themselves are the obstacle, both handled here rather
than by widening a tolerance:

**A neighbour covering only part of a side.** A bore's rim is one long cornerless
side and the patch beside it may touch an eighth of it. Matching a *count* over a
partial cover lands between the neighbour's vertices everywhere except by luck.
So the shared stretch takes the neighbour's vertices exactly and the remainder is
filled at that neighbour's own spacing along the side's own curve — the shared
part welds, the rest borders nothing. Offered only on a side you **click**: how
to divide the rest of a side is a decision, not something to do to every side of
every patch a hover passes over.

**A corner nothing agrees on.** Nothing on a disc's boundary is a corner, so four
are synthesised at the quarter points of its arc length — and those are arbitrary
in the strongest sense. The ring committed around it has its own vertices at its
own phase, so the quarter points fall *between* them, and whether each side finds
a committed vertex at its corner is a coin toss. Such a loop is **re-cut**: the
boundary is matched once, as the closed side it really is, and the sides are
carved out of the neighbour's own ring of points, so every corner lands on one at
distance zero. The side *count* is kept, so the generator choice does not change.
On the fixture's two cones that took 140 and 200 open boundary edges to zero.

[Next: committing →](commit.md)
