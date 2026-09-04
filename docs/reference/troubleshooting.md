# Troubleshooting

## "I deployed and nothing changed"

**Check the version string in the System tab first, before anything else.**

Blender caches Python modules, so a fresh copy on disk is not a fresh copy in
memory — and a deploy that never ran looks exactly like a feature that does not
work. The panel compares what Python is running against what `version.py` reads
on disk and prints the mismatch in red.

While that mismatch stands, **every traceback cites line numbers that do not
match the file you are reading**. Fix it first.

- Use **Reload Addon Only**, not Blender's global *Reload Scripts* — the latter
  can half-fail silently when another installed addon errors during its own
  reload.
- If the version string still does not move, the deploy went to a different
  Blender. `python scripts/deploy.py --list` shows every addons folder it found.

## "No Plasticity face data"

The mesh was not imported through the bridge, so it carries no face ids and there
is nothing to divide into patches.

If you clicked `<Something>_Retop`, that is not a failure: the session resolves
it back to `Something`, and the panel offers that as a button.

## The patch does not match the face Plasticity draws

Two CAD faces meeting along an edge do **not** always tessellate it the same way.
The finer side drops vertices in the middle of the coarser side's segments — a
T-junction along the border — and the border then does not pair up vertex for
vertex.

It is not rare: on one real exported object, 2327 of 4857 boundary segments came
back unpaired that way.

The addon falls back to resolving those by geometry, and the fallback runs *only*
on the segments the exact pairing missed, so a cleanly tessellated mesh pays
nothing. If a patch still dices strangely:

- **check how far from the origin the part is.** The vertex weld uses an absolute
  tolerance in the mesh's local units. On a part whose coordinates run to a few
  hundred units, the float32 ulp is already the same order, so two faces'
  independently rounded copies of a shared vertex can miss each other — which
  shows up as a phantom patch border, hence wrong corners, wrong side count,
  wrong generator. **Suspect this before anything else.**
- turn the [CAD edge overlay](../guide/cad-structure.md) on (<kbd>E</kbd>) and
  look at whether the border is drawn as one edge or as a string of unrelated
  segments.

## A patch reads as five or seven boundary loops

Same family of problem. A weld that reached across a real edge collapses a
triangle, and the patch's boundary then no longer decomposes into closed cycles —
what comes back is an **open chain handed out as a loop**, which draws a chord
across a face the model never divided.

The weld epsilon is capped by the mesh's own shortest edge for exactly this
reason, and only loops that actually closed are returned. If you still see it,
it is worth reporting with the file.

## A crack along a shared edge

The two patches have different vertices on that boundary. In order of likelihood:

1. **The neighbour's span was changed after it was committed.** Already-committed
   neighbours keep their own spans; re-edit the neighbour to match.
2. **The match was outvoted.** A grid has one span per direction; the panel
   reports how many sides lost. Pin the side you care about — a pin beats an
   automatic match.
3. **The match reached the wrong row.** Turn the side highlight on
   (<kbd>M</kbd>) and hover the side: the overlay draws the actual vertices the
   match would take.
4. **Nothing worked.** [Hand-edit it](../guide/hand-editing.md) —
   <kbd>Tab</kbd>, drag the vertex onto its twin, auto-merge closes it.

## The retopology is inside out

Blender's face-orientation overlay shows it in red. This was a real bug in ring
patches with a matched hole; it is asserted against on every fixture shape now.
If you hit it, please report the file.

## A committed patch cannot be re-edited

The panel names the result mesh this session writes to, with its face and patch
count, while you are picking surfaces. If it says it could not find the faces to
remove, the retopology you can see does **not** belong to that mesh — committing
would leave the old surface overlapping the new one.

Usually that means the source object was renamed or re-imported, so a session on
the new name started a *second* result mesh. Everything resolves through
`<Source>_Retop`, and the panel flags an orphan result object rather than letting
it look like a broken re-edit.

## The panel is dead / the session eats my clicks

The session should pass through everything outside the 3D view's viewport region
— including the N-panel, which floats *on top* of the viewport region with
Blender's default Region Overlap.

If you can reproduce a panel field that will not take a keystroke while a session
runs, that is a bug worth reporting; it has come back more than once.

## The session will not start

- **You are in Edit Mode.** The panel says which mode to leave.
- **`session_active` is set with no modal listening** — a reload or a crashed
  modal. The panel detects it and offers a reset.

## Ctrl+Z went too far

One step is one patch, but the session's own entry is a step too, so pressing
past the last committed patch ends the session.
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> puts everything back, and you can
start a new session on the same object and carry on.

## Reporting a bug

Include:

- the **version and build string** from the System tab (and whether the red
  stale-load line was showing);
- your **Blender version**;
- the `.blend`, or the object, if you can share it;
- what the panel said — the generator name, the side count, the loop count, and
  any warning.
