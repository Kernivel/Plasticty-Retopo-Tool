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
from . import patch_data
from . import sides
from . import geometry
from . import generators
from . import state
from . import mesh_build
from . import overlay
from . import operators
from . import ui


def register():
    state.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    state.unregister()
