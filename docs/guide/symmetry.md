# Symmetry

<kbd>Alt</kbd>+<kbd>X</kbd>, then <kbd>X</kbd>, <kbd>Y</kbd> or <kbd>Z</kbd>.

The retopology is mirrored across that axis of the **source object's** origin.
Press the same axis again to turn it off; the three are cumulative. The
**Output** tab shows which are on and lets you click them directly.

The prompt cancels on anything that is not an axis — an armed prompt nobody can
get out of is worse than one that gives up easily.

!!! note "Why Alt+X and not Alt+Z"

    <kbd>Alt</kbd>+<kbd>X</kbd> is the Hard Ops reflex, which is why the retopo
    x-ray moved to <kbd>Shift</kbd>+<kbd>X</kbd>.
    <kbd>Alt</kbd>+<kbd>Z</kbd> is Blender's own viewport X-ray, and taking over
    a Blender binding costs more than it gives.

## It is a modifier, not geometry

A **Mirror modifier** on `<Object>_Retop`, and that is not merely
non-destructiveness.

Every piece of bookkeeping here reads the result mesh's *base* data — commit,
re-edit, neighbour matching, shading, face adoption — so a modifier is invisible
to all of it by construction. Baked mirror faces would carry the same patch ids
as the originals, and re-editing one patch would then delete **both** halves and
rebuild only one, tearing a hole in the mirrored side that nothing would put
back.

The flip side: **the mirrored half is not real.** You cannot pick a patch on it,
re-edit it, or match a side against it. Retop one half; the other follows.

The plane is the source object's origin rather than the result object's.
Plasticity drops every import at the world origin so the two coincide today, but
that is a fact about the current bridge, and the source object is what "the
object" means to you.

Which axes are on lives **on the modifier**, not in scene state: they belong to
one object, and two objects retopped in the same file have no reason to agree.
Only *how* the mirror behaves is a scene preference.

| Setting | Default | |
|---|---|---|
| **Clip at the Plane** | on | stops a vertex being dragged across the centre line while hand-editing, and holds the ones already on it there |
| **Mirror Merge Distance** | 0.001 | closes the seam down the middle |

## Applying it

When the retopology is done, use the panel's **Apply Mirror** button rather than
the modifier dropdown.

A mirrored face copies the patch id of the face it came from, and re-editing that
patch would then delete both halves. The button leaves the copies **untracked**
instead — unclaimed faces are never deleted — and entering the object again hands
each copy to the Plasticity face it actually sits on. On a symmetric part that is
the real face on the other side, so the mirrored half becomes patches you can
re-edit like any other.

!!! warning "Only correct because the part is symmetric"

    Mirror a patch out over *empty space* and there is no face there to claim the
    copies: they join the patch they were copied from, and a later re-edit of
    that patch takes them along. That is mirroring something that is not
    symmetric — a user error the rule degrades on, rather than a case it defends
    against.

The copies are told from the originals by **face centre**, not by index: the
originals come through the apply untouched so their centres match exactly, while
assuming Blender appends the mirrored half is an ordering detail that could
change under you.
