# Matching a neighbour

Two patches only weld if their shared boundary carries the **same vertices** —
not merely the same count.

That distinction is the whole feature, and it is invisible until you look at the
vertices. A neighbour committed as an [n-gon](ngon.md) put its points where the
boundary *curves*, not at even spacing; a grid resampling evenly to the same
count lands between them every time. So a matched side is handed the neighbour's
own committed vertices, and the generator is told the count that reproduces them.

<!-- media: 12s split. Left: a shared edge with counts equal but points offset,
     zoomed on the crack. Right: the same edge matched, points coincident. -->

## It happens by itself

**Match Committed Neighbours** is on by default, and applies to *every*
generator. Retop one face, then the one next door, and their shared boundary is
already welded.

Automatic matching only ever takes an **exact** answer — it fires without being
asked, so it must never reach for something that merely happens to be nearby.

## Pointing at a side

Press <kbd>M</kbd> to toggle the side highlight (it is a preference, so it
survives between patches and sessions). Every side of the patch is drawn on the
surface:

| | |
|---|---|
| <span class="side-swatch" style="background:#3ddc84"></span> **Green** | this side is being matched, and the preview is reproducing it |
| <span class="side-swatch" style="background:#f0a500"></span> **Amber** | this side is following its own CAD edge |
| <span class="side-swatch" style="background:#8a8a8a"></span> **Grey** | neither |
| **Brighter** | under the cursor |

!!! note "Green means *is being* matched, not *could be*"

    Those are different answers. A side that lost a span collision, or whose span
    you typed over since, is not green — it says so in the tooltip by the cursor
    instead.

**Click a side** to pin it to the committed neighbour across it.
**<kbd>Ctrl</kbd>+click** pins it to its own CAD tessellation instead.
**Click a matched side again** to turn the match off.

The overlay also draws **which vertices the match would take** — dots on the
hovered side's candidates and on every pinned side's, green from a neighbour and
amber from the CAD edge. Knowing a side *can* be matched is only half of it; a
match going to the wrong neighbour or stopping short is invisible from a coloured
line lying on the boundary.

<!-- media: 15s. Hover along the sides of one patch so each colour and its
     tooltip appears, then click one and Ctrl+click another. -->

## Three kinds of pin

| | Gesture | Follows |
|---|---|---|
| **Neighbour** | click | the committed patch across the side |
| **Source** | <kbd>Ctrl</kbd>+click | the side's own CAD tessellation, thinned by curvature |
| **Excluded** | click a matched side | nothing — leave this side alone |

**Source** needs no neighbour at all, so it works on the very first patch of a
model and on any side facing nothing yet.

**Excluded** exists because with automatic matching on — the default — releasing
the *pin* is invisible: the automatic pass would put the match straight back on
the next regeneration and the side would stay green, so the click read as broken.
It is a plain two-state toggle instead.

A pin stores the *kind*, not the count. The count is recomputed from live
geometry every regeneration, so a stored copy could only disagree.

## How far a match reaches

Two different answers, for two different questions.

**Automatic matching** uses float slack. Both patches usually resample the same
polyline, so the real distance is about zero.

**A side you pointed at** gets the **Match Margin** on top (2% by default).
Pointing at a side says *which* neighbour you mean, so it may reach one that has
drifted — a coarse neighbour whose chords sag off a curved boundary, or two CAD
edges tessellated slightly differently.

Both are a share of the **patch's longest side**, not of the side being matched.
A neighbour's drift is an absolute distance; scaling by the side made a short
side's reach vanish, so a stub between two retopped faces refused while the long
side beside it matched without trouble.

## A side may only match the faces it actually borders

This is not proximity. Proximity cannot tell "the patch across this edge" from "a
patch that happens to run close by" — a face stacked a fraction above another, a
thin wall, two sheets meeting at a shallow angle all put committed vertices well
inside a side's reach without touching it, and the side comes back tracing a loop
through its neighbourhood instead of the edge it shares.

The mesh already records which face is across each boundary segment, so a side is
matched **only** against the patches it genuinely borders — and against *all* of
them, since a boundary between two committed patches often falls mid-side.

When a side's neighbours are named but none of them is committed yet, the pool is
**empty** rather than falling back to the rest of the mesh, and the panel names
the patch it is waiting for.

## A grid cannot honour two counts in one direction

A quad grid has one span per *direction*. Two sides wanting different counts
along the same axis cannot both be honoured, so:

1. a **pin** beats an automatic match;
2. then the **denser** one wins;
3. only the winner's vertices are substituted — the loser keeps the boundary the
   CAD drew, rather than a resampled version of someone else's.

The panel reports how many sides were outvoted.

!!! tip "Not every generator collides"

    An n-gon gets a key per side and a [ring](rings.md) one per *loop*, so
    neither collides with itself. An [N-Side](generators.md#the-n-side-patch)
    solves its spoke allocation, so several of its sides can be matched at once.

## Changing a span releases a match

Spans are resolved *before* any side is rewritten, and a match the resolved span
can no longer reproduce is then dropped.

That split is what makes the span control work at all: without it, scrolling the
span on a side bordering a committed neighbour did nothing — the match put its
own count straight back every regeneration and the control looked broken.

**Changing the count away from the neighbour's is how you say "don't weld here".**
A pin is immune, because you asked for it.

## Reasons

Every refusal carries a reason, shown in the click warning, in the tooltip by the
cursor, and in the panel. The common ones:

| Reason | What it means |
|---|---|
| *no committed neighbour* | the face across this side has not been retopped yet |
| *one point only* | this side is shorter than the neighbour's vertex spacing, so there is nothing to follow |
| *does not cover the side* | the neighbour touches only part of it — matching a count there **is** the half-cell offset |
| *outvoted* | another side won the span this one drives |
