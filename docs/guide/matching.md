# Matching a neighbour

Matching is this plugin way to speed up the process of retopologizing a patch.
When the plugin detects an already committed neighbour, it will try to create and merge vertices to match the adjacent surface.

This works for both spans and N-gons in both directions.
For N-gons it will put vertices following the boundary.

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
