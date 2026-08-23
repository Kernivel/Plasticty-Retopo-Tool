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


def _result_shading_update(self, context):
    from . import mesh_build
    mesh_build.refresh_result_shading(context)


def _wire_opacity_update(self, context):
    from . import mesh_build
    mesh_build.apply_wireframe_opacity(context)


class RetopPatchState(bpy.types.PropertyGroup):
    active_face_id: bpy.props.IntProperty(name="Active Face Id", default=-1)
    generator_name: bpy.props.StringProperty(name="Generator", default="")
    num_sides: bpy.props.IntProperty(name="Num Sides", default=0)
    # Whether N-gon mode can run on the active patch at all: it needs a flat
    # face, and at most one hole. Written by the generation path, read by the
    # panel and the N keybind so both can say why rather than just do nothing.
    # Set when the corner detection produced a side count that should not be
    # trusted -- the angle test flagging every boundary vertex of a coarsely
    # tessellated circle, which is indistinguishable from a real polygon and so
    # is reported rather than silently overruled.
    corner_warning: bpy.props.StringProperty(name="Corner Warning", default="")
    # Why the generator in use is not the one the patch's shape would suggest --
    # currently only "this annulus is not a band", which routes a plate with a
    # small hole to the n-gon fill instead of a stretched ring.
    generator_note: bpy.props.StringProperty(name="Generator Note", default="")
    ngon_available: bpy.props.BoolProperty(name="N-gon Available", default=True)
    ngon_unavailable_reason: bpy.props.StringProperty(name="Why Not", default="")
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

    # N-gon mode: fill the patch with a single face following its boundary
    # instead of a span grid. Toggled with N during a session.
    ngon_mode: bpy.props.BoolProperty(
        name="N-gon", default=False,
        description="Fill the patch with one n-gon following its boundary instead of a span "
                     "grid. Meant for flat faces, where a grid is only wasted geometry. Not "
                     "available on a patch with a hole -- an n-gon has a single loop",
        update=_live_update,
    )
    ngon_angle: bpy.props.FloatProperty(
        name="N-gon Detail Angle", default=20.0, min=1.0, max=180.0,
        description="How much the boundary has to turn before N-gon mode keeps a vertex there. A "
                     "straight side stays a single edge whatever its length; a curve keeps one "
                     "vertex per this many degrees of arc; and a shallow feature that isn't sharp "
                     "enough to be a patch corner -- a chamfer, a crease -- is kept exactly where "
                     "it is as long as it turns more than this. Lower it to follow finer features",
        update=_live_update,
    )

    ngon_planar_tolerance: bpy.props.FloatProperty(
        name="N-gon Flatness Tolerance", default=5.0, min=0.0, max=90.0,
        description="How far a patch's own polygons may tilt from its average normal (degrees) "
                     "and still count as flat. N-gon mode is offered on flat faces only: a "
                     "single face across a curved surface is a flat lid over it, so a bevel or "
                     "a fillet silently loses its shape. Raise it to allow gently curved faces",
        update=_live_update,
    )
    auto_match_neighbours: bpy.props.BoolProperty(
        name="Match Committed Neighbours", default=True,
        description="Where a side of the patch is shared with a neighbour that has already been "
                     "retopologized, reuse that neighbour's own boundary vertices along it -- "
                     "their count and their exact positions -- so the two boundaries weld "
                     "instead of cracking. Applies to every generator: a grid copying only the "
                     "segment count still lands between the neighbour's vertices whenever the "
                     "neighbour didn't space them evenly. Only exact matches are taken "
                     "automatically; the Match Margin is for the sides you point at. Sides with "
                     "no committed neighbour are unaffected",
        update=_live_update,
    )
    # How many sides wanted to drive the same span with different counts on the
    # last generation. A grid has one count per direction, so only one of them
    # can win; the panel says so rather than letting the loser look matched.
    match_conflicts: bpy.props.IntProperty(name="Match Conflicts", default=0)
    ngon_show_verts: bpy.props.BoolProperty(
        name="Show N-gon Vertices", default=True,
        description="Draw a dot on every boundary vertex while adjusting an n-gon. A span grid "
                     "shows its own topology through its quads, but an n-gon is a single face, "
                     "so its vertices are the only thing there is to judge -- whether a chamfer "
                     "was picked up, whether a curve is dense enough",
    )
    ngon_vert_size: bpy.props.FloatProperty(
        name="Vertex Dot Size", default=11.0, min=2.0, max=40.0,
        description="Size of the N-gon vertex dots, in pixels",
    )

    # Two settings, not one, because the two modes want opposite things from a
    # corner. A grid's side count *chooses the generator*, so extra corners turn
    # a quad into an N-Side and its clean grid into a fan -- which is what
    # topological corners do to a bevel, whose long side borders face after
    # face. An n-gon just follows the boundary: extra corners cost nothing there
    # and are the only way a shallow chamfer survives.
    resolution: bpy.props.EnumProperty(
        name="Resolution",
        items=[
            ('VERY_LOW', "Very Low", "Quarter of the computed span count", '', 0),
            ('LOW', "Low", "Half the computed span count", '', 1),
            ('MID', "Mid", "The span count computed from the patch itself", '', 2),
            ('HIGH', "High", "Twice the computed span count", '', 3),
            ('EXTREME', "Extreme", "Four times the computed span count", '', 4),
        ],
        default='MID',
        description="Scales the span count a new patch starts at. The generators size a patch "
                     "from its own edge lengths, which is the right shape but not necessarily "
                     "the density you want -- this saves scrolling every patch back down to it. "
                     "It only sets the starting point: a span taken from a committed neighbour "
                     "still wins, or the two would not weld",
        update=_live_update,
    )

    corner_method_spans: bpy.props.EnumProperty(
        name="Corners (Grid)",
        items=[
            ('ANGLE', "Angle", "Corners where the boundary turns sharper than the threshold "
                               "below. The default for grids: it gives a bevel or a fillet the "
                               "four sides it should have", 'DRIVER_ROTATIONAL_DIFFERENCE', 0),
            ('BOTH', "Both", "Angle corners plus a corner wherever the neighbouring Plasticity "
                             "face changes. Follows the CAD more closely, but every extra corner "
                             "is an extra side, so a curved patch can end up as an N-Side fan",
             'CHECKBOX_HLT', 1),
            ('TOPOLOGY', "Topology", "Corners only where the neighbouring Plasticity face "
                                     "changes. Falls back to the angle test on a boundary that "
                                     "has no such junction", 'MOD_BOOLEAN', 2),
        ],
        default='ANGLE',
        description="How a patch boundary is split into sides for the span-based generators "
                     "(Quad, Triangle, Wedge, N-Side, Ring)",
        update=_live_update,
    )
    corner_method_ngon: bpy.props.EnumProperty(
        name="Corners (N-gon)",
        items=[
            ('BOTH', "Both", "Angle corners plus a corner wherever the neighbouring Plasticity "
                             "face changes. The default for n-gons: extra corners only add "
                             "boundary vertices, and they are what catches a chamfer too gentle "
                             "for the angle test", 'CHECKBOX_HLT', 0),
            ('TOPOLOGY', "Topology", "Corners only where the neighbouring Plasticity face "
                                     "changes. Falls back to the angle test on a boundary that "
                                     "has no such junction", 'MOD_BOOLEAN', 1),
            ('ANGLE', "Angle", "Corners where the boundary turns sharper than the threshold "
                               "below only. Shallow features are swallowed into a side",
             'DRIVER_ROTATIONAL_DIFFERENCE', 2),
        ],
        default='BOTH',
        description="How a patch boundary is split into sides in N-gon mode",
        update=_live_update,
    )

    corner_angle_threshold: bpy.props.FloatProperty(
        name="Corner Angle Threshold", default=135.0, min=1.0, max=179.0,
        description="Boundary turns sharper than this (degrees) are treated as corners",
        update=_live_update,
    )
    small_side_tolerance: bpy.props.FloatProperty(
        name="Small Side Tolerance", default=0.0, min=0.0, precision=4,
        description="Merge a boundary side shorter than this (in the Length Unit above) into "
                     "the next one, so a sliver left by the tessellation doesn't cost the patch "
                     "a whole extra side. 0 = never merge",
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
    result_shade_smooth: bpy.props.BoolProperty(
        name="Shade Smooth", default=True,
        description="Shade the committed retopology smooth and mark its creases sharp, so it "
                     "reads like the Plasticity model it was built from. Creases are the borders "
                     "between two patches that meet at more than the angle below -- a patch is "
                     "one CAD surface, so its own interior is never creased",
        update=_result_shading_update,
    )
    sharp_edge_angle: bpy.props.FloatProperty(
        name="Sharp Edge Angle", default=30.0, min=0.0, max=180.0,
        description="A border between two patches meeting at more than this angle (degrees) is "
                     "marked as a sharp edge. Raise it to keep more borders smooth (a fillet "
                     "running into the face it blends), lower it to crease more of them",
        update=_result_shading_update,
    )
    result_see_through: bpy.props.BoolProperty(
        name="See Retopo Through Meshes", default=True,
        description="Draw the retopology on top of everything else, so it stays visible through "
                     "the CAD surface and anything else in the scene. Off: it is occluded like "
                     "any other object, which is how you check it actually sits on the surface "
                     "rather than floating off it. Alt+X toggles it",
        update=_result_appearance_update,
    )
    result_show_wire: bpy.props.BoolProperty(
        name="Show Wireframe", default=True,
        description="Draw the retopology wireframe over its surface while a session is running. "
                     "With smooth shading on, this is what makes the topology readable at all. "
                     "Result meshes no session is working on never show a wireframe either way",
        update=_result_appearance_update,
    )
    result_wire_opacity: bpy.props.FloatProperty(
        name="Wireframe Opacity", default=0.5, min=0.0, max=1.0,
        description="Strength of the wireframe. Blender has no per-object setting for this: it "
                     "drives the 3D viewport's own Wireframe Opacity overlay, so it applies to "
                     "every object showing a wireframe in that viewport",
        update=_wire_opacity_update,
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

    # --- CAD structure display (see cad_display.py) ---------------------------
    #
    # The bridge sends a triangle soup: which triangles belong to which CAD face
    # is in the mesh, but nothing draws it, so a Plasticity import reads as one
    # undifferentiated field of triangles. These put the model's own structure
    # back on screen while a session runs.
    show_cad_edges: bpy.props.BoolProperty(
        name="Show CAD Edges", default=False,
        description="Draw the Plasticity edges -- the borders between CAD faces -- over the "
                     "source surface while a session runs. Rebuilt from the face ids the bridge "
                     "writes into the mesh, so it needs no live connection. E toggles it",
    )
    show_brep_vertices: bpy.props.BoolProperty(
        name="Show CAD Vertices", default=True,
        description="Dot every junction where two CAD edges meet -- a genuine B-rep vertex, as "
                     "opposed to the many boundary vertices the mesher put down. Those are the "
                     "points patches weld to each other by",
    )
    show_surface_flow: bpy.props.BoolProperty(
        name="Show Surface Flow", default=False,
        description="Draw the grid each CAD face would be retopologized into, at a low density. "
                     "Plasticity's own isoparametric curves are not in the bridge data -- the "
                     "protocol carries no surface parameters at all -- so these are derived from "
                     "each face's boundary by the same Coons interpolation the generators use. On "
                     "a fillet or a swept face they land very close to the real isoparms",
    )
    flow_density: bpy.props.IntProperty(
        name="Flow Density", default=3, min=1, max=12,
        description="Lines per direction in the surface flow display",
    )
    cad_display_scope: bpy.props.EnumProperty(
        name="Show For",
        items=[
            ('OBJECT', "Whole Object", "Every CAD face of the object being retopologized", '', 0),
            ('ACTIVE', "Active Patch", "Only the patch under the cursor", '', 1),
        ],
        default='OBJECT',
        description="How much of the CAD structure to draw. The whole object is what makes the "
                     "model's layout readable; one patch is what keeps a dense part legible",
    )
    cad_edge_color: bpy.props.FloatVectorProperty(
        name="CAD Edge Color", subtype='COLOR', size=3, default=(0.1, 0.9, 1.0),
        min=0.0, max=1.0, description="Colour of the Plasticity edge overlay",
    )
    cad_edge_width: bpy.props.FloatProperty(
        name="CAD Edge Width", default=2.0, min=0.5, max=10.0,
        description="Width of the Plasticity edge overlay, in pixels",
    )
    flow_color: bpy.props.FloatVectorProperty(
        name="Surface Flow Color", subtype='COLOR', size=3, default=(0.65, 0.45, 1.0),
        min=0.0, max=1.0, description="Colour of the surface flow overlay",
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
    match_margin: bpy.props.FloatProperty(
        name="Match Margin", default=2.0, min=0.0, max=25.0, subtype='PERCENTAGE',
        description="How far a committed retopology vertex may sit off a side, as a percentage "
                     "of that side's length, and still be offered as something to match. Raise "
                     "it to reach a neighbour whose edges have drifted from the CAD boundary -- "
                     "a coarse one whose chords cut across a curve, say. Only the sides you "
                     "point at use this margin: automatic matching stays exact, or it would "
                     "reach for whatever happens to be nearby",
        update=_live_update,
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

    # --- picking a neighbour to match (see operators.adopt_side_reference) ---
    #
    # A patch's automatic span comes from whichever committed neighbour the
    # propagation registry happens to answer for first, which is the wrong one
    # as often as not on a patch with several retopped neighbours. This is the
    # manual override: point at the shared boundary you actually want to match.
    match_mode: bpy.props.BoolProperty(
        name="Match Neighbour", default=True,
        description="Highlight the sides of the patch being adjusted, so clicking one matches "
                     "its committed neighbour's vertices. On by default: a left click has "
                     "nothing else to do while adjusting, so a click away from any side commits "
                     "and a click on one matches it. M turns the highlighting off",
    )
    # Index into the active patch's flattened side list (all loops, in order),
    # or -1. Written by the modal on mouse move, read by the overlay.
    hovered_side: bpy.props.IntProperty(name="Hovered Side", default=-1)
    # {flat side index: segment count} as JSON, for N-gon mode -- a grid has
    # nowhere to put a per-side count, so adopting a reference there writes
    # span_u/span_v/span directly. Cleared whenever the active patch changes.
    side_overrides: bpy.props.StringProperty(name="Side Overrides", default="")

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

    # --- output organisation ---
    mirror_source_collections: bpy.props.BoolProperty(
        name="Mirror Inbox Collections", default=True,
        description="File each <Object>_Retop mesh under a copy of the collection hierarchy the "
                     "source object has inside Plasticity's Inbox, rebuilt beneath the Retop "
                     "collection. The collections the bridge creates above Inbox are ignored. "
                     "Off: every result mesh sits flat at the top of Retop",
    )

    # --- viewport behaviour ---
    local_view_include_retop: bpy.props.BoolProperty(
        name="Keep Retopo in Isolate", default=True,
        description="When you isolate an object with '/', pull its <Object>_Retop mesh and the "
                     "live preview into the isolated view too. Off: '/' isolates the selection "
                     "on its own, hiding the retopology you're building",
    )

    # --- N-panel tabs (HardOps-style icon row) ---
    ui_tab: bpy.props.EnumProperty(
        name="Settings Tab",
        items=[
            ('PATCH', "Patch", "Corner detection and boundary welding", 'MOD_MESHDEFORM', 0),
            ('PICKER', "Picker", "How surfaces are picked in the viewport",
             'RESTRICT_SELECT_OFF', 1),
            ('DISPLAY', "Display", "Preview and result appearance, isolate behaviour",
             'SHADING_RENDERED', 2),
            ('OUTPUT', "Output", "Shading and collections of the committed mesh",
             'OUTLINER_COLLECTION', 3),
            ('KEYS', "Keybinds", "Keyboard and mouse bindings of the session", 'EVENT_A', 4),
            ('SYSTEM', "System", "Version and addon reloading", 'PREFERENCES', 5),
        ],
        default='PATCH',
    )

    overlay_scale: bpy.props.FloatProperty(
        name="Keybind Overlay Size", default=1.0, min=0.5, max=2.5,
        description="Size of the keybind hints drawn at the bottom of the viewport. They are "
                     "drawn in pixels, so they shrink on a 4K screen and crowd a small one",
    )

    # --- collapsible UI sections (sub-sections inside a tab) ---
    show_patch_settings: bpy.props.BoolProperty(name="Patch Settings", default=True)
    show_ngon_settings: bpy.props.BoolProperty(name="N-gon Mode", default=True)
    show_preview_appearance: bpy.props.BoolProperty(name="Preview Appearance", default=False)
    show_result_appearance: bpy.props.BoolProperty(name="Result Appearance", default=False)


# Multipliers for the Resolution preset. Powers of two, so each step is one
# subdivision level up or down -- a scale people already read by eye.
# Powers of two so each step is one subdivision level, times 0.75 across the
# board: what the generators compute from edge lengths reads about a quarter
# too dense in practice, and every preset was inheriting that.
RESOLUTION_TRIM = 0.75
RESOLUTION_FACTORS = {
    'VERY_LOW': 0.25 * RESOLUTION_TRIM,
    'LOW': 0.5 * RESOLUTION_TRIM,
    'MID': 1.0 * RESOLUTION_TRIM,
    'HIGH': 2.0 * RESOLUTION_TRIM,
    'EXTREME': 4.0 * RESOLUTION_TRIM,
}


def scale_default_spans(state, defaults):
    """Apply the Resolution preset to a generator's computed spans.

    Only ever the *computed* defaults: propagation from a committed neighbour
    and the spans a patch was committed with are both applied after this, and
    must both beat it -- scaling them would break the very welds they exist to
    make.
    """
    factor = RESOLUTION_FACTORS.get(state.resolution, 1.0)
    if factor == 1.0:
        return defaults
    return {key: max(1, int(round(value * factor))) if isinstance(value, int) else value
            for key, value in defaults.items()}


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
