"""Parsing of Plasticity "patches" (CAD faces) out of the triangulated mesh
produced by the plasticity-blender-addon bridge.

The bridge stores two custom properties on the imported mesh:
  mesh["groups"]    -- flat list of [loop_start, loop_count] pairs, in polygon order
  mesh["face_ids"]  -- one Plasticity face id per group, same order as the pairs

A "patch" is the set of triangles that share one face_id. This module rebuilds,
for a given mesh, the polygon->face_id mapping and the boundary loop(s) of each
patch (the edges where a patch touches a different patch or the outer boundary
of the solid).

**Everything here is cached per mesh** (see `analyse`). The parse walks every
polygon, builds a KD-tree over every vertex and a directed-half-edge table over every triangle corner -- and the session used to redo all of it on *every mouse
move*, because hovering a patch re-prepares it. On a CAD part of any size that
is the difference between a smooth hover and a stuttering one. Nothing in a
Plasticity mesh changes while it is being retopologized, so the result is keyed
by a fingerprint of the mesh's own contents and reused until that changes.
"""
import array
import zlib
from dataclasses import dataclass, field


NO_NEIGHBOUR = None  # a boundary half-edge with no polygon on the other side


@dataclass
class Patch:
    face_id: int
    poly_indices: list  # polygon indices belonging to this patch
    # each boundary loop is an ordered list of vertex indices (loop[i] -> loop[i+1] is a boundary edge)
    boundary_loops: list = field(default_factory=list)
    # per loop, the face id on the other side of each boundary segment:
    # boundary_neighbours[k][i] faces segment loop[i] -> loop[(i+1) % n].
    # NO_NEIGHBOUR where the patch borders nothing (an open solid).
    boundary_neighbours: list = field(default_factory=list)


def polygon_face_ids(mesh):
    """Return a list mapping polygon index -> face_id, using mesh['groups']/['face_ids'].

    Mirrors the group-walking logic used by the bridge itself when it writes
    these attributes (handler.py: safe_mesh_import_data), so it stays correct
    even though group ranges are expressed in loop-index space while we index
    by polygon.
    """
    groups = mesh.get("groups")
    face_ids = mesh.get("face_ids")
    n_polys = len(mesh.polygons)

    if not groups or not face_ids:
        # No patch metadata (e.g. a plain, non-Plasticity mesh): treat everything
        # as a single patch so callers still have something to work with.
        return [0] * n_polys, [-1] if n_polys else []

    result = [0] * n_polys
    group_idx = 0
    group_start = groups[0]
    group_count = groups[1]

    for poly in mesh.polygons:
        while group_idx + 1 < len(face_ids) and poly.loop_start >= group_start + group_count:
            group_idx += 1
            group_start = groups[group_idx * 2]
            group_count = groups[group_idx * 2 + 1]
        result[poly.index] = face_ids[group_idx]

    return result, list(face_ids)


def build_patches(mesh):
    """Return ({face_id: Patch} with poly_indices filled in and boundary_loops
    still empty, polygon->face-id map, every declared face id).
    """
    face_id_of_poly, face_ids = polygon_face_ids(mesh)

    patches = {}
    for poly in mesh.polygons:
        fid = face_id_of_poly[poly.index]
        patch = patches.get(fid)
        if patch is None:
            patch = Patch(face_id=fid, poly_indices=[])
            patches[fid] = patch
        patch.poly_indices.append(poly.index)

    return patches, face_id_of_poly, face_ids


def _edge_key(a, b):
    return (a, b) if a < b else (b, a)


def build_weld_map(mesh, epsilon=1e-5):
    """Return a list mapping raw vertex index -> canonical "welded" vertex
    index, merging all vertices within `epsilon` of each other.

    The Plasticity bridge exports triangle soups where vertices are NOT
    shared even within a single CAD face (every triangle corner gets its own
    coincident-position vertex, e.g. for per-corner normals). Boundary/edge
    detection needs to treat coincident-position vertices as the same point,
    or literally every internal triangulation edge looks like a patch
    boundary. This mirrors a "Merge by Distance" pass, without actually
    modifying the mesh.
    """
    from mathutils.kdtree import KDTree

    n = len(mesh.vertices)
    kd = KDTree(n)
    for i, v in enumerate(mesh.vertices):
        kd.insert(v.co, i)
    kd.balance()

    weld_id = [-1] * n
    for i, v in enumerate(mesh.vertices):
        if weld_id[i] != -1:
            continue
        weld_id[i] = i
        for _co, idx, _dist in kd.find_range(v.co, epsilon):
            if weld_id[idx] == -1:
                weld_id[idx] = i

    return weld_id


def build_directed_owners(mesh, face_id_of_poly, weld_map=None):
    """(a, b) -> face id of the polygon that traverses that directed edge.

    This is the closest thing to edge identity the bridge makes available. The
    protocol carries no edge ids at all (only vertices/faces/normals/groups/
    face_ids), but a patch's boundary half-edge (a, b) is matched by the
    neighbouring patch's (b, a), so the *neighbour* of every boundary segment
    is recoverable -- and the vertex where that neighbour changes is a genuine
    B-rep vertex, the junction between two CAD edges.

    Built once per mesh and shared by every patch, since it is global.
    """
    if weld_map is None:
        weld_map = range(len(mesh.vertices))

    owners = {}
    for poly in mesh.polygons:
        face_id = face_id_of_poly[poly.index]
        verts = [weld_map[vi] for vi in poly.vertices]
        count = len(verts)
        for i in range(count):
            a = verts[i]
            b = verts[(i + 1) % count]
            if a != b:
                owners[(a, b)] = face_id
    return owners


def boundary_neighbours_for_loop(loop, face_id, directed_owners):
    """The face id across each segment of `loop`, segment i being
    loop[i] -> loop[(i + 1) % n]. `face_id` is the patch's own id, used to
    reject a match with itself (which a pinched boundary can produce).
    """
    count = len(loop)
    neighbours = []
    for i in range(count):
        a = loop[i]
        b = loop[(i + 1) % count]
        # The neighbour traverses the same edge the other way round.
        owner = directed_owners.get((b, a), NO_NEIGHBOUR)
        neighbours.append(NO_NEIGHBOUR if owner == face_id else owner)
    return neighbours


def compute_boundary_loops(mesh, patch, face_id_of_poly, weld_map=None,
                           directed_owners=None):
    """Fill patch.boundary_loops from patch.poly_indices.

    A boundary edge of the patch is an edge used by exactly one polygon of the
    patch on one winding direction and by no other polygon of the *same*
    patch on the other winding direction (i.e. it's a patch-to-patch or
    patch-to-void border, not an internal triangulation edge).

    `weld_map`, if given, maps each raw vertex index to a canonical index
    shared by all vertices at (nearly) the same position -- required for
    correct results on the Plasticity bridge's unwelded triangle soups (see
    build_weld_map). The returned loop indices are expressed in this same
    canonical space.
    """
    if weld_map is None:
        weld_map = range(len(mesh.vertices))  # identity mapping

    # directed_edge (a, b) -> True if some polygon of the patch has this
    # ordered edge in its loop (i.e. traverses a -> b along the polygon winding)
    directed_present = set()

    for poly_idx in patch.poly_indices:
        poly = mesh.polygons[poly_idx]
        verts = [weld_map[vi] for vi in poly.vertices]
        n = len(verts)
        for i in range(n):
            a = verts[i]
            b = verts[(i + 1) % n]
            if a == b:
                continue  # degenerate edge after welding
            directed_present.add((a, b))

    # A directed edge (a, b) is a boundary half-edge of the patch if the
    # reverse (b, a) is not also emitted by another polygon of this same
    # patch (that would mean it's shared internally, i.e. both sides belong
    # to the patch and cancel out).
    boundary_half_edges = {}
    for (a, b) in directed_present:
        if (b, a) not in directed_present:
            boundary_half_edges[a] = b

    # Walk the half-edges into closed loops.
    loops = []
    remaining = dict(boundary_half_edges)
    while remaining:
        start = next(iter(remaining))
        loop = [start]
        current = start
        while True:
            nxt = remaining.pop(current, None)
            if nxt is None:
                # open chain (shouldn't happen on a closed patch boundary) - stop
                break
            if nxt == start:
                break
            loop.append(nxt)
            current = nxt
        loops.append(loop)

    patch.boundary_loops = loops
    patch.boundary_neighbours = (
        [boundary_neighbours_for_loop(loop, patch.face_id, directed_owners)
         for loop in loops]
        if directed_owners is not None else []
    )
    return loops


def loop_extent(loop, positions):
    """Bounding-box diagonal of a boundary loop, in the mesh's own units."""
    if not loop:
        return 0.0
    xs = [positions[vi] for vi in loop]
    lo = [min(p[axis] for p in xs) for axis in range(3)]
    hi = [max(p[axis] for p in xs) for axis in range(3)]
    return sum((hi[axis] - lo[axis]) ** 2 for axis in range(3)) ** 0.5


def sort_loops_outer_first(loops, positions):
    """Order a patch's boundary loops with the outer one first.

    compute_boundary_loops walks a *set* of half-edges, so the order it returns
    depends on hash iteration -- on a patch with a hole, "the first loop" could
    just as easily be the hole. Anything picking a single loop must go through
    here, or it silently retopologizes the hole instead of the face. The outer
    boundary is the one enclosing the others, so it has the largest extent.
    """
    return sorted(loops, key=lambda loop: loop_extent(loop, positions), reverse=True)


@dataclass
class MeshPatches:
    """Everything one parse of a mesh produces, cached as a unit.

    Handed out read-only: callers may look at any of it, but anything that
    wants to *change* a patch must copy first, or the next hover inherits the
    edit. `positions` in particular is shared, which is why
    `generators.base.resolve_side_points` copies each point it hands on.
    """
    patches: dict          # face_id -> Patch, boundary loops already computed
    face_id_of_poly: list  # polygon index -> face id
    face_ids: list         # every face id the mesh declares, in group order
    weld_map: list         # raw vertex index -> canonical welded index
    directed_owners: dict  # (a, b) -> face id traversing that directed edge
    positions: dict        # vertex index -> Vector (mesh local space)


def mesh_fingerprint(mesh):
    """A cheap value that changes whenever the mesh's geometry does.

    Counts alone are not enough: the bridge re-imports into the *same*
    datablock, and a moved vertex with the topology untouched has to invalidate
    too. So the vertex coordinates go through a CRC -- one C-level
    `foreach_get` plus one CRC pass, which is orders of magnitude cheaper than
    the parse it guards (a KD-tree over the same vertices, and a Python loop
    over every triangle corner).
    """
    count = len(mesh.vertices)
    coords = array.array("f", bytes(4 * 3 * count))
    if count:
        mesh.vertices.foreach_get("co", coords)
    return (count, len(mesh.polygons), len(mesh.loops),
            len(mesh.get("face_ids") or ()), zlib.crc32(coords.tobytes()))


# mesh name -> (fingerprint, MeshPatches). Keyed by name rather than by the
# datablock so a dead mesh can never keep itself alive through this dict; a
# stale entry under a reused name is caught by the fingerprint anyway.
_cache = {}
_CACHE_LIMIT = 8  # a session works on one object; a few neighbours is plenty


def invalidate(mesh=None):
    """Drop the cached parse of `mesh`, or of everything when given nothing.

    Only needed when a mesh changes in a way the fingerprint cannot see -- it
    sees geometry, not the `groups`/`face_ids` custom properties being rewritten
    with identical counts. Called on addon reload and when a session ends.
    """
    if mesh is None:
        _cache.clear()
    else:
        _cache.pop(mesh.name, None)


def analyse(mesh, weld_epsilon=1e-5):
    """The full parse of `mesh`, from cache when the mesh has not changed.

    This is the entry point everything else should use: patches, their boundary
    loops, the polygon->face-id map, the weld map, the directed-owner table and
    the vertex positions all come out of one pass and are consistent with each
    other by construction.
    """
    fingerprint = mesh_fingerprint(mesh)
    cached = _cache.get(mesh.name)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]

    patches, face_id_of_poly, face_ids = build_patches(mesh)
    weld_map = build_weld_map(mesh, weld_epsilon)
    directed_owners = build_directed_owners(mesh, face_id_of_poly, weld_map)
    for patch in patches.values():
        compute_boundary_loops(mesh, patch, face_id_of_poly, weld_map, directed_owners)

    analysis = MeshPatches(
        patches=patches,
        face_id_of_poly=face_id_of_poly,
        face_ids=face_ids,
        weld_map=weld_map,
        directed_owners=directed_owners,
        positions={v.index: v.co.copy() for v in mesh.vertices},
    )

    if len(_cache) >= _CACHE_LIMIT:
        _cache.pop(next(iter(_cache)))
    _cache[mesh.name] = (fingerprint, analysis)
    return analysis


def get_patches_with_boundaries(mesh, weld_epsilon=1e-5):
    """{face_id: Patch} with boundary loops computed. Thin wrapper over
    `analyse` for callers that only want the patches.
    """
    return analyse(mesh, weld_epsilon).patches
