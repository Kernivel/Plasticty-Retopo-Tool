"""Which vertices a patch's side has to reproduce, and where they come from.

Two patches only weld along a shared boundary if they land on the *same
vertices*, not merely on the same count -- a neighbour committed as an n-gon
put its points where the boundary curves, and a grid resampling evenly to that
same count lands between them every time. So a side takes the neighbour's own
committed vertices, and the generator is told the count that reproduces them
(`geometry.resample_polyline_by_arclength` hands a polyline straight back when
asked for exactly as many points as it holds, so no generator needed changing).

Three things decide what a side may take:

- **what it borders.** A side can only match the Plasticity faces actually
  across it, which the mesh states per boundary segment. Proximity alone cannot
  tell those from a patch that merely passes nearby, and matching used to be
  proximity alone -- which is how a side ended up following a run of vertices
  tracing a loop through its neighbourhood instead of the edge it shares.
- **who asked.** An automatic match takes only an exact answer. A pin -- you
  pointed at the side, so you have said which neighbour you mean -- may reach
  one that has drifted, by `match_margin`.
- **whether the spans still allow it.** A grid has one count per *direction*,
  so two sides wanting different counts along one axis cannot both be honoured,
  and a count the user typed since releases the match rather than being
  overruled by it.

Kept out of `operators` for the same reason `patchprep` is, plus one more: the
overlay draws what a match would take, and a draw handler must never be able to
reach the operators module.
"""
import json
from typing import TYPE_CHECKING

from . import constants
from . import generators
from . import mesh_build

if TYPE_CHECKING:
    import bpy
    import mathutils

    from . import patchprep
    from . import state as state_mod

# A committed patch's boundary vertices, keyed by the face id owning them --
# what `mesh_build.committed_boundary_map` hands back.
CommittedMap = dict[int, "list[mathutils.Vector]"]
# One winning match per span key: the side, the points it takes, whether pinned.
Winners = dict[str, "tuple[SideReference, list[mathutils.Vector], bool]"]


class SideReference:
    """One side of the active patch, ready to be pointed at in the viewport.

    `span` is what the neighbour across this side put along it, or None when
    there is nothing to match -- that's the difference between a side the
    picker offers and one it greys out.
    """

    __slots__ = ("index", "loop", "in_loop", "points", "match_points",
                 "neighbours", "reason", "strict_points", "source_points",
                 "match_world", "source_world")

    def __init__(
        self,
        index: int,
        loop: int,
        in_loop: int,
        points: "list[mathutils.Vector]",
        match_points: "list[mathutils.Vector] | None",
        neighbours: list[int] | None,
        reason: str = "",
        strict_points: "list[mathutils.Vector] | None" = None,
        source_points: "list[mathutils.Vector] | None" = None,
        match_world: "list[mathutils.Vector] | None" = None,
        source_world: "list[mathutils.Vector] | None" = None,
    ) -> None:
        # The same two point sets in world space, for the overlay to draw.
        # Kept here rather than transformed at draw time: a draw handler runs on
        # every redraw and has no business recomputing what generation knew.
        self.match_world = match_world or []
        self.source_world = source_world or []
        # Why this side can't be matched, when it can't -- an opaque refusal on
        # a side that visibly touches retopology is impossible to act on.
        self.reason = reason
        # What the *automatic* matching is allowed to take: found without the
        # picker's margin, so it never reaches for something merely nearby.
        # `match_points` is the generous answer, for a side you pointed at.
        self.strict_points = strict_points
        self.index = index      # flat index across every loop, in order
        self.loop = loop        # which boundary loop it belongs to
        self.in_loop = in_loop  # its index within that loop
        self.points = points    # world space, for drawing and hit-testing
        # The neighbour's own committed vertices along this side, in the source
        # object's local space -- the thing that actually gets matched. None
        # when there is nothing to match, or when the neighbour covers only
        # part of the side.
        self.match_points = match_points
        # The CAD boundary's own vertices along this side, thinned by curvature
        # (the same rule N-gon mode follows). Always available: the source mesh
        # is there whether or not anything has been committed yet, which is what
        # lets a side be pinned to the *original* topology rather than to a
        # neighbour -- a first patch has no committed neighbour to match, but it
        # still has the tessellation Plasticity chose.
        self.source_points = source_points or []
        # Every Plasticity face across this side, most-covering first. The
        # match is confined to these; see _side_neighbours.
        self.neighbours = list(neighbours or [])

    @property
    def neighbour(self) -> int | None:
        """The face the picker names -- the one covering most of the side."""
        return self.neighbours[0] if self.neighbours else None

    @property
    def available(self) -> bool:
        return self.match_points is not None

    @property
    def span(self) -> int | None:
        """Segments the neighbour put along this side."""
        return len(self.match_points) - 1 if self.match_points else None

    @property
    def source_span(self) -> int:
        """Segments the CAD tessellation puts along this side."""
        return max(1, len(self.source_points) - 1)


# Rebuilt every time a patch is generated, dropped by a reload. The overlay and
# the modal both read it; nothing persists it, because it holds Vectors and
# describes a preview that only exists while the session runs.
_active_sides: list[SideReference] = []


def active_sides() -> list[SideReference]:
    return _active_sides


def build_side_references(
    context: "bpy.types.Context",
    obj: "bpy.types.Object",
    prepared: "patchprep.PreparedPatch",
    face_id: int | None = None,
) -> list[SideReference]:
    """The active patch's sides, with the geometry each of them could match.

    Walks every loop, so a ring or a holed n-gon offers its hole's sides too --
    those border committed neighbours just as much as the outer ones do.

    Each side is matched **only against the patches it actually borders**
    (`SideReference.neighbours`). Matching used to run against every committed
    vertex in the result mesh and keep whatever fell within the tolerance, which
    is how a short side ended up following a loop around its neighbourhood
    instead of the edge it shares: proximity alone cannot tell "the patch across
    this edge" from "a patch that happens to pass nearby". The mesh already says
    which is which, per boundary segment.
    """
    global _active_sides

    state = context.scene.plasticity_retop
    matrix = obj.matrix_world
    # The patch being *generated*, which is not the same thing as the one the
    # scene currently calls active: picking a committed patch generates it
    # before recording it as active, so reading the active id here left the
    # patch's own committed geometry in its own pool and it matched itself --
    # a re-edit came back with whatever spans reproduced what was already there
    # instead of the ones it was committed with.
    if face_id is None:
        face_id = state.active_face_id
    # Grouped once for the whole patch: this walks the result mesh, and doing it
    # per side made a hover cost that times the side count.
    committed = mesh_build.committed_boundary_map(obj)

    # One reach for the whole patch, from its longest side. A neighbour's drift
    # is an absolute distance, so a per-side share of the margin left a short
    # side unable to see what the long side beside it matched without trouble.
    reference_length = max(
        (sum((b - a).length for a, b in zip(side, side[1:]))
         for loop_sides in prepared.loops_sides for side in loop_sides),
        default=0.0)

    references = []
    index = 0
    for loop_i, loop_sides in enumerate(prepared.loops_sides):
        neighbours_of_side = (prepared.loops_neighbours[loop_i]
                              if loop_i < len(prepared.loops_neighbours) else [])
        for side_i, side in enumerate(loop_sides):
            neighbours = (neighbours_of_side[side_i]
                          if side_i < len(neighbours_of_side) else [])
            pool = _match_pool(committed, neighbours, face_id)

            source_points = generators.ngon.side_points(side, state.ngon_angle)
            match_points, reason = mesh_build.match_side_to_points(
                pool, side, mesh_build.side_match_tolerance(
                    state, side, margin=True, reference_length=reference_length))
            strict_points, _strict_reason = mesh_build.match_side_to_points(
                pool, side, mesh_build.side_match_tolerance(
                    state, side, reference_length=reference_length))
            if not pool:
                reason = _empty_pool_reason(neighbours, committed, face_id)
            references.append(SideReference(
                index=index, loop=loop_i, in_loop=side_i,
                points=[matrix @ point for point in side],
                match_points=match_points,
                neighbours=neighbours,
                reason=reason,
                strict_points=strict_points,
                source_points=source_points,
                match_world=[matrix @ point for point in (match_points or ())],
                source_world=[matrix @ point for point in source_points],
            ))
            index += 1

    _active_sides = references
    return references


def _empty_pool_reason(
    neighbours: list[int], committed: CommittedMap, active_face_id: int | None
) -> str:
    """Why a side had nothing to look at -- which is not the same as having
    looked and found nothing. "No neighbour" on a side that plainly runs
    against a finished patch is the refusal nobody can act on.
    """
    others = [face_id for face_id in neighbours if face_id != active_face_id]
    if not others:
        return "nothing borders this side"
    if len(others) == 1:
        return f"patch {others[0]} isn't retopologized yet"
    return "none of this side's neighbours is retopologized yet"


def _match_pool(
    committed: CommittedMap, neighbours: list[int], active_face_id: int | None
) -> "list[mathutils.Vector]":
    """The committed vertices a side is allowed to match.

    Strictly the Plasticity faces across this side, plus any untracked
    retopology. Nothing else, ever -- and *nothing at all* when none of those
    faces has been committed yet, rather than falling back to the rest of the
    result mesh. Proximity cannot tell "the patch across this edge" from "a
    patch that happens to run close by", which is how a side used to collect a
    vertex run tracing a loop through its neighbourhood: a thin wall, a face
    stacked a fraction above another, two sheets meeting at a shallow angle all
    put committed vertices well inside the tolerance of a side they do not
    touch. The mesh already says, per boundary segment, which face is across.

    Untracked retopology (`NO_PATCH`) is the one thing that cannot be checked
    that way -- it predates patch ids and belongs to no named face -- so it
    stays available to every side. That is also the only case a mesh with no
    patch data at all can produce.
    """
    if not committed:
        return []

    wanted = [face_id for face_id in neighbours
              if face_id in committed and face_id != active_face_id]
    if mesh_build.NO_PATCH in committed:
        wanted.append(mesh_build.NO_PATCH)

    return mesh_build.flatten_boundary_points(committed, wanted, active_face_id)


def clear_side_references() -> None:
    global _active_sides
    _active_sides = []


# What a manual pin on a side means. Stored rather than the segment count it
# resolves to: the count is recomputed from live geometry every regeneration,
# so keeping a stale copy of it could only ever disagree.
PIN_NEIGHBOUR = "N"  # follow the committed patch across this side
PIN_SOURCE = "S"     # follow the CAD tessellation of this side itself
PIN_KINDS = (PIN_NEIGHBOUR, PIN_SOURCE)


def side_override_map(state: "state_mod.RetopPatchState") -> dict[int, str]:
    """The manual per-side pins, as {flat index: PIN_*}."""
    if not state.side_overrides:
        return {}
    try:
        stored = json.loads(state.side_overrides)
    except ValueError:
        return {}

    pins = {}
    for key, value in stored.items():
        # Older sessions stored the resolved segment count here; anything
        # numeric means "follow the neighbour", which is all it ever meant.
        kind = value if value in PIN_KINDS else (
            PIN_NEIGHBOUR if isinstance(value, int) and value >= 1 else None)
        if kind is not None:
            pins[int(key)] = kind
    return pins


def store_side_overrides(
    state: "state_mod.RetopPatchState", overrides: dict[int, str]
) -> None:
    state.side_overrides = json.dumps({str(k): v for k, v in overrides.items()}) if overrides else ""


def span_key_for(generator_name: str, reference: SideReference) -> str:
    """Which span a match on this side drives.

    A grid has one count per *direction*, not per side: pinning a quad's bottom
    side pins its top one too, because they are the same span. Sides that share
    an answer are exactly the sides that collide, which is what the key is for.
    An n-gon has no spans at all -- every side carries its own segment count --
    so each gets a key of its own and nothing ever collides.
    """
    if generator_name == constants.NGON:
        return f"side:{reference.index}"
    if generator_name == constants.QUAD:
        return "span_u" if reference.in_loop % 2 == 0 else "span_v"
    if generator_name in constants.TWO_SPAN_GENERATORS:
        return "span_u"
    return "span"


def _match_candidates(
    state: "state_mod.RetopPatchState", references: list[SideReference]
) -> "list[tuple[SideReference, list[mathutils.Vector], bool]]":
    """Every side that wants to be matched, with the points it would take.

    A pin uses the picker's generous margin -- pointing at a side is saying
    which neighbour you mean, so it may reach one that has drifted. Automatic
    matching only ever takes the exact answer, or it would reach for whatever
    happens to be nearby on sides nobody asked about.
    """
    pins = side_override_map(state)
    automatic = state.auto_match_neighbours

    candidates = []
    for reference in references:
        kind = pins.get(reference.index)
        if kind == PIN_SOURCE:
            points = reference.source_points
        elif kind == PIN_NEIGHBOUR:
            points = reference.match_points
        elif automatic and reference.available:
            points = reference.strict_points
        else:
            continue
        if points and len(points) >= 2:
            candidates.append((reference, points, kind is not None))
    return candidates


def _winning_matches(
    candidates: "list[tuple[SideReference, list[mathutils.Vector], bool]]",
    generator_name: str,
) -> tuple[Winners, list[SideReference]]:
    """One match per span, since a grid cannot honour two counts in one
    direction.

    Two sides driving the same span used to both get substituted and the second
    one silently win the count, which left the loser's points resampled to a
    number that was not theirs -- the exact "the spans agree but the vertices
    don't" crack the matching exists to close. Only the winner is substituted
    now; the rest keep their own polyline and are told about it.

    A pin beats an automatic match, because it was asked for. Between two of a
    kind the denser one wins: it is the one that would lose the most detail.
    """
    best = {}
    losers = []
    for reference, points, pinned in candidates:
        key = span_key_for(generator_name, reference)
        rank = (1 if pinned else 0, len(points), -reference.index)
        current = best.get(key)
        if current is None or rank > current[0]:
            if current is not None:
                losers.append(current[1])
            best[key] = (rank, reference, points, pinned)
        else:
            losers.append(reference)
    return ({key: (reference, points, pinned)
             for key, (_rank, reference, points, pinned) in best.items()},
            losers)


def collect_side_matches(
    context: "bpy.types.Context", generator_name: str
) -> tuple[Winners, list[SideReference]]:
    """({span key: (side, points, pinned)}, [sides that lost a collision]).

    Everything the caller needs to decide spans *before* any side is rewritten:
    which sides want to be matched, what they would take, and which of them
    were outvoted because a grid cannot honour two counts in one direction.
    """
    state = context.scene.plasticity_retop
    return _winning_matches(
        _match_candidates(state, active_sides()), generator_name)


def _honours(
    key: str, points: "list[mathutils.Vector]", spans: dict[str, int] | None
) -> bool:
    """Whether the resolved spans still let this match reproduce its points.

    A substituted side only comes back vertex for vertex if the generator asks
    for exactly as many points as it was handed. Once the span driving that
    side says otherwise -- because the user typed one, or because the opposite
    side won the direction -- substituting would hand the generator a polyline
    it is about to resample anyway, moving the very vertices the match existed
    to land on. Better to leave the side as the CAD drew it and let the count
    the user asked for mean what it says.
    """
    if spans is None or key.startswith("side:"):
        return True  # n-gon sides carry their own count; nothing to disagree with
    return spans.get(key) == len(points) - 1


def apply_side_matches(
    context: "bpy.types.Context",
    obj: "bpy.types.Object",
    prepared: "patchprep.PreparedPatch",
    generator_name: str,
    spans: dict[str, int] | None = None,
    winners: Winners | None = None,
) -> tuple[dict[int, int], list[int]]:
    """Replace each matched side's polyline with the vertices it must reproduce.

    Nothing downstream needs to know: every generator resamples a side with
    `geometry.resample_polyline_by_arclength`, which hands a polyline straight
    back when asked for exactly as many points as it holds. So a matched side is
    reproduced vertex for vertex as long as the generator puts len-1 segments
    along it -- which is what the returned counts are for.

    `spans` is the finally-resolved {span key: count}; a match the spans no
    longer honour is skipped (see `_honours`). Given None, every match is taken,
    which is what a caller that has no spans to resolve wants.

    Returns ({flat side index: segments}, [sides that lost a collision]).
    """
    state = context.scene.plasticity_retop
    if winners is None:
        winners, losers = collect_side_matches(context, generator_name)
    else:
        losers = []

    counts = {}
    for key, (reference, points, _pinned) in winners.items():
        if not _honours(key, points, spans):
            continue
        original = prepared.loops_sides[reference.loop][reference.in_loop]
        prepared.loops_sides[reference.loop][reference.in_loop] = points
        counts[reference.index] = len(points) - 1

        # If the match moved this side's first point, the corner is no longer
        # the source vertex it is named after -- and a corner welds *by
        # identity*, so leaving the name on it would make a later patch reuse
        # a vertex that has since moved, or drag this one onto it. Blank it and
        # let that point weld by proximity like every other boundary point.
        # Only a cornerless loop can get here: a real corner is a B-rep vertex
        # the neighbour shares, so its match starts exactly on it.
        tolerance = mesh_build.side_match_tolerance(state, original)
        if (points[0] - original[0]).length > tolerance:
            corner_ids = prepared.loops_corner_ids[reference.loop]
            if reference.in_loop < len(corner_ids):
                corner_ids[reference.in_loop] = mesh_build.NO_SOURCE

    return counts, [reference.index for reference in losers]


def ngon_side_segments(
    prepared: "patchprep.PreparedPatch", matched_counts: dict[int, int]
) -> list[dict[int, int]]:
    """The matched counts, regrouped per loop the way the n-gon wants them."""
    per_loop = []
    index = 0
    for loop_i in range(len(prepared.loops_sides)):
        forced = {}
        for side_i in range(len(prepared.loops_sides[loop_i])):
            if index in matched_counts:
                forced[side_i] = matched_counts[index]
            index += 1
        per_loop.append(forced)
    return per_loop
