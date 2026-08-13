"""Bottom-right keybind hint overlay, drawn in the 3D viewport while a retop
session is running (mirrors how Plasticity shows its own modal keybinds).
"""
import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

_handle = None

MARGIN = 18
LINE_HEIGHT = 22
KEY_GAP = 10
FONT_SIZE = 13

TEXT_COLOR = (0.92, 0.92, 0.92, 1.0)
KEY_TEXT_COLOR = (1.0, 1.0, 1.0, 1.0)
KEY_BG_COLOR = (0.28, 0.28, 0.30, 0.85)
TYPED_COLOR = (1.0, 0.72, 0.25, 1.0)

# Kept in sync with operators.TWO_SPAN_GENERATORS; duplicated rather than
# imported so the draw handler never pulls in the operators module (which
# imports this one).
TWO_SPAN_GENERATOR_NAMES = {"Quad", "Wedge"}

# Set by the session modal while digits are being typed, so the overlay can
# echo them back like Blender's own numeric input.
typed_span = ""


def keybinds_for(state):
    """[(key, action), ...] for the session's current phase, bottom line last."""
    phase = state.session_phase
    if phase == 'OBJECT':
        return [
            ("Click", "Enter object"),
            ("Esc", "End session"),
        ]
    if phase == 'PATCH':
        return [
            ("Click", "Pick surface"),
            ("Esc", "Leave object"),
        ]

    # ADJUST
    binds = [
        ("Ctrl+Scroll", "Span +/-"),
        ("0-9", "Type span"),
    ]
    if state.generator_name in TWO_SPAN_GENERATOR_NAMES:
        binds.append(("Tab", f"U/V direction (now {state.span_axis})"))
    binds.extend([
        ("R-Click", "Commit"),
        ("Enter", "Commit"),
        ("Esc", "Discard"),
    ])
    return binds


def _set_font_size(font_id, size):
    # blf.size() dropped its dpi argument in Blender 4.0.
    try:
        blf.size(font_id, size)
    except TypeError:
        blf.size(font_id, size, 72)


def _draw_key_background(x, y, width, height):
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


def _draw():
    context = bpy.context
    state = getattr(context.scene, "plasticity_retop", None)
    if state is None or not state.session_active:
        return

    region = context.region
    if region is None:
        return

    font_id = 0
    _set_font_size(font_id, FONT_SIZE)

    binds = keybinds_for(state)
    base_y = MARGIN
    right_x = region.width - MARGIN

    # Bottom-up, so the list reads top-down in the order given.
    for i, (key, action) in enumerate(reversed(binds)):
        y = base_y + i * LINE_HEIGHT

        action_w, action_h = blf.dimensions(font_id, action)
        key_w, _key_h = blf.dimensions(font_id, key)

        action_x = right_x - action_w
        key_box_w = key_w + 12
        key_box_x = action_x - KEY_GAP - key_box_w

        _draw_key_background(key_box_x, y - 4, key_box_w, action_h + 9)

        blf.color(font_id, *KEY_TEXT_COLOR)
        blf.position(font_id, key_box_x + 6, y, 0)
        blf.draw(font_id, key)

        blf.color(font_id, *TEXT_COLOR)
        blf.position(font_id, action_x, y, 0)
        blf.draw(font_id, action)

    if typed_span and state.session_phase == 'ADJUST':
        label = f"Span: {typed_span}_"
        label_w, _label_h = blf.dimensions(font_id, label)
        blf.color(font_id, *TYPED_COLOR)
        blf.position(font_id, right_x - label_w, base_y + len(binds) * LINE_HEIGHT + 6, 0)
        blf.draw(font_id, label)


def enable():
    global _handle
    if _handle is not None:
        return
    _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL')


def disable():
    global _handle
    if _handle is None:
        return
    bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
    _handle = None
