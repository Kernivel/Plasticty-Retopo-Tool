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
VERT_OUTLINE_RATIO = 1.45  # dark square behind the bright one

# Drawn as screen-space quads rather than GL points. `gpu.state.point_size_set`
# is a no-op whenever the backend runs with program point size enabled -- the
# shader has to write gl_PointSize then, and the builtin UNIFORM_COLOR one does
# not -- which came out as 1px dots that ignored the size setting entirely.
# Two triangles per dot always honour the pixels asked for.

# --- side reference picker (M in ADJUST) ---
#
# Three states, because the useful question is not "where are the sides" but
# "which of them can I actually match": one that borders a committed neighbour,
# one that doesn't, and the one under the cursor.
# Hover brightens a side's *own* colour instead of replacing it: a single
# hover colour hid the one thing worth knowing before clicking -- whether this
# side can be matched at all -- and turned a refusal into a surprise.
SIDE_AVAILABLE_COLOR = (0.20, 0.75, 0.38, 0.80)
SIDE_AVAILABLE_HOVER_COLOR = (0.45, 1.0, 0.60, 1.0)
SIDE_BLOCKED_COLOR = (0.42, 0.42, 0.45, 0.45)
SIDE_BLOCKED_HOVER_COLOR = (0.75, 0.40, 0.35, 0.95)  # red: clicking will refuse
SIDE_WIDTH = 3.0
SIDE_HOVER_WIDTH = 6.0

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

# Set by the session modal while digits are being typed, so the overlay can
# echo them back like Blender's own numeric input.
typed_span: str = ""

# Set by the session modal when the patch under the cursor has already been
# committed, so the hint reads "Re-edit patch" -- clicking it reopens it with
# the spans it was built with instead of starting a fresh one.
hover_committed: bool = False


def keybinds_for(
    state: "state_mod.RetopPatchState",
) -> list[list[tuple[str, str]]]:
    """[(key, action), ...] for the session's current phase, bottom line last."""
    phase = state.session_phase
    # Alt+X is offered in every phase: it is the binding that answers "is the
    # retopology where I think it is", and that comes up at any point.
    see_through = ("Alt+X", "Retopo X-Ray: "
                            + ("on" if getattr(state, "result_see_through", True) else "off"))
    # Same reasoning: the CAD structure is read in every phase, and most of all
    # while deciding which surface to pick next.
    cad_edges = ("E", "Plasticity edges: "
                      + ("on" if getattr(state, "show_cad_edges", False) else "off"))

    if phase == 'OBJECT':
        return [
            ("Click", "Enter object"),
            cad_edges,
            see_through,
            ("Esc", "End session"),
        ]
    if phase == 'PATCH':
        return [
            ("Click", "Re-edit patch" if hover_committed else "Pick surface"),
            cad_edges,
            see_through,
            ("Esc", "Leave object"),
        ]

    # ADJUST
    # getattr: this runs inside a draw handler, which can fire in the middle of
    # a reload when the scene still carries the previous property group.
    commit_label = "Replace patch" if getattr(state, "editing_committed", False) else "Commit"

    # N-gon mode has no spans at all, so advertising span keys there would be
    # advertising keys that do nothing.
    if getattr(state, "ngon_mode", False):
        binds = [
            ("Ctrl+Scroll", "Detail +/-"),
            ("N", "Back to grid"),
        ]
    else:
        binds = [
            ("Ctrl+Scroll", "Span +/-"),
            ("0-9", "Type span"),
        ]
        if state.generator_name in TWO_SPAN_GENERATOR_NAMES:
            binds.append(("Tab", f"U/V direction (now {state.span_axis})"))
        binds.append(("N", "N-gon (flat faces)"))
    if getattr(state, "editing_committed", False):
        binds.append(("X", "Delete patch"))
    binds.append(cad_edges)
    binds.append(see_through)
    binds.append(("M", "Side highlight: "
                       + ("on" if getattr(state, "match_mode", True) else "off")))
    binds.extend([
        ("Click", "Match a side, else " + commit_label.lower()),
        ("Ctrl+Click", "Match the CAD edge"),
        ("R-Click", commit_label),
        ("Enter", commit_label),
        ("Esc", "Discard"),
    ])
    return binds


def _set_font_size(font_id: int, size: float) -> None:
    # blf.size() dropped its dpi argument in Blender 4.0.
    try:
        blf.size(font_id, size)
    except TypeError:
        blf.size(font_id, size, 72)


def _draw_key_background(x: float, y: float, width: float, height: float) -> None:
    vertices = (
        (x, y), (x + width, y),
        (x + width, y + height), (x, y + height),
    )
    indices = ((0, 1, 2), (0, 2, 3))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": vertices}, indices=indices)

    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", KEY_BG_COLOR)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


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

    if typed_span and state.session_phase == 'ADJUST':
        label = f"Span: {typed_span}_"
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
        if reference.available:
            color = SIDE_AVAILABLE_HOVER_COLOR if is_hovered else SIDE_AVAILABLE_COLOR
        else:
            color = SIDE_BLOCKED_HOVER_COLOR if is_hovered else SIDE_BLOCKED_COLOR
        width = SIDE_HOVER_WIDTH if is_hovered else SIDE_WIDTH
        shader.uniform_float("lineWidth", width)
        shader.uniform_float("color", color)
        batch_for_shader(shader, 'LINE_STRIP', {"pos": reference.points}).draw(shader)

    gpu.state.blend_set('NONE')


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
        elif reference.index == hovered and kind is None:
            # Nothing pinned here yet: preview whichever set a click would take.
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
            vertices, indices = _quads_around(projected, half)
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
    gpu.state.depth_test_set('NONE')

    # Flow first, edges over it: the edges are the exact thing and should never
    # be hidden by the derived one.
    if want_flow:
        colour = tuple(getattr(state, "flow_color", (0.65, 0.45, 1.0)))
        _draw_line_batch(
            [matrix @ point for point in cad_display.flow_segments(
                mesh, getattr(state, "flow_density", 3),
                getattr(state, "corner_angle_threshold", 135.0), face_id)],
            colour + (FLOW_ALPHA,), FLOW_WIDTH)

    if want_edges:
        colour = tuple(getattr(state, "cad_edge_color", (0.1, 0.9, 1.0)))
        _draw_line_batch(
            [matrix @ point for point in cad_display.edge_segments(mesh, face_id)],
            colour + (1.0,), getattr(state, "cad_edge_width", 2.0))

    gpu.state.blend_set('NONE')


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
        vertices, indices = _quads_around(projected, half)
        shader.uniform_float("color", color)
        batch_for_shader(shader, 'TRIS', {"pos": vertices},
                         indices=indices).draw(shader)
    gpu.state.blend_set('NONE')


def _quads_around(
    centres: "list[mathutils.Vector]", half: float
) -> tuple[list[tuple[float, float]], list[tuple[int, int, int]]]:
    """Two triangles per centre, as (vertices, indices) for a TRIS batch."""
    vertices = []
    indices = []
    for point in centres:
        base = len(vertices)
        x, y = point
        vertices.extend((
            (x - half, y - half), (x + half, y - half),
            (x + half, y + half), (x - half, y + half),
        ))
        indices.extend(((base, base + 1, base + 2), (base, base + 2, base + 3)))
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

    # Dark square behind the bright one, so a dot stays readable over both a
    # pale CAD surface and the dark background.
    for half, color in ((size * VERT_OUTLINE_RATIO * 0.5, VERT_OUTLINE_COLOR),
                        (size * 0.5, VERT_COLOR)):
        vertices, indices = _quads_around(projected, half)
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
