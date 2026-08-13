"""Shared contract for retop generators.

A generator takes a patch's boundary sides (already split by sides.py) and
produces a preview mesh: a flat list of local-space Vector verts and a list
of faces (tuples of indices into that vert list, each face a tri or quad).
"""


class GenerationResult:
    __slots__ = ("verts", "faces", "uvs", "corner_local_indices", "boundary_local_indices")

    def __init__(self, verts, faces, uvs=None, corner_local_indices=None, boundary_local_indices=None):
        self.verts = verts  # list[Vector], local/object space
        self.faces = faces  # list[tuple[int, ...]]
        self.uvs = uvs if uvs is not None else [(0.0, 0.0)] * len(verts)  # list[(u, v)], one per vert
        # local vert index of each patch corner, in boundary-walk order (one
        # per side). Corners are always exact, un-resampled source mesh
        # vertices, so they are the only points safe to weld by identity
        # across neighboring patches (see mesh_build.commit_preview_to_result).
        self.corner_local_indices = corner_local_indices or []
        # local vert index of every point lying on ANY boundary side (corners
        # included). With propagation keeping spans equal on both sides of a
        # shared edge, these coincide almost exactly between neighboring
        # patches -- safe to weld by proximity (unlike interior/reprojected
        # points, which are never included here).
        self.boundary_local_indices = boundary_local_indices or []


class Generator:
    name = "base"
    num_sides = None  # int, or None if the generator accepts a range

    def matches(self, num_sides):
        raise NotImplementedError

    def default_spans(self, sides):
        """sides: list of point-lists (already resolved to Vectors, i.e. the
        output of resolve_side_points), walking the patch boundary in order.
        """
        raise NotImplementedError

    def generate(self, sides, span_settings, bvh=None):
        """sides: list of vertex-index lists (one per patch side, walking the
        boundary in order, consecutive sides sharing their corner vertex).
        positions: dict vertex_index -> Vector (object space) is expected to
        already be baked into `sides` by the caller via `resolve_side_points`.
        """
        raise NotImplementedError


def resolve_side_points(sides, positions):
    """Convert vertex-index sides into Vector-point sides."""
    return [[positions[vi] for vi in side] for side in sides]
