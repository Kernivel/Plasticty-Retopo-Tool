# Matching a neighbour

Matching is this plugin way to speed up the process of retopologizing a patch.
When the plugin detects an already committed neighbour, it will try to create and merge vertices to match the adjacent surface.

This works for both spans and N-gons in both directions.
For N-gons it will put vertices following the boundary.

This page is the part you drive. For what happens underneath — the pool a side
is allowed to see, the order the spans and the matches are resolved in — see
[How it works: matching a neighbour](../how-it-works/matching.md).

<video autoplay loop muted playsinline poster="../../assets/img/matching-crack.jpg">
  <source src="../../assets/video/matching-crack.webm" type="video/webm">
</video>

**Match Committed Neighbours** is on by default and applies to *every*
generator.


## Pointing at a side

Press <kbd>M</kbd> to toggle the side highlight (it is a preference, so it
survives between patches and sessions). Every side of the patch is drawn on the
surface:

Matching is binary — a side reproduces the patch across it, or it does not — so
the colours answer that one question:

| | |
|---|---|
| <span class="side-swatch" style="background:#3ddc84"></span> **Green** | matched: the preview is reproducing the neighbour's vertices |
| <span class="side-swatch" style="background:#e6473d"></span> **Red** | there **is** a committed patch across this side and it is not being matched |
| <span class="side-swatch" style="background:#8a8a8a"></span> **Grey** | nothing committed across it yet: normal, nothing to fix |
| **Brighter** | under the cursor |

**Click a side** to match it to the committed neighbour across it. **Click a
matched side again** to turn the match off — which turns it red, because that
is what releasing it leaves behind. A side with nothing across it cannot be
matched at all, and the click is refused.

The overlay also draws **which vertices the match would take** — green dots on
the hovered side's candidates and on every pinned side's

<video autoplay loop muted playsinline poster="../../assets/img/matching-side-colours.jpg">
  <source src="../../assets/video/matching-side-colours.webm" type="video/webm">
</video>

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

Proximity cannot tell "the patch across this edge" from "a
patch that happens to run close by" — a face stacked a fraction above another, a
thin wall, two sheets meeting at a shallow angle all put committed vertices well
inside a side's reach without touching it, and the side comes back tracing a loop
through its neighbourhood instead of the edge it shares.

The mesh already records which face is across each boundary segment, so a side is
matched **only** against the patches it genuinely borders.


## A grid cannot honour two counts in one direction

A quad grid has one span per *direction*. Two sides wanting different counts
along the same axis cannot both be honoured, so:

1. a manual **match** beats an automatic match;
2. then the **denser** one wins;
3. only the winner's vertices are substituted — the loser keeps the boundary the
   CAD drew, rather than a resampled version of someone else's.

The panel reports how many sides were outvoted.


## Changing a span releases a match

Changing the span means the spans count and the neighbour's count are no longer
equal. During adjustment, it is preferable to have the matching automatically
release the match to allow the user to tweak the spanning on the current patch.

## A neighbour that covers only part of a side

A bore's rim is one long cornerless side; the patch beside it may touch a
fraction of it. A chamfer runs the length of a face that has been retopped in
three pieces. In both, the neighbour is real and the arc they share is
perfectly matchable — there is simply more side than neighbour.

**Click the side and it is matched over the stretch the neighbour covers**, and
filled in at that neighbour's own spacing over the rest, along the side's own
curve. The shared stretch lands on the neighbour's vertices exactly and welds;
the remainder borders nothing, so it is free.

!!! note "Why not just copy the count"

    Because a count lands *between* the neighbour's vertices everywhere except
    by luck — the half-cell offset the coverage rule exists to prevent. Taking
    the vertices where the neighbour is, and choosing the rest, has no offset
    to leave.

Two things it does not do. An **open** side keeps its own endpoints exactly:
those are the patch's corners and they weld to their neighbours by *identity*,
so a match is not free to move them. And it is only offered on a side you
**click** — automatic matching keeps the strict answer, as it does with the
margin, because how to divide the rest of a side is a decision rather than
something to do to every side of every patch you hover past.

## Copying a patch's density

Matching and propagation both work across a *shared boundary*: two patches that
touch have to agree or they crack. Two patches that never meet are a different
question, and nothing in the mesh can answer it — a ring here and a ring there
that you want at the same density.

<kbd>Ctrl</kbd>+**click** finished retopology while adjusting a patch, and the
patch takes the spans that one was committed with. Commit a ring at U=1, V=12,
start the next one, Ctrl+click the first: the new one is U=1, V=12.

It works because the **generator** each patch was built by is recorded at
commit alongside its spans. That is also what limits it: the copy is refused
between patches built by different generators, and says so. A Ring's two counts
mean *around* and *across*, a Quad's mean its own U and V, an N-Side's single
one means segments per side — the same number means something different in
each, so carrying it over would be carrying a number rather than a density.

**Click the same patch again and U and V come over exchanged.** Between two
Quads the two directions are each patch's own — which one is U comes from where
its boundary walk started, not from anything you can see — so a copy lands
rotated about half the time and nothing in either patch can say in advance
which half. The second click is that answer, and a third puts it back: one
gesture, two states, the same shape as clicking a matched side to release it.

The tooltip follows, showing the spans **the way the next click would apply
them**, so it previews the click rather than describing the record.

Between two Rings there is no ambiguity to resolve — around is around — and a
generator with a single span has nothing to exchange, which it says rather than
quietly doing nothing. Which patch you copied from is remembered per patch, so
starting another one begins unswapped.

Move the cursor over finished retopology and **the patch outlines in amber**,
with a tooltip saying what a click would take — `U=7, V=3`. If its generator
does not match, the outline is dimmed and the tooltip says so rather than the
patch simply not lighting up: a target that refuses and a target that is not
there look the same otherwise.

An n-gon has no spans to copy; its density is its detail angle.

## After the commit: cracked borders

The side colours only exist while a patch is open. Match two patches, commit
both, then re-open one and change its span: the match is released — that is what
changing the count means — and the patch you did **not** touch is left with a
seam down the side it shares. Nothing about it changed, and until now nothing
said anything.

**Cracked borders** is the standing version of that warning. Any CAD edge with a
committed patch on both sides that the retopology failed to close is dashed in
red.

<video autoplay loop muted playsinline poster="../../assets/img/cracked-borders.jpg">
  <source src="../../assets/video/cracked-borders.webm" type="video/webm">
</video>

## Reasons

Every refusal carries a reason, shown in the click warning, in the tooltip by the
cursor, and in the panel. The common ones:

| Reason | What it means |
|---|---|
| *no committed neighbour* | the face across this side has not been retopped yet |
| *one point only* | this side is shorter than the neighbour's vertex spacing, so there is nothing to follow |
| *does not cover the side* | the neighbour touches only part of it — matching a count there **is** the half-cell offset |
| *outvoted* | another side won the span this one drives |
