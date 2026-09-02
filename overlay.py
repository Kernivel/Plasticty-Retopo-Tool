"""Viewport overlays drawn while a retop session is running: the bottom-right
keybind hints (mirroring how Plasticity shows its own modal keybinds), the
N-gon vertex dots, the side highlight, and the CAD structure of the source
surface (see cad_display).

Two separate draw handlers, because they draw in different spaces: the hints
and every kind of dot are 2D (POST_PIXEL), the lines are in the scene
(POST_VIEW).

Both are read-only by construction. A draw handler that created a datablock
would crash the next Ctrl+Z -- see the note in mesh_build. Everything expensive
they show is computed and cached elsewhere for the same reason: a redraw is not
a place to walk a mesh.
"""
import math
from typing import TYPE_CHECKING

import blf
import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader

# Safe to import: all three are loaded before this module (see __init__.py) and
# none imports it back. operators is the one that can't be reached from here.
from . import cad_display
from . import constants
from . import keymap
from . import mesh_build
from . import sidematch

if TYPE_CHECKING:
    # Annotations only: the overlay runs inside a draw handler and must never
    # widen what it pulls in at import time.
    import mathutils

    from . import state as state_mod

_handle: object | None = None
_points_handle: object | None = None

# --- N-gon vertex dots ---
#
# A span grid shows its own topology: the preview's quads *are* the spans. An
# n-gon is one face, so its boundary vertices are invisible -- and they are the
# only thing there is to judge in that mode (is the chamfer picked up? is the
# curve dense enough?). Hence dots, and only in n-gon mode.
VERT_COLOR = (1.0, 0.85, 0.2, 1.0)
VERT_OUTLINE_COLOR = (0.05, 0.05, 0.05, 0.9)
VERT_SIZE = 11.0          # fallback when the scene property isn't there yet
VERT_OUTLINE_RATIO = 1.45  # dark disc behind the bright one

# Drawn as screen-space geometry rather than GL points. `gpu.state.point_size_set`
# is a no-op whenever the backend runs with program point size enabled -- the
# shader has to write gl_PointSize then, and the builtin UNIFORM_COLOR one does
# not -- which came out as 1px dots that ignored the size setting entirely. A
# fan of triangles per dot always honours the pixels asked for.
#
# A fan rather than the two triangles it started as: a square dot reads as a
# handle you can grab, which none of these are -- they mark where a vertex is.
# Twelve segments is where a dot this size stops looking like a polygon, and it
# is divisible by four so the disc still measures exactly 2*half across, which
# is what keeps the size setting checkable.
DOT_SEGMENTS = 12

# --- side reference picker (M in ADJUST) ---
#
# Three states, because the useful question is not "where are the sides" but
# "which of them can I actually match": one that borders a committed neighbour,
# one that doesn't, and the one under the cursor.
# Hover brightens a side's *own* colour instead of replacing it: a single
# hover colour hid the one thing worth knowing before clicking -- whether this
# side can be matched at all -- and turned a refusal into a surprise.
# Four states, not three, and the fourth is the one that was missing: a side
# that *is* being matched right now. "Could be matched" and "is reproducing the
# neighbour's vertices" used to draw the same green, so a side that had lost a
# span collision, or whose span the user had typed since, looked exactly like
# one the preview was welding to -- which is most of why the feature read as
# arbitrary. Green now means matched; a side that could be but isn't is grey,
# like one with nothing to match, and the tooltip tells the two apart.
SIDE_MATCHED_COLOR = (0.25, 0.95, 0.45, 0.95)
SIDE_MATCHED_HOVER_COLOR = (0.60, 1.0, 0.75, 1.0)
SIDE_SOURCE_COLOR = (1.0, 0.72, 0.25, 0.95)        # matched to its own CAD edge
SIDE_SOURCE_HOVER_COLOR = (1.0, 0.85, 0.55, 1.0)
SIDE_AVAILABLE_COLOR = (0.55, 0.60, 0.58, 0.55)    # could be matched, isn't
SIDE_AVAILABLE_HOVER_COLOR = (0.55, 1.0, 0.70, 1.0)  # green: clicking will match
SIDE_BLOCKED_COLOR = (0.42, 0.42, 0.45, 0.45)
SIDE_BLOCKED_HOVER_COLOR = (0.75, 0.40, 0.35, 0.95)  # red: clicking will refuse
SIDE_WIDTH = 3.0
SIDE_MATCHED_WIDTH = 4.5
SIDE_HOVER_WIDTH = 6.0

# --- the tooltip on the hovered side ---
#
# Colour alone cannot say *why* a side is grey, and the panel is the wrong
# place to read it: the pointer is already on the side, in the viewport, about
# to click. Two lines by the cursor -- what the side is doing, and why.
TOOLTIP_BG = (0.10, 0.10, 0.11, 0.90)
TOOLTIP_TEXT = (0.95, 0.95, 0.95, 1.0)
TOOLTIP_DETAIL = (0.72, 0.74, 0.76, 1.0)
TOOLTIP_MATCHED = (0.45, 1.0, 0.60, 1.0)
TOOLTIP_PAD = 8
TOOLTIP_OFFSET = 18   # from the cursor, so the pointer never covers the text

# --- the vertices a match would actually take ---
#
# Knowing a side *can* be matched is only half of it. Which vertices it would
# land on is the half that shows a match going to the wrong neighbour, or
# stopping short, or picking up a run that wanders off the shared edge -- and
# none of that is visible from a coloured line lying on the boundary. Drawn for
# the side under the cursor and for every side already pinned.
MATCH_DOT_COLOR = (0.35, 1.0, 0.55, 1.0)         # from a committed neighbour
SOURCE_DOT_COLOR = (1.0, 0.72, 0.25, 1.0)        # from the CAD tessellation
MATCH_DOT_OUTLINE = (0.05, 0.05, 0.05, 0.9)
MATCH_DOT_SIZE = 9.0
MATCH_DOT_OUTLINE_RATIO = 1.5

# --- the CAD structure under the triangles ---
#
# See cad_display: the Plasticity edges are recovered exactly, the surface flow
# is derived from each face's boundary. Both are drawn without depth testing,
# for the same reason the side highlight is -- they lie *on* the surface, so
# testing them against it is a coin flip per pixel.
BREP_DOT_COLOR = (1.0, 1.0, 1.0, 1.0)
BREP_DOT_OUTLINE = (0.05, 0.05, 0.05, 0.9)
BREP_DOT_SIZE = 7.0
FLOW_WIDTH = 1.0
FLOW_ALPHA = 0.55

MARGIN = 18
LINE_HEIGHT = 22
KEY_GAP = 10       # between a key's box and its action text
ITEM_GAP = 26      # between one key/action pair and the next along a row
FONT_SIZE = 13

TEXT_COLOR = (0.92, 0.92, 0.92, 1.0)
KEY_TEXT_COLOR = (1.0, 1.0, 1.0, 1.0)
KEY_BG_COLOR = (0.28, 0.28, 0.30, 0.85)
TYPED_COLOR = (1.0, 0.72, 0.25, 1.0)

# From `constants`, not from `operators`: the draw handler must never pull in
# the operators module, which imports this one back.
TWO_SPAN_GENERATOR_NAMES = constants.TWO_SPAN_GENERATORS

# The digits being typed are echoed from `state.typed_span`, not a module
# global: the keys that clear it (U/V, N-gon, the span wheel) are real
# operators now, and an operator cannot reach the running modal's attributes.

# Where the pointer was when the modal last looked, in window coordinates, or
# None when it is not over the viewport. The tooltip needs it and a draw
# handler has no event to read it from -- same arrangement as
# `hover_committed` below.
cursor_window: "tuple[float, float] | None" = None

# Set by the session modal when the patch under the cursor has already been
# committed, so the hint reads "Re-edit patch" -- clicking it reopens it with
# the spans it was built with instead of starting a fresh one.
hover_committed: bool = False


def keybinds_for(
    state: "state_mod.RetopPatchState",
) -> list[list[tuple[str, str]]]:
    """[(key, action), ...] for the session's current phase, bottom line last.

    Every key here is looked up in the keymap table rather than written out, so
    a remapped binding changes the hint with it. A hint line that says `E` when
    the key is now `Ctrl+E` is worse than no hint line at all -- it is the one
    place a user checks before deciding the feature is broken.
    """
    phase = state.session_phase

    def key(action_id: str) -> str:
        # Read off the live KeyMapItem, so a remapped key changes the hint with
        # it. A hint that says `E` when the key is now `Ctrl+E` is worse than
        # no hint at all -- it is the one place a user checks before deciding
        # the feature is broken.
        return keymap.describe(action_id)

    # The retopo x-ray is offered in every phase: it is the binding that
    # answers "is the retopology where I think it is", and that comes up at any
    # point. It sits on Shift+X because Alt+X now belongs to the mirror -- the
    # Hard Ops reflex.
    see_through = (key("see_through"), "Retopo X-Ray: "
                   + ("on" if getattr(state, "result_see_through", True) else "off"))
    # Which axes are currently mirrored lives on the modifier, not in state,
    # and a draw handler has no business reaching for an object to find out --
    # so the hint names the key and the panel names the state.
    mirror = (key("mirror"), "Mirror X/Y/Z")
    # Same reasoning as the x-ray: the CAD structure is read in every phase,
    # and most of all while deciding which surface to pick next.
    cad_edges = (key("cad_edges"), "Plasticity edges: "
                 + ("on" if getattr(state, "show_cad_edges", False) else "off"))

    if phase == 'OBJECT':
        return [
            ("Click", "Enter object"),
            cad_edges,
            see_through,
            (key("back"), "End session"),
        ]
    if phase == 'TWEAK':
        # Blender's keys, not ours: the session is only holding the door open.
        # Listed anyway because the whole point of the round trip is that you
        # do not have to remember which mode you are in to fix a seam.
        return [
            ("K", "Knife"),
            ("Ctrl+R", "Loop cut"),
            ("J", "Connect vertices"),
            ("G", "Move (snapped, auto-merge)"),
            ("M", "Merge by distance"),
            # Blender's own Tab, not the table's: the modal consumes it in this
            # phase whatever hand_edit is bound to, because getting *out* of a
            # mode Blender put you in has to be the key Blender uses.
            ("Tab", "Back to Retop"),
        ]

    if phase == 'PATCH':
        return [
            ("Click", "Re-edit patch" if hover_committed else "Pick surface"),
            (key("hand_edit"), "Hand-edit mesh"),
            # Ctrl+Z is deliberately *not* listed. It is Blender's own key and
            # reaching for it is automatic; what the session does is make one
            # step mean one committed patch, which is a property of the undo
            # stack rather than a binding to advertise. The line is short and
            # every entry on it has to earn its width.
            mirror,
            cad_edges,
            see_through,
            (key("back"), "Leave object"),
        ]

    # ADJUST
    # getattr: this runs inside a draw handler, which can fire in the middle of
    # a reload when the scene still carries the previous property group.
    commit_label = "Replace patch" if getattr(state, "editing_committed", False) else "Commit"

    # N-gon mode has no spans at all, so advertising span keys there would be
    # advertising keys that do nothing.
    # The two span keys are one hint, since they are a pair and the line has no
    # room for both -- "Ctrl+Wheel Up/Down" collapses to "Ctrl+Scroll" whenever
    # they really are the two directions of one wheel, and spells both out when
    # somebody has bound them to something else.
    span_key = _pair_label("span_more", "span_less")
    if getattr(state, "ngon_mode", False):
        binds = [
            (span_key, "Detail +/-"),
            (key("ngon_mode"), "Back to grid"),
        ]
    else:
        binds = [
            (span_key, "Span +/-"),
            ("0-9", "Type span"),
        ]
        if state.generator_name in TWO_SPAN_GENERATOR_NAMES:
            binds.append((key("span_axis"), f"U/V direction (now {state.span_axis})"))
        binds.append((key("ngon_mode"), "N-gon (flat faces)"))
    if getattr(state, "editing_committed", False):
        binds.append((key("delete_patch"), "Delete patch"))
    binds.append(cad_edges)
    binds.append(see_through)
    binds.append((key("match_mode"), "Side highlight: "
                  + ("on" if getattr(state, "match_mode", True) else "off")))
    binds.extend([
        (key("pin_neighbour"), "Match a side, else " + commit_label.lower()),
        (key("pin_source"), "Match the CAD edge"),
    ])
    # Every way of committing, not just the first: right-click and Enter are
    # both worth knowing (the right-click is the Plasticity-style affordance
    # people arrive expecting), and this is the one action where the second
    # binding is as much a habit as the first.
    for label in keymap.describe_all("commit"):
        binds.append((label, commit_label))
    binds.append((key("back"), "Discard"))
    return binds


def _pair_label(up_action: str, down_action: str) -> str:
    """One label for two opposite actions, e.g. "Ctrl+Scroll" for a wheel pair.

    They are always used together and the hint line is one row across the
    bottom of the screen, so spending two entries on "more" and "less" costs
    more than it says. Collapsed only when they really are the two directions
    of one wheel with the same modifiers; anything else is spelled out, because
    a user who moved one of them needs to see what they moved it to.
    """
    up = keymap.describe(up_action)
    down = keymap.describe(down_action)
    up_key, _, up_rest = up.rpartition("+")
    down_key, _, down_rest = down.rpartition("+")
    if up_key == down_key and {up_rest, down_rest} == {"Wheel Up", "Wheel Down"}:
        return f"{up_key}+Scroll" if up_key else "Scroll"
    return f"{up} / {down}"


def _set_font_size(font_id: int, size: float) -> None:
    # blf.size() dropped its dpi argument in Blender 4.0.
    try:
        blf.size(font_id, size)
    except TypeError:
        blf.size(font_id, size, 72)


def _draw_filled_rect(
    x: float, y: float, width: float, height: float,
    color: tuple[float, float, float, float],
) -> None:
    vertices = (
        (x, y), (x + width, y),
        (x + width, y + height), (x, y + height),
    )
    indices = ((0, 1, 2), (0, 2, 3))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": vertices}, indices=indices)

    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def _draw_key_background(x: float, y: float, width: float, height: float) -> None:
    _draw_filled_rect(x, y, width, height, KEY_BG_COLOR)


def _draw() -> None:
    context = bpy.context
    state = getattr(context.scene, "plasticity_retop", None)
    if state is None or not state.session_active:
        return

    region = context.region
    if region is None:
        return

    _draw_vertex_dots(context, state, region)
    _draw_match_points(context, state, region)
    _draw_brep_vertices(context, state, region)

    scale = max(0.5, getattr(state, "overlay_scale", 1.0))
    _draw_side_tooltip(state, region, scale)

    font_id = 0
    _set_font_size(font_id, FONT_SIZE * scale)

    margin = MARGIN * scale
    line_height = LINE_HEIGHT * scale
    key_gap = KEY_GAP * scale
    item_gap = ITEM_GAP * scale
    key_pad = 12 * scale

    binds = keybinds_for(state)
    if not binds:
        return

    # Laid out in a row, wrapped onto as many rows as it takes, and centred at
    # the bottom. A column down one side is what a docked panel covers -- and
    # every corner of a 3D view has something docked in it.
    entries = []
    for key, action in binds:
        key_w, _ = blf.dimensions(font_id, key)
        action_w, action_h = blf.dimensions(font_id, action)
        entries.append((key, action, key_w + key_pad, action_w, action_h))

    available = region.width - 2 * margin
    rows = [[]]
    row_width = 0.0
    for entry in entries:
        width = entry[2] + KEY_GAP + entry[3]
        # Never leave a row empty: one entry wider than the viewport still has
        # to go somewhere.
        if rows[-1] and row_width + item_gap + width > available:
            rows.append([])
            row_width = 0.0
        row_width += (item_gap if rows[-1] else 0.0) + width
        rows[-1].append(entry)

    # Bottom-up, so the rows read top-down in the order the binds were given.
    for row_index, row in enumerate(reversed(rows)):
        y = margin + row_index * line_height
        total = sum(entry[2] + key_gap + entry[3] for entry in row)
        total += item_gap * (len(row) - 1)
        x = (region.width - total) * 0.5

        for key, action, key_box_w, action_w, action_h in row:
            _draw_key_background(x, y - 4 * scale, key_box_w, action_h + 9 * scale)

            blf.color(font_id, *KEY_TEXT_COLOR)
            blf.position(font_id, x + key_pad * 0.5, y, 0)
            blf.draw(font_id, key)

            blf.color(font_id, *TEXT_COLOR)
            blf.position(font_id, x + key_box_w + key_gap, y, 0)
            blf.draw(font_id, action)

            x += key_box_w + key_gap + action_w + item_gap

    typed = getattr(state, "typed_span", "")
    if typed and state.session_phase == 'ADJUST':
        label = f"Span: {typed}_"
        label_w, _label_h = blf.dimensions(font_id, label)
        blf.color(font_id, *TYPED_COLOR)
        blf.position(font_id, (region.width - label_w) * 0.5,
                     margin + len(rows) * line_height + 6 * scale, 0)
        blf.draw(font_id, label)


def _preview_vertex_coords() -> "list[mathutils.Vector] | None":
    """World-space vertices of the preview object, or None when there is
    nothing to draw. Read from the *base* mesh, like commit does: the Preview
    Offset is a Displace modifier, so evaluating it would put the dots where
    the geometry isn't going to be committed.
    """
    obj = bpy.data.objects.get(mesh_build.PREVIEW_OBJ_NAME)
    if obj is None or obj.type != 'MESH' or not obj.data.vertices:
        return None
    matrix = obj.matrix_world
    return [matrix @ vertex.co for vertex in obj.data.vertices]


def _draw_side_references(state: "state_mod.RetopPatchState") -> None:
    """The active patch's sides while the side picker is on."""
    references = sidematch.active_sides()
    if not references:
        return

    hovered = getattr(state, "hovered_side", -1)
    pins = sidematch.side_override_map(state)
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    viewport = gpu.state.viewport_get()
    shader.bind()
    shader.uniform_float("viewportSize", (viewport[2], viewport[3]))

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')  # same reason as the dots: they lie on the surface

    # Hovered side last, so it draws over its neighbours rather than under them.
    for reference in sorted(references, key=lambda ref: ref.index == hovered):
        if len(reference.points) < 2:
            continue
        is_hovered = reference.index == hovered
        color, width = _side_appearance(
            reference, pins.get(reference.index), is_hovered)
        shader.uniform_float("lineWidth", width)
        shader.uniform_float("color", color)
        batch_for_shader(shader, 'LINE_STRIP', {"pos": reference.points}).draw(shader)

    gpu.state.blend_set('NONE')


def _side_appearance(
    reference: "sidematch.SideReference", pin_kind: str | None, hovered: bool
) -> "tuple[tuple[float, float, float, float], float]":
    """(colour, line width) for one side of the picker.

    Green is reserved for a side whose vertices the preview is *actually*
    reproducing; amber for one following its own CAD edge. Everything else is
    grey, whether it could be matched or not -- the difference between those
    two is what the tooltip is for, and painting them the same green was what
    made a match look applied when it was not.
    """
    if reference.applied:
        if pin_kind == sidematch.PIN_SOURCE:
            return ((SIDE_SOURCE_HOVER_COLOR if hovered else SIDE_SOURCE_COLOR),
                    SIDE_HOVER_WIDTH if hovered else SIDE_MATCHED_WIDTH)
        return ((SIDE_MATCHED_HOVER_COLOR if hovered else SIDE_MATCHED_COLOR),
                SIDE_HOVER_WIDTH if hovered else SIDE_MATCHED_WIDTH)
    if reference.available:
        return ((SIDE_AVAILABLE_HOVER_COLOR if hovered else SIDE_AVAILABLE_COLOR),
                SIDE_HOVER_WIDTH if hovered else SIDE_WIDTH)
    return ((SIDE_BLOCKED_HOVER_COLOR if hovered else SIDE_BLOCKED_COLOR),
            SIDE_HOVER_WIDTH if hovered else SIDE_WIDTH)


def _draw_side_tooltip(
    state: "state_mod.RetopPatchState", region: bpy.types.Region, scale: float
) -> None:
    """What the side under the cursor is doing, said by the cursor.

    Two lines: whether it is selected for surface matching, and why. Drawn from
    the POST_PIXEL handler, next to the pointer rather than in a corner -- the
    question is asked with the mouse already on the side.
    """
    if state.session_phase != 'ADJUST' or not getattr(state, "match_mode", False):
        return
    if cursor_window is None:
        return

    references = sidematch.active_sides()
    index = getattr(state, "hovered_side", -1)
    if not (0 <= index < len(references)):
        return
    reference = references[index]

    pins = sidematch.side_override_map(state)
    title, detail = sidematch.status_of(reference, pins.get(index))

    font_id = 0
    _set_font_size(font_id, FONT_SIZE * scale)
    title_w, title_h = blf.dimensions(font_id, title)
    detail_w, detail_h = blf.dimensions(font_id, detail)

    pad = TOOLTIP_PAD * scale
    line = max(title_h, detail_h) + 6 * scale
    width = max(title_w, detail_w) + 2 * pad
    height = 2 * line + 2 * pad - 6 * scale

    x = cursor_window[0] - region.x + TOOLTIP_OFFSET * scale
    y = cursor_window[1] - region.y + TOOLTIP_OFFSET * scale
    # Kept inside the region: a tooltip half off the edge of the viewport is
    # exactly the half you needed to read.
    x = min(max(0.0, x), max(0.0, region.width - width))
    y = min(max(0.0, y), max(0.0, region.height - height))

    _draw_filled_rect(x, y, width, height, TOOLTIP_BG)

    blf.color(font_id, *(TOOLTIP_MATCHED if reference.applied else TOOLTIP_TEXT))
    blf.position(font_id, x + pad, y + pad + line - 6 * scale, 0)
    blf.draw(font_id, title)

    blf.color(font_id, *TOOLTIP_DETAIL)
    blf.position(font_id, x + pad, y + pad - 6 * scale, 0)
    blf.draw(font_id, detail)


def _draw_points() -> None:
    """POST_VIEW: the side highlight, which is genuinely 3D geometry.

    The vertex dots are *not* here -- they are drawn in screen space by
    `_draw_vertex_dots`, from the POST_PIXEL handler.
    """
    context = bpy.context
    state = getattr(context.scene, "plasticity_retop", None)
    # getattr throughout: a draw handler can fire mid-reload, when the scene
    # still carries the previous property group.
    if state is None or not state.session_active:
        return

    # Drawn in every phase, unlike the side highlight: the CAD structure is what
    # you read *while choosing* a surface, not only while adjusting one.
    _draw_cad_structure(context, state)

    if state.session_phase != 'ADJUST':
        return
    if getattr(state, "match_mode", False):
        _draw_side_references(state)


def _match_dot_sets(
    state: "state_mod.RetopPatchState",
) -> "list[tuple[list[mathutils.Vector], tuple[float, float, float, float]]]":
    """[(world points, colour)] the match overlay should draw right now.

    The hovered side shows what clicking it would take; a pinned side shows
    what it did take, so a pin that landed on the wrong neighbour stays visible
    after the click rather than only during the hover.
    """
    references = sidematch.active_sides()
    if not references:
        return []

    pins = sidematch.side_override_map(state)
    hovered = getattr(state, "hovered_side", -1)

    sets = []
    for reference in references:
        kind = pins.get(reference.index)
        if kind == sidematch.PIN_SOURCE:
            sets.append((reference.source_world, SOURCE_DOT_COLOR))
        elif kind == sidematch.PIN_NEIGHBOUR and reference.match_world:
            sets.append((reference.match_world, MATCH_DOT_COLOR))
        elif reference.index == hovered and kind in (None, sidematch.PIN_EXCLUDED):
            # Nothing being matched here: preview whichever set a click would
            # take. Including a side released by hand -- the dots are what
            # clicking it again would bring back.
            if reference.match_world:
                sets.append((reference.match_world, MATCH_DOT_COLOR))
            elif reference.source_world:
                sets.append((reference.source_world, SOURCE_DOT_COLOR))
    return sets


def _draw_match_points(
    context: bpy.types.Context,
    state: "state_mod.RetopPatchState",
    region: bpy.types.Region,
) -> None:
    """Dots on the vertices the current matches land on."""
    if state.session_phase != 'ADJUST':
        return
    if not getattr(state, "match_mode", False):
        return

    sets = _match_dot_sets(state)
    if not sets:
        return

    rv3d = context.region_data
    if rv3d is None:
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    shader.bind()

    for points, color in sets:
        projected = []
        for point in points:
            screen = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
            if screen is not None:  # None for anything behind the camera
                projected.append(screen)
        if not projected:
            continue
        for half, dot_color in (
                (MATCH_DOT_SIZE * MATCH_DOT_OUTLINE_RATIO * 0.5, MATCH_DOT_OUTLINE),
                (MATCH_DOT_SIZE * 0.5, color)):
            vertices, indices = _discs_around(projected, half)
            shader.uniform_float("color", dot_color)
            batch_for_shader(shader, 'TRIS', {"pos": vertices},
                             indices=indices).draw(shader)

    gpu.state.blend_set('NONE')


def _cad_display_target(
    context: bpy.types.Context, state: "state_mod.RetopPatchState"
) -> "tuple[bpy.types.Object | None, bpy.types.Mesh | None, int | None]":
    """(object, mesh, face id or None) the CAD overlay should describe.

    None for the face id means the whole object. A scope of ACTIVE with nothing
    picked yet falls back to the whole object rather than drawing nothing --
    "pick a surface" is exactly the moment the model's layout is worth seeing.
    """
    obj = bpy.data.objects.get(getattr(state, "session_object_name", ""))
    if obj is None or obj.type != 'MESH' or not obj.data.get("face_ids"):
        return None, None, None

    face_id = None
    if getattr(state, "cad_display_scope", 'OBJECT') == 'ACTIVE':
        active = getattr(state, "active_face_id", -1)
        if active != -1:
            face_id = active
    return obj, obj.data, face_id


def _draw_line_batch(
    points: "list[mathutils.Vector]",
    color: tuple[float, float, float, float],
    width: float,
) -> None:
    """One LINES batch for a whole list of point pairs.

    One batch, not one per edge: a CAD part has hundreds of edges, and a draw
    call each is what turns an overlay into a stutter.
    """
    if len(points) < 2:
        return
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    viewport = gpu.state.viewport_get()
    shader.bind()
    shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'LINES', {"pos": points}).draw(shader)


# How far a depth-tested CAD line is nudged towards the viewer, as a share of
# its distance to the viewpoint. Proportional rather than absolute for the same
# reason the raycast's step past a hit is: a fixed epsilon is either too small
# to clear the surface at range or large enough to lift a line off a small part
# visibly. Small enough that the line still reads as lying *on* the surface.
DEPTH_NUDGE = 0.002


def _towards_viewer(
    points: list["mathutils.Vector"], rv3d: bpy.types.RegionView3D | None
) -> list["mathutils.Vector"]:
    """Lift world-space points off the surface, towards the viewpoint.

    Only needed when the CAD display is depth-tested: the lines lie exactly on
    the surface they describe, so testing them against it without this is a
    coin flip per pixel and they come out as a stipple. One view direction for
    the whole batch rather than a per-point eye vector -- at a nudge this small
    the difference at the edge of the frame is far below a pixel, and a draw
    handler should not be normalising a vector per point.
    """
    if rv3d is None or not points:
        return points
    # Everything here comes out of the region's own matrix, so the draw handler
    # still imports nothing it didn't already.
    inverse = rv3d.view_matrix.inverted()
    towards = inverse.col[2].to_3d().normalized()  # camera +Z: back at the viewer
    origin = inverse.translation
    return [point + towards * ((point - origin).length * DEPTH_NUDGE)
            for point in points]


def _draw_cad_structure(
    context: bpy.types.Context, state: "state_mod.RetopPatchState"
) -> None:
    """POST_VIEW: the Plasticity edges, and the flow of each CAD face."""
    want_edges = getattr(state, "show_cad_edges", False)
    want_flow = getattr(state, "show_surface_flow", False)
    if not (want_edges or want_flow):
        return

    obj, mesh, face_id = _cad_display_target(context, state)
    if mesh is None:
        return

    matrix = obj.matrix_world
    gpu.state.blend_set('ALPHA')

    # Drawn through the model by default -- that is what makes the structure of
    # a whole part readable at a glance. Turned off, they are occluded like
    # real geometry, so the far side of a curved or enclosed shape stops
    # showing through the near side; the nudge is what keeps them from
    # z-fighting with the very surface they lie on.
    xray = getattr(state, "cad_display_xray", True)
    rv3d = context.region_data
    if xray:
        gpu.state.depth_test_set('NONE')
    else:
        gpu.state.depth_test_set('LESS_EQUAL')

    def place(points: list["mathutils.Vector"]) -> list["mathutils.Vector"]:
        world = [matrix @ point for point in points]
        return world if xray else _towards_viewer(world, rv3d)

    # Flow first, edges over it: the edges are the exact thing and should never
    # be hidden by the derived one.
    if want_flow:
        colour = tuple(getattr(state, "flow_color", (0.65, 0.45, 1.0)))
        _draw_line_batch(
            place(cad_display.flow_segments(
                mesh, getattr(state, "flow_density", 3),
                getattr(state, "corner_angle_threshold", 135.0), face_id)),
            colour + (FLOW_ALPHA,), FLOW_WIDTH)

    if want_edges:
        colour = tuple(getattr(state, "cad_edge_color", (0.1, 0.9, 1.0)))
        _draw_line_batch(
            place(cad_display.edge_segments(mesh, face_id)),
            colour + (1.0,), getattr(state, "cad_edge_width", 2.0))

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')


def _draw_brep_vertices(
    context: bpy.types.Context,
    state: "state_mod.RetopPatchState",
    region: bpy.types.Region,
) -> None:
    """The junctions between CAD edges, as screen-space dots.

    Tied to the edge display: a B-rep vertex is where two edges meet, and dots
    with no edges to sit on say nothing.
    """
    if not getattr(state, "show_cad_edges", False):
        return
    if not getattr(state, "show_brep_vertices", False):
        return

    obj, mesh, face_id = _cad_display_target(context, state)
    if mesh is None:
        return

    rv3d = context.region_data
    if rv3d is None:
        return

    matrix = obj.matrix_world
    projected = []
    for point in cad_display.brep_vertices(mesh, face_id):
        screen = view3d_utils.location_3d_to_region_2d(region, rv3d, matrix @ point)
        if screen is not None:  # None for anything behind the camera
            projected.append(screen)
    if not projected:
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    shader.bind()
    for half, color in ((BREP_DOT_SIZE * 0.75, BREP_DOT_OUTLINE),
                        (BREP_DOT_SIZE * 0.5, BREP_DOT_COLOR)):
        vertices, indices = _discs_around(projected, half)
        shader.uniform_float("color", color)
        batch_for_shader(shader, 'TRIS', {"pos": vertices},
                         indices=indices).draw(shader)
    gpu.state.blend_set('NONE')


def _discs_around(
    centres: "list[mathutils.Vector]", half: float, segments: int = DOT_SEGMENTS
) -> tuple[list[tuple[float, float]], list[tuple[int, int, int]]]:
    """A triangle fan per centre, as (vertices, indices) for a TRIS batch.

    Round rather than square: these mark where a vertex *is*, and a square dot
    reads as a handle to grab. `segments` stays a multiple of four so the disc
    measures exactly 2*half across and 2*half tall -- the size setting has to
    stay something a test can measure.
    """
    vertices = []
    indices = []
    for point in centres:
        base = len(vertices)
        x, y = point
        vertices.append((x, y))
        for step in range(segments):
            angle = 2.0 * math.pi * step / segments
            vertices.append((x + half * math.cos(angle), y + half * math.sin(angle)))
        for step in range(segments):
            indices.append((base, base + 1 + step,
                            base + 1 + (step + 1) % segments))
    return vertices, indices


def _draw_vertex_dots(
    context: bpy.types.Context,
    state: "state_mod.RetopPatchState",
    region: bpy.types.Region,
) -> None:
    """A dot on every boundary vertex of the n-gon being adjusted."""
    if state.session_phase != 'ADJUST':
        return
    if not getattr(state, "ngon_mode", False):
        return
    if not getattr(state, "ngon_show_verts", False):
        return

    coords = _preview_vertex_coords()
    if not coords:
        return

    rv3d = context.region_data
    if rv3d is None:
        return

    projected = []
    for point in coords:
        screen = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
        if screen is not None:  # None for anything behind the camera
            projected.append(screen)
    if not projected:
        return

    size = getattr(state, "ngon_vert_size", VERT_SIZE)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    shader.bind()

    # Dark disc behind the bright one, so a dot stays readable over both a
    # pale CAD surface and the dark background.
    for half, color in ((size * VERT_OUTLINE_RATIO * 0.5, VERT_OUTLINE_COLOR),
                        (size * 0.5, VERT_COLOR)):
        vertices, indices = _discs_around(projected, half)
        shader.uniform_float("color", color)
        batch_for_shader(shader, 'TRIS', {"pos": vertices},
                         indices=indices).draw(shader)

    gpu.state.blend_set('NONE')


def enable() -> None:
    global _handle, _points_handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw, (), 'WINDOW', 'POST_PIXEL')
    if _points_handle is None:
        _points_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_points, (), 'WINDOW', 'POST_VIEW')


def disable() -> None:
    global _handle, _points_handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    if _points_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_points_handle, 'WINDOW')
        _points_handle = None
