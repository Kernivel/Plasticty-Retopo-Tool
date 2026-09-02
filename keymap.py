"""Which key does what — declared here, owned by Blender.

The session's keys were `event.type == 'X'` comparisons inside `operators._modal`.
That leaves nothing to remap and nothing in Blender's keymap editor to find
either, because a modal operator reads raw events and sits *above* every
keymap. Making them remappable by hand meant a table, a capture modal and a
panel to draw it in — a second, worse keymap editor living next to Blender's.

So they are real `KeyMapItem`s on real operators now, and Blender owns all of
it: the editing UI, the conflict display, the per-item restore, the
persistence in the user's preferences. This module only *declares* what to
register. The addon's preferences page draws them with `rna_keymap_ui.draw_kmi`
— the same rows the keymap editor uses — and the panel's Keybinds tab is a
button that opens it.

**Who dispatches them is a second question, and the answer differs by scope.**
`GLOBAL` actions are dispatched by Blender, like any keymap item, because they
must work with no session running. `SESSION` actions are dispatched by the
modal, which reads the live items and runs the matching operator itself.

That is not belt-and-braces. A key in the 3D View keymap does not reliably beat
one in a *mode* keymap, and the session's keys collide with mode keymaps
constantly -- `X` is `object.delete` in Object Mode, `Tab` is
`object.editmode_toggle` in Object Non-modal. Registering each action in
whichever keymap owns its competitor is unmaintainable and still leaves the
next addon to claim the key; MACHIN3 puts its own `Alt+X` in `Mesh` rather than
`3D View` for exactly this reason. The modal sits above every keymap, so
dispatching from there always wins, and the items stay real -- editable in
Blender's rows, listed in the keymap editor, saved in the user's preferences.

The failure it prevents is not cosmetic: with `X` falling through, deleting a
patch that turned out not to be committed reached `object.delete` and took the
CAD object with it.

Two things stay outside all of this:

- **the digits and Backspace**, numeric entry rather than a shortcut: they must
  stay instantaneous and they only make sense as a block;
- **the mirror's `Alt+X` then `X`/`Y`/`Z`**, a key *sequence*, which Blender's
  keymap has no notion of.

The left click is *half* outside. Taking the side under the cursor is a normal
binding (`pin_neighbour`, `pin_source`); what stays in the modal is the
fallback when there is no side under the cursor, which commits — that one
genuinely depends on the hover, and the modal hands the event over whenever it
doesn't apply.
"""
import bpy


def _b(key: str, ctrl: bool = False, shift: bool = False, alt: bool = False) -> dict[str, object]:
    return {"type": key, "ctrl": ctrl, "shift": shift, "alt": alt}


SESSION = 'SESSION'   # dispatched by the modal, which always wins
GLOBAL = 'GLOBAL'     # dispatched by Blender: must work with no session

# (id, label, scope, operator, operator properties, default bindings)
#
# `id` names the action for the overlay hints and the preferences page; it is
# not a Blender concept. Two entries can share an operator and differ by their
# properties, which is how one `nudge_span` covers both wheel directions.
ACTIONS: tuple[tuple[str, str, str, str, dict[str, object], list[dict[str, object]]], ...] = (
    ("span_more", "Span +", SESSION, "retop.nudge_span", {"delta": 1},
     [_b('WHEELUPMOUSE', ctrl=True)]),
    ("span_less", "Span -", SESSION, "retop.nudge_span", {"delta": -1},
     [_b('WHEELDOWNMOUSE', ctrl=True)]),
    ("span_axis", "U / V direction", SESSION, "retop.toggle_span_axis", {}, [_b('TAB')]),
    ("ngon_mode", "N-gon mode", SESSION, "retop.toggle_ngon", {}, [_b('N')]),
    ("match_mode", "Side highlight", SESSION, "retop.toggle_match_mode", {}, [_b('M')]),
    # Both clicks, not just the Ctrl one: the *fallback* when no side is under
    # the cursor is the modal's (it commits), but taking the side is an action
    # like any other and there was never a reason for it to be fixed.
    ("pin_neighbour", "Match side to neighbour", SESSION, "retop.pin_side",
     {"source": False}, [_b('LEFTMOUSE')]),
    ("pin_source", "Match side to CAD edge", SESSION, "retop.pin_side",
     {"source": True}, [_b('LEFTMOUSE', ctrl=True)]),
    ("delete_patch", "Delete patch", SESSION, "retop.delete_patch", {}, [_b('X')]),
    ("commit", "Commit patch", SESSION, "retop.commit_patch", {},
     [_b('RET'), _b('NUMPAD_ENTER'), _b('RIGHTMOUSE')]),
    ("back", "Discard / back out", SESSION, "retop.back", {}, [_b('ESC')]),
    ("hand_edit", "Hand-edit mesh", SESSION, "retop.tweak_mesh", {}, [_b('TAB')]),
    ("end_tweak", "Back from hand-edit", SESSION, "retop.end_tweak", {}, [_b('TAB')]),
    ("cad_edges", "Plasticity edges", SESSION, "retop.toggle_cad_edges", {}, [_b('E')]),
    ("surface_flow", "Surface flow", SESSION, "retop.toggle_surface_flow", {},
     [_b('E', ctrl=True)]),
    ("local_view", "Isolate", GLOBAL, "retop.local_view", {},
     [_b('SLASH'), _b('NUMPAD_SLASH')]),
    ("mirror", "Mirror", GLOBAL, "retop.mirror", {}, [_b('X', alt=True)]),
    ("see_through", "Retopo X-ray", GLOBAL, "retop.toggle_see_through", {},
     [_b('X', shift=True)]),
)

ACTION_IDS = tuple(entry[0] for entry in ACTIONS)
_BY_ID = {entry[0]: entry for entry in ACTIONS}

# action id -> the KeyMapItems registered for it, filled by
# `operators._register_keymaps`. Held here rather than in `operators` so the
# overlay can read a live binding without importing that module -- a draw
# handler must never pull in the operators, which import it back.
_registered: dict[str, list[bpy.types.KeyMapItem]] = {}

# Event type -> what to call it on screen. Only the ones whose raw name would
# be unhelpful; anything else falls back to the name with its underscores
# turned into spaces, which covers the letters and the F-keys.
KEY_LABELS = {
    'RET': "Enter", 'NUMPAD_ENTER': "Enter (num)", 'ESC': "Esc",
    'BACK_SPACE': "Backspace", 'TAB': "Tab", 'SPACE': "Space",
    'LEFTMOUSE': "Click", 'RIGHTMOUSE': "R-Click", 'MIDDLEMOUSE': "M-Click",
    'WHEELUPMOUSE': "Wheel Up", 'WHEELDOWNMOUSE': "Wheel Down",
    'SLASH': "/", 'NUMPAD_SLASH': "Numpad /", 'BACK_SLASH': "\\",
    'COMMA': ",", 'PERIOD': ".", 'SEMI_COLON': ";", 'QUOTE': "'",
    'MINUS': "-", 'EQUAL': "=", 'GRLESS': "<",
    'LEFT_BRACKET': "[", 'RIGHT_BRACKET': "]",
}


def label_of(action_id: str) -> str:
    entry = _BY_ID.get(action_id)
    return entry[1] if entry else action_id


def scope_of(action_id: str) -> str:
    entry = _BY_ID.get(action_id)
    return entry[2] if entry else SESSION


def operator_of(action_id: str) -> str:
    entry = _BY_ID.get(action_id)
    return entry[3] if entry else ""


def properties_of(action_id: str) -> dict[str, object]:
    entry = _BY_ID.get(action_id)
    return dict(entry[4]) if entry else {}


def default_bindings(action_id: str) -> list[dict[str, object]]:
    entry = _BY_ID.get(action_id)
    # Copied: the caller may be about to edit what it is handed, and the
    # module-level default is shared by everything that asks.
    return [dict(binding) for binding in entry[5]] if entry else []


def _matches(kmi: bpy.types.KeyMapItem, event: object) -> bool:
    """Whether `event` is this item being pressed.

    Modifiers are compared *exactly*, not as a subset: a binding on bare `X`
    must not fire on `Alt+X`, which is the mirror. `kmi.any` is honoured
    because Blender's rows offer it and a user who ticks it means it.
    """
    if kmi.type != getattr(event, "type", None):
        return False
    if getattr(event, "value", None) != 'PRESS':
        return False
    if kmi.any:
        return True
    for name in ("ctrl", "shift", "alt", "oskey"):
        if bool(getattr(kmi, name)) != bool(getattr(event, name, False)):
            return False
    return True


def session_action_for(event: object) -> str | None:
    """The SESSION action `event` asks for, or None.

    The modal dispatches these itself rather than letting them fall through to
    the keymap -- see the module docstring for why a keymap item cannot be
    relied on to win against a mode keymap.
    """
    for action_id in ACTION_IDS:
        if scope_of(action_id) != SESSION:
            continue
        for kmi in items_for(action_id):
            if _matches(kmi, event):
                return action_id
    # Nothing registered (no addon keyconfig, i.e. --background): fall back to
    # the declaration, so the dispatch is still testable headless.
    if not _registered:
        for action_id in ACTION_IDS:
            if scope_of(action_id) != SESSION:
                continue
            for binding in default_bindings(action_id):
                if (binding["type"] == getattr(event, "type", None)
                        and getattr(event, "value", None) == 'PRESS'
                        and all(bool(binding.get(m)) == bool(getattr(event, m, False))
                                for m in ("ctrl", "shift", "alt"))):
                    return action_id
    return None


def remember(action_id: str, kmi: bpy.types.KeyMapItem) -> None:
    """Record a registered item so the overlay can read its live binding."""
    _registered.setdefault(action_id, []).append(kmi)


def forget_all() -> None:
    _registered.clear()


def items_for(action_id: str) -> list[bpy.types.KeyMapItem]:
    """The live KeyMapItems of an action, dropping any Blender has freed.

    A KeyMapItem's Python wrapper outlives the item when a keyconfig is rebuilt
    under it -- reading `.type` off one of those raises, and a draw handler is
    the worst place to find that out.
    """
    alive = []
    for kmi in _registered.get(action_id, []):
        try:
            _ = kmi.type
        except (ReferenceError, AttributeError):
            continue
        alive.append(kmi)
    return alive


def key_label(key: str) -> str:
    return KEY_LABELS.get(key, key.replace("_", " ").title() if len(key) > 1 else key)


def describe_binding(binding: dict[str, object]) -> str:
    """"Ctrl+Shift+X", from a declaration dict."""
    parts = []
    if binding.get("ctrl"):
        parts.append("Ctrl")
    if binding.get("shift"):
        parts.append("Shift")
    if binding.get("alt"):
        parts.append("Alt")
    parts.append(key_label(str(binding.get("type", ""))))
    return "+".join(parts)


def describe_item(kmi: bpy.types.KeyMapItem) -> str:
    """The same, from a live item -- so a remapped key reads as what it is now."""
    parts = []
    if kmi.ctrl:
        parts.append("Ctrl")
    if kmi.shift:
        parts.append("Shift")
    if kmi.alt:
        parts.append("Alt")
    if kmi.oskey:
        parts.append("OS")
    parts.append(key_label(kmi.type))
    return "+".join(parts)


def describe(action_id: str) -> str:
    """The first live binding of an action, falling back to its default.

    First rather than all of them: this feeds the viewport hint line, which is
    one row across the bottom of the screen and cannot afford to list three
    ways of committing. The fallback matters in `--background`, where there is
    no addon keyconfig at all and nothing was ever registered.
    """
    items = items_for(action_id)
    if items:
        return describe_item(items[0])
    defaults = default_bindings(action_id)
    return describe_binding(defaults[0]) if defaults else "unbound"


def describe_all(action_id: str) -> list[str]:
    """Every binding of an action, for the one hint that lists them."""
    items = items_for(action_id)
    if items:
        return [describe_item(kmi) for kmi in items]
    return [describe_binding(b) for b in default_bindings(action_id)]


def preferences() -> object | None:
    """The addon's preferences entry, or None when there is no addon entry.

    Read straight off the context rather than by importing `prefs`, which
    imports *this* module -- and this one has to stay a leaf the overlay can
    pull in. Returns None in the tests and in `--background`, where the package
    is imported plainly and has no addon entry to hang preferences on.
    """
    try:
        addon = bpy.context.preferences.addons.get(__package__)
    except AttributeError:
        return None
    return getattr(addon, "preferences", None) if addon else None


def global_keys_outside_session() -> bool:
    """Whether the GLOBAL keys mean anything with no session running.

    Off by default, and that default is what the GLOBAL/SESSION split costs
    otherwise: '/' , `Alt+X` and `Shift+X` are keys other addons bind too --
    Hard Ops above all, whose own `Alt+X` this one was modelled on -- and an
    addon that claims them from the moment it is installed is one that has to
    be *disabled* to get them back. A session running is the addon being used;
    with none, these operators' polls fail and Blender hands the key on to
    whoever else wants it, which is exactly what a failing poll does.

    A preference rather than a hard rule because the isolate and the mirror are
    genuinely useful between sessions, and the user who wants them back should
    not have to give up the addon to get them.
    """
    return bool(getattr(preferences(), "global_keys_outside_session", False))
