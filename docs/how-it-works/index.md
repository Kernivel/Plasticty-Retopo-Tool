# How it works

This section follows one patch from the moment you hover a surface to the moment
its quads land in `<Source>_Retop`. It is the reference for *why* the addon did
what it did — which is what you need before changing a span, a corner threshold
or a match and expecting a particular result.

The [Guide](../guide/matching.md) says what to press. This says what happens
when you press it.

## The whole pipeline

<figure class="diagram" markdown="0">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 570" role="img" aria-label="The generation pipeline, from hovering a surface to committing it">
  <defs>
    <marker id="hwArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0 0 L10 5 L0 10 z" fill="#2980b9"/>
    </marker>
  </defs>

  <rect x="112" y="20"  width="8" height="182" fill="#2980b9"/>
  <rect x="112" y="224" width="8" height="46"  fill="#8e44ad"/>
  <rect x="112" y="292" width="8" height="114" fill="#27ae60"/>
  <rect x="112" y="428" width="8" height="114" fill="#c0762a"/>
  <text transform="translate(100,111) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#2980b9">1. The patch</text>
  <text transform="translate(100,247) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#8e44ad">2. Generator</text>
  <text transform="translate(100,349) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#27ae60">3. Matching</text>
  <text transform="translate(100,485) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#c0762a">4. Commit</text>

  <g font-family="sans-serif">
    <rect x="140" y="20" width="470" height="46" rx="6" fill="#f2f7fb" stroke="#2980b9"/>
    <text x="158" y="40" font-size="13" fill="#14405c">Hover a surface</text>
    <text x="158" y="57" font-size="11" fill="#555">a ray through the mesh returns one polygon, and the polygon names a face id</text>

    <rect x="140" y="88" width="470" height="46" rx="6" fill="#f2f7fb" stroke="#2980b9"/>
    <text x="158" y="108" font-size="13" fill="#14405c">Identify the patch</text>
    <text x="158" y="125" font-size="11" fill="#555">every triangle with that id, its welded border, its boundary loops, its neighbours</text>

    <rect x="140" y="156" width="470" height="46" rx="6" fill="#f2f7fb" stroke="#2980b9"/>
    <text x="158" y="176" font-size="13" fill="#14405c">Split the boundary into sides</text>
    <text x="158" y="193" font-size="11" fill="#555">corners from the angle test and the topological test, then ranked and merged</text>

    <rect x="140" y="224" width="470" height="46" rx="6" fill="#f7f2fb" stroke="#8e44ad"/>
    <text x="158" y="244" font-size="13" fill="#4a2060">Choose the generator</text>
    <text x="158" y="261" font-size="11" fill="#555">two loops go to Ring, N-gon mode to N-gon, otherwise the side count decides</text>

    <rect x="140" y="292" width="470" height="46" rx="6" fill="#f2faf4" stroke="#27ae60"/>
    <text x="158" y="312" font-size="13" fill="#14512f">Look at the committed neighbours</text>
    <text x="158" y="329" font-size="11" fill="#555">one side reference per side: which patch is across it, and which of its vertices</text>

    <rect x="140" y="360" width="470" height="46" rx="6" fill="#f2faf4" stroke="#27ae60"/>
    <text x="158" y="380" font-size="13" fill="#14512f">Settle the spans, then substitute the matched sides</text>
    <text x="158" y="397" font-size="11" fill="#555">resolution, propagation, stored spans, winning matches — then apply, then re-check</text>

    <rect x="140" y="428" width="470" height="46" rx="6" fill="#fdf6ee" stroke="#c0762a"/>
    <text x="158" y="448" font-size="13" fill="#6b3d0c">Generate the preview</text>
    <text x="158" y="465" font-size="11" fill="#555">a Coons grid between the sides, interior reprojected onto the CAD surface</text>

    <rect x="140" y="496" width="470" height="46" rx="6" fill="#fdf6ee" stroke="#c0762a"/>
    <text x="158" y="516" font-size="13" fill="#6b3d0c">Commit</text>
    <text x="158" y="533" font-size="11" fill="#555">weld into &lt;Source&gt;_Retop, tag every face with the patch, register its spans</text>
  </g>

  <g stroke="#2980b9" stroke-width="1.5" marker-end="url(#hwArrow)">
    <line x1="375" y1="66"  x2="375" y2="84"/>
    <line x1="375" y1="134" x2="375" y2="152"/>
    <line x1="375" y1="202" x2="375" y2="220"/>
    <line x1="375" y1="270" x2="375" y2="288"/>
    <line x1="375" y1="338" x2="375" y2="356"/>
    <line x1="375" y1="406" x2="375" y2="424"/>
    <line x1="375" y1="474" x2="375" y2="492"/>
  </g>
</svg>
<figcaption>Steps 1 to 7 run again on <em>every</em> change — a hover, a scrolled span, a
clicked side. Only the last one writes anything permanent.</figcaption>
</figure>

## What re-runs, and when

Everything above the commit is recomputed from scratch each time the preview is
rebuilt: hovering a patch, scrolling <kbd>Ctrl</kbd>+wheel, typing a span,
clicking a side, toggling <kbd>N</kbd>. Nothing about a patch is stored between
two regenerations except the things you explicitly set — the spans, the pinned
sides, the mode.

What *is* cached is the layer underneath: one parse of the source mesh, keyed by
its contents. Patches, boundary loops, the weld map and the neighbour tables are
computed once and shared by every hover, every overlay and every match query
until a vertex actually moves. Without it a hover would re-walk the whole mesh —
about 85 ms a frame on a 16k-triangle part, against 0.5 ms cached.

## The four steps

| | |
|---|---|
| [**1. Identifying a patch**](patches.md) | how a triangle soup becomes patches, borders, neighbours and corners |
| [**2. Choosing a generator**](generators.md) | how the sides pick a generator, and what each one builds |
| [**3. Matching a neighbour**](matching.md) | how a side is handed a committed patch's own vertices |
| [**4. Committing**](commit.md) | how the preview is welded in, and what is recorded for later |
