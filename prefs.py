"""The addon's preferences page, which is where the keybinds live.

Drawn with `rna_keymap_ui.draw_kmi` -- Blender's own keymap rows, the ones the
keymap editor uses. Not a stylistic choice: the keys *are* real `KeyMapItem`s
(see keymap.py), so this is simply the widget that edits them. Anything else
would be a second, worse keymap editor drawn next to the real one, which is
what the hand-rolled version in the N-panel had become.

Everything the rows offer comes free with them: the modifier toggles, the
key-type dropdown, the map-type switch between Keyboard and Mouse, the per-item
enable checkbox, and the restore-to-default arrow that appears once an item is
user-modified. None of it is this module's to implement, and the same items
show up under Preferences > Keymap > Add-ons for anyone who never opens this
page.

The N-panel's Keybinds tab is a button that opens this, plus the read-only list
of what is *not* remappable. That split is the point: a tab that tried to edit
fifteen bindings in a 300px column was unreadable, and the columns stretched to
whatever the longest key label happened to be.
"""
import bpy

from . import keymap


def _addon_keymap_items() -> list[tuple[bpy.types.KeyMap, bpy.types.KeyMapItem]]:
    """The addon's registered items, newest registration first in ACTIONS order.

    Read from the registry `operators._register_keymaps` fills rather than by
    walking the keyconfig: two of our items can share a key and an operator
    (the two wheel directions of `retop.nudge_span`), so matching them back by
    idname alone would pair them up wrong.
    """
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return []
    km = keyconfig.keymaps.get('3D View')
    if km is None:
        return []
    pairs = []
    for action_id in keymap.ACTION_IDS:
        for kmi in keymap.items_for(action_id):
            pairs.append((km, kmi))
    return pairs


def draw_keymap(layout: bpy.types.UILayout) -> None:
    """The keybind rows. Shared by the preferences page and nothing else yet."""
    import rna_keymap_ui  # Blender ships it; imported lazily, it is UI-only

    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        layout.label(text="No addon keyconfig in this Blender", icon='ERROR')
        return

    km = keyconfig.keymaps.get('3D View')
    if km is None or not keymap.items_for(keymap.ACTION_IDS[0]):
        layout.label(text="Keybinds are not registered", icon='ERROR')
        layout.label(text="Re-enable the addon, or use Reload Addon Only.")
        return

    column = layout.column()
    for action_id in keymap.ACTION_IDS:
        items = keymap.items_for(action_id)
        if not items:
            continue
        row = column.row()
        # The label in its own fixed-width split rather than inside the row:
        # `draw_kmi` builds a full-width block, and putting a label beside it
        # in a plain row makes every column as wide as the longest key name.
        split = row.split(factor=0.25)
        split.label(text=keymap.label_of(action_id))
        body = split.column()
        for kmi in items:
            rna_keymap_ui.draw_kmi(
                ["ADDON", "USER", "DEFAULT"], keyconfig, km, kmi, body, 0)


class RETOP_AddonPreferences(bpy.types.AddonPreferences):
    # Must be the package name for Blender to attach this to the addon entry.
    bl_idname = __package__

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text="Keybinds", icon='EVENT_A')
        layout.label(
            text="Also under Preferences > Keymap > Add-ons > 3D View",
            icon='INFO')
        draw_keymap(layout)


CLASSES = (RETOP_AddonPreferences,)


def register() -> None:
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            # Running from a plain import rather than as an installed addon
            # (the tests do): there is no addon entry for these preferences to
            # attach to, and that must not take the rest of the addon down.
            pass


def unregister() -> None:
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
