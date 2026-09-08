# 4. Committing

Everything up to here was a preview: one object, rewritten from scratch on every
change, holding one patch. Committing is the only step that writes anything
permanent.

## Where it goes

Committed geometry is written into a second object named **`<Source>_Retop`**,
filed under a `Retop` collection that mirrors the Inbox hierarchy the bridge
built.

!!! warning "The name is the link"

    Everything resolves through `<Source>_Retop`. Rename or re-import the CAD
    object and its retopology becomes unreachable — a session on the new name
    starts a *second* result mesh that overlaps the first. The panel says so
    rather than letting it look like a broken re-edit.

The commit reads the preview's **base** mesh. The offset that keeps the preview
and the result off the CAD surface is a Displace modifier, never baked, so what
lands in the result mesh sits exactly on the surface.

## The weld

<figure class="diagram" markdown="0">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 210" role="img" aria-label="Corners welded by identity, boundary points by proximity">
  <g transform="translate(150,25)">
    <rect x="-130" y="0" width="130" height="120" fill="#dce9f5"/>
    <rect x="6" y="0" width="130" height="120" fill="#e2f1d8"/>
    <g stroke="#7fa8c4" stroke-width="1" fill="none">
      <path d="M-130 30H0M-130 60H0M-130 90H0M-87 0V120M-43 0V120"/>
      <path d="M6 24H136M6 48H136M6 72H136M6 96H136M50 0V120M92 0V120"/>
    </g>
    <path d="M0 0V120M6 0V120" stroke="#2c3e50" stroke-width="1.5" fill="none"/>
    <g fill="#e6473d"><circle cx="0" cy="0" r="5"/><circle cx="6" cy="0" r="5"/><circle cx="0" cy="120" r="5"/><circle cx="6" cy="120" r="5"/></g>
    <g fill="#3ddc84">
      <circle cx="0" cy="30" r="4"/><circle cx="0" cy="60" r="4"/><circle cx="0" cy="90" r="4"/>
      <circle cx="6" cy="24" r="4"/><circle cx="6" cy="48" r="4"/><circle cx="6" cy="72" r="4"/><circle cx="6" cy="96" r="4"/>
    </g>
  </g>

  <g font-family="sans-serif" font-size="11">
    <text x="300" y="40" fill="#a03028">corners — welded by identity</text>
    <text x="300" y="56" fill="#666">both patches name the same source vertex</text>
    <text x="300" y="90" fill="#1f7a4a">everything else — welded by proximity</text>
    <text x="300" y="106" fill="#666">only among boundary points, within</text>
    <text x="300" y="122" fill="#666">Boundary Weld Distance</text>
    <text x="10" y="180" fill="#555">Unmatched here: the two sides carry different counts, so the green</text>
    <text x="10" y="196" fill="#555">points do not pair up and the border stays open. That is a crack.</text>
  </g>
</svg>
</figure>

- **Corners weld by identity.** They are untouched source vertices, so each one
  carries the index of the vertex it came from and both patches name the same
  one. That is exact, and it is why a match that *moves* a corner has to give up
  its identity: leaving the name on a point that has moved would make a later
  patch reuse a vertex that is no longer there.
- **Everything else welds by proximity**, and only among vertices flagged as
  boundary, at *Boundary Weld Distance*. An unscoped merge would silently pull
  unrelated points together and drop faces.

Which is the whole reason [step 3](matching.md) exists: proximity only closes a
border if the two patches put their points in the same places.

## What is recorded

Three things, and each buys back a capability later:

| Recorded | What it enables |
|---|---|
| **A patch id on every committed face** | re-editing: click the patch again and its faces are found and removed |
| **The patch's spans and its generator** | re-opening it with the spans it was built with, and <kbd>Ctrl</kbd>+click to copy a density between patches built by the same generator |
| **The span of each side, keyed by its two corner ids** | propagation: the next patch along that shared boundary starts at a count that welds |

Then the result mesh is re-shaded. Every face is smooth, and an edge is marked
sharp only when its two faces carry **different patch ids** and their normals
differ by more than *Sharp Edge Angle*. One patch is one CAD surface, so an
angle-based auto-sharpen would crease a curved patch's own low-span interior
instead. It is re-run after *every* commit, not just the first: sharpness belongs
to the border *between* patches, so a new neighbour changes the shading of an
edge that already existed.

## Re-editing, and the removal that comes first

<figure class="diagram" markdown="0">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 620 200" role="img" aria-label="The re-edit cycle: pick, remove and snapshot, adjust, then commit or restore">
  <defs>
    <marker id="hwArrow2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0 0 L10 5 L0 10 z" fill="#2980b9"/>
    </marker>
  </defs>
  <g font-family="sans-serif">
    <rect x="10" y="60" width="130" height="52" rx="6" fill="#f2f7fb" stroke="#2980b9"/>
    <text x="75" y="82" font-size="12" fill="#14405c" text-anchor="middle">click a committed</text>
    <text x="75" y="98" font-size="12" fill="#14405c" text-anchor="middle">patch</text>

    <rect x="180" y="60" width="150" height="52" rx="6" fill="#fdf6ee" stroke="#c0762a"/>
    <text x="255" y="82" font-size="12" fill="#6b3d0c" text-anchor="middle">its faces are removed,</text>
    <text x="255" y="98" font-size="12" fill="#6b3d0c" text-anchor="middle">the mesh snapshotted</text>

    <rect x="370" y="10" width="140" height="52" rx="6" fill="#f2faf4" stroke="#27ae60"/>
    <text x="440" y="32" font-size="12" fill="#14512f" text-anchor="middle">commit</text>
    <text x="440" y="48" font-size="11" fill="#555" text-anchor="middle">snapshot dropped</text>

    <rect x="370" y="110" width="140" height="52" rx="6" fill="#fdf0ee" stroke="#e6473d"/>
    <text x="440" y="132" font-size="12" fill="#7a2018" text-anchor="middle">discard / Esc / undo</text>
    <text x="440" y="148" font-size="11" fill="#555" text-anchor="middle">snapshot restored</text>

    <g stroke="#2980b9" stroke-width="1.5" fill="none" marker-end="url(#hwArrow2)">
      <path d="M140 86H176"/>
      <path d="M330 80L366 44"/>
      <path d="M330 92L366 128"/>
    </g>
    <text x="10" y="182" font-size="11" fill="#555">Removing on pick, not on commit, is deliberate: the patch visibly disappears, so a failure to</text>
    <text x="10" y="196" font-size="11" fill="#555">identify it shows up at once instead of becoming two overlapping surfaces after the commit.</text>
  </g>
</svg>
</figure>

The removal takes faces only, so vertices a neighbour still uses survive and the
new grid welds back onto them. Every exit that is not a commit — Discard,
<kbd>Esc</kbd>, leaving the object, ending the session, an addon reload — puts the
snapshot back.

<kbd>X</kbd> (**delete patch**) falls straight out of this: the faces are already
out, so deleting is dropping the snapshot with nothing committed in its place.
The span registry is deliberately left alone — its entries describe a shared
boundary whose other side is still committed.

**Retopology committed before face tracking existed** is claimed on entry: each
untagged face is classified onto the source patch it sits on, by nearest source
polygon, voting with the face centre and its vertices. On anything short of a
strict majority the face stays unclaimed — and unclaimed faces are never deleted,
so a misread degrades to a duplicate rather than to a hole in a neighbour. The
same pass repairs faces created by hand in Edit Mode, which is why
[hand-editing](../guide/hand-editing.md) goes through <kbd>Tab</kbd> rather than
straight into Blender.

## One undo step per patch

Commit, delete and a discard that restored something each push their own undo
step. Without that, the nearest step below a mid-session state was *"enter
&lt;object&gt;"*, so a single <kbd>Ctrl</kbd>+<kbd>Z</kbd> rolled the whole
session back and every committed patch went at once. <kbd>Ctrl</kbd>+<kbd>Z</kbd>
is deliberately not one of the session's own keys: it is passed straight through
to Blender, and those steps are what make it mean *take the last patch back*.

## After the commit

The side colours only exist while a patch is open, but a crack outlives the
session that made it — and the patch that ends up cracked is usually the one you
did **not** touch. **Cracked borders** is the standing version of that warning: a
CAD edge with a committed patch on **both** sides that the result mesh leaves
open along it, dashed in red.

Both halves of that rule matter. An open border with only one side committed is
the frontier of the work, which every part has and none of which is a defect;
painting those would make the report meaningless. And detection reads the
source's B-rep edges rather than proximity between result vertices — the same
reason a side may only match the faces it borders.
