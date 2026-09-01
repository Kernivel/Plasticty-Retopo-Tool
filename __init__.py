bl_info = {
    "name": "Plasticity Retop",
    "author": "",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > N-panel > Retop",
    "description": "Patch-based retopology assistant for meshes imported via the Plasticity bridge",
    "category": "Mesh",
}

from . import version
from . import constants
from . import patch_data
from . import sides
from . import geometry
from . import generators
from . import cad_display
from . import state
from . import mesh_build
from . import patchprep
from . import sidematch
from . import keymap
from . import tweak
from . import overlay
from . import operators
from . import prefs
from . import ui


def register() -> None:
    state.register()
    operators.register()
    # After the operators: the preferences page draws the keymap items they
    # registered, and an AddonPreferences whose draw finds nothing is a blank
    # page with no explanation.
    prefs.register()
    ui.register()


def unregister() -> None:
    ui.unregister()
    prefs.unregister()
    operators.unregister()
    state.unregister()
