import bpy


def _live_update(self, context):
    # Lazy import: operators.py isn't guaranteed to be loaded yet when this
    # module's properties are first registered (see __init__.py import order).
    from . import operators
    operators.regenerate_active_preview(context)


def _appearance_update(self, context):
    from . import mesh_build
    mesh_build.refresh_preview_appearance(context)


def _result_appearance_update(self, context):
    from . import mesh_build
    mesh_build.refresh_result_appearance(context)


class RetopPatchState(bpy.types.PropertyGroup):
    active_face_id: bpy.props.IntProperty(name="Active Face Id", default=-1)
    generator_name: bpy.props.StringProperty(name="Generator", default="")
    num_sides: bpy.props.IntProperty(name="Num Sides", default=0)
    # Boundary loops of the active patch: 1 is the usual case, 2 is a band
    # (a face with a hole, or a tube) handled by the Ring generator, and more
    # than 2 means only the outer boundary is used -- the panel says so.
    num_loops: bpy.props.IntProperty(name="Boundary Loops", default=1)
    source_object_name: bpy.props.StringProperty(name="Source Object", default="")
    # The active patch already existed in the result mesh: its geometry was
    # taken out when it was picked (see mesh_build.remove_patch_from_result)
    # and the snapshot below puts it back if the re-edit is discarded.
    editing_committed: bpy.props.BoolProperty(name="Re-editing Committed Patch", default=False)
    reedit_removed_faces: bpy.props.IntProperty(name="Faces Removed For Re-edit", default=0)
    # Cached for the panel: counting committed patches walks the result mesh's
    # face attribute, and the panel redraws on every mouse move during a session.
    committed_patch_count: bpy.props.IntProperty(name="Committed Patches", default=0)
    reedit_backup_mesh: bpy.props.StringProperty(name="Re-edit Snapshot", default="")
    reedit_result_object: bpy.props.StringProperty(name="Re-edit Result Object", default="")

    span_u: bpy.props.IntProperty(name="Span U", default=4, min=1, soft_max=64, update=_live_update)
    span_v: bpy.props.IntProperty(name="Span V", default=4, min=1, soft_max=64, update=_live_update)
    span: bpy.props.IntProperty(name="Span", default=4, min=1, soft_max=64, update=_live_update)
    span_axis: bpy.props.EnumProperty(
        name="Span Direction",
        items=[
            ('U', "U", "Scroll adjusts the U span"),
            ('V', "V", "Scroll adjusts the V span"),
        ],
        default='U',
        description="Which span the mouse wheel adjusts on a quad patch (Tab switches)",
    )

    corner_angle_threshold: bpy.props.FloatProperty(
        name="Corner Angle Threshold", default=135.0, min=1.0, max=179.0,
        description="Boundary turns sharper than this (degrees) are treated as corners",
        update=_live_update,
    )
    small_side_tolerance: bpy.props.FloatProperty(
        name="Small Side Tolerance", default=0.0, min=0.0,
        description="Merge boundary sides shorter than this length into a neighbor",
        update=_live_update,
    )
    reproject: bpy.props.BoolProperty(
        name="Reproject", default=True,
        description="Snap interior grid vertices onto the original CAD surface to follow curvature/fillets",
        update=_live_update,
    )

    preview_color: bpy.props.FloatVectorProperty(
        name="Preview Color", subtype='COLOR', size=3, default=(1.0, 0.45, 0.05),
        min=0.0, max=1.0, description="Albedo of the preview overlay material",
        update=_appearance_update,
    )
    preview_alpha: bpy.props.FloatProperty(
        name="Preview Alpha", default=0.6, min=0.0, max=1.0,
        description="Opacity of the preview overlay (Material Preview/Rendered shading; "
                     "in Solid shading, set the viewport's color mode to 'Object' to see it)",
        update=_appearance_update,
    )
    preview_offset: bpy.props.FloatProperty(
        name="Preview Offset", default=0.0, soft_min=-0.05, soft_max=0.05,
        description="Push the preview off the source surface along its normals, purely for "
                     "visibility -- cosmetic only, never baked into the committed result",
        update=_appearance_update,
    )

    result_color: bpy.props.FloatVectorProperty(
        name="Result Color", subtype='COLOR', size=3, default=(0.15, 0.55, 0.95),
        min=0.0, max=1.0, description="Albedo of the committed retopology result mesh",
        update=_result_appearance_update,
    )
    result_alpha: bpy.props.FloatProperty(
        name="Result Alpha", default=1.0, min=0.0, max=1.0,
        description="Opacity of the committed retopology result mesh (Material Preview/Rendered "
                     "shading; in Solid shading, set the viewport's color mode to 'Object' to see it)",
        update=_result_appearance_update,
    )
    result_offset: bpy.props.FloatProperty(
        name="Result Offset", default=0.0, min=0.0, soft_max=10.0, precision=4,
        description="Lift the committed retopology off the CAD surface along its normals so the two "
                     "don't z-fight in the viewport (in the Length Unit above). 0 = automatic "
                     "(0.1%% of the source object's size). Viewport-only: it's a Displace modifier "
                     "with rendering disabled, so the stored geometry stays exactly on the surface",
        update=_result_appearance_update,
    )
    highlight_all_results: bpy.props.BoolProperty(
        name="Show All Retopo", default=True,
        description="While a session is running, show every retopology mesh in the scene (not just "
                     "the one being worked on), dimmed with the alpha below",
        update=_result_appearance_update,
    )
    inactive_result_alpha: bpy.props.FloatProperty(
        name="Other Retopo Alpha", default=0.25, min=0.0, max=1.0,
        description="Opacity of the retopology meshes that aren't the one currently being worked on",
        update=_result_appearance_update,
    )

    length_unit: bpy.props.EnumProperty(
        name="Length Unit",
        items=[
            ('MM', "Millimeters", "Distances below are in mm", '', 0),
            ('CM', "Centimeters", "Distances below are in cm", '', 1),
            ('M', "Meters", "Distances below are in m (Blender's default: 1 unit = 1 m)", '', 2),
            ('IN', "Inches", "Distances below are in inches", '', 3),
            ('FT', "Feet", "Distances below are in feet", '', 4),
        ],
        default='M',
        description="Unit the distance settings below are typed in. Blender's own unit is 1 metre, "
                     "so pick the unit your CAD model is authored in and type real-world values",
    )
    pick_depth_tolerance: bpy.props.FloatProperty(
        name="Pick Depth Tolerance", default=0.0, min=0.0, soft_max=100.0, precision=4,
        description="When the picker finds a different patch than the one currently hovered, two "
                     "hits closer together than this (in the Length Unit above) count as the same "
                     "depth and the hover stays put, instead of flip-flopping between overlapping "
                     "surfaces. 0 = automatic (proportional to view distance)",
    )
    pick_max_distance: bpy.props.FloatProperty(
        name="Pick Max Distance", default=0.0, min=0.0, soft_max=100000.0,
        description="Ignore anything farther than this (in the Length Unit above) from the "
                     "viewpoint when picking. 0 = no limit",
    )

    boundary_weld_distance: bpy.props.FloatProperty(
        name="Boundary Weld Distance", default=1e-4, min=0.0, soft_max=100.0, precision=4,
        description="Merge distance (in the Length Unit above) used to stitch a newly committed "
                     "patch's boundary onto an already-committed neighbor's matching boundary. "
                     "Increase if a shared edge with matching spans still shows as a crack instead "
                     "of fully welding",
    )

    # --- retop session (see operators.RETOP_OT_session) ---
    session_active: bpy.props.BoolProperty(name="Session Active", default=False)
    session_object_name: bpy.props.StringProperty(name="Session Object", default="")
    session_phase: bpy.props.EnumProperty(
        name="Session Phase",
        items=[
            ('OBJECT', "Pick an object", "Waiting for you to click a Plasticity object"),
            ('PATCH', "Pick a surface", "Waiting for you to click a patch on the current object"),
            ('ADJUST', "Adjust & commit", "Tweaking spans on the picked patch"),
        ],
        default='OBJECT',
    )

    # --- collapsible UI sections ---
    show_keybinds: bpy.props.BoolProperty(name="Keybinds", default=False)
    show_patch_settings: bpy.props.BoolProperty(name="Patch Settings", default=False)
    show_picker_settings: bpy.props.BoolProperty(name="Picker Settings", default=False)
    show_preview_appearance: bpy.props.BoolProperty(name="Preview Appearance", default=False)
    show_result_appearance: bpy.props.BoolProperty(name="Result Appearance", default=False)


# Blender's own length unit is 1 metre, so these convert a value typed in the
# chosen unit into Blender units.
UNIT_TO_BLENDER = {
    'MM': 0.001,
    'CM': 0.01,
    'M': 1.0,
    'IN': 0.0254,
    'FT': 0.3048,
}


def to_blender_units(state, value):
    """Convert `value`, typed in state.length_unit, into Blender units."""
    return value * UNIT_TO_BLENDER.get(state.length_unit, 1.0)


CLASSES = (RetopPatchState,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.plasticity_retop = bpy.props.PointerProperty(type=RetopPatchState)


def unregister():
    del bpy.types.Scene.plasticity_retop
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
