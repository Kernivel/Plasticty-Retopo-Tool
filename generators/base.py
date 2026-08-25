"""Shared contract for retop generators.

A generator takes a patch's boundary sides (already split by sides.py) and
produces a preview mesh: a flat list of local-space Vector verts and a list
of faces (tuples of indices into that vert list, each face a tri or quad).
"""
from typing import TYPE_CHECKING, Any

import mathutils

if TYPE_CHECKING:
    from mathutils.bvhtree import BVHTree


class GenerationResult:
    __slots__ = ("verts", "faces", "uvs", "corner_local_indices", "boundary_local_indices",
                 "side_allocation")

    def __init__(
        self,
        verts: list[mathutils.Vector],
        faces: list[tuple[int, ...]],
        uvs: list[tuple[float, float]] | None = None,
        corner_local_indices: list[int] | None = None,
        boundary_local_indices: list[int] | None = None,
    ) -> None:
        # How many segments each side got, per boundary loop -- only the Ring
        # generator sets it (it spreads one "around" count over the sides
        # itself, so the commit path can't recompute it from a single span).
        # A Ring reports one list per loop; an N-gon a single flat list of its
        # sides' segment counts (both loops' concatenated, for a holed one).
        self.side_allocation: tuple[list[int], list[int]] | list[int] | None = None
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
    """A generator is identified by `name` (see constants) and selected by
    `matches`, never by a declared side count -- Ring and N-gon are reached
    directly, and the rest answer for a range.
    """

    name: str = "base"

    def matches(self, num_sides: int) -> bool:
        raise NotImplementedError

    def default_spans(self, sides: list[list[mathutils.Vector]]) -> dict[str, int]:
        """sides: list of point-lists (already resolved to Vectors, i.e. the
        output of resolve_side_points), walking the patch boundary in order.
        """
        raise NotImplementedError

    def generate(
        self,
        sides: list[list[mathutils.Vector]],
        span_settings: dict[str, Any],
        bvh: "BVHTree | None" = None,
    ) -> GenerationResult:
        """sides: list of vertex-index lists (one per patch side, walking the
        boundary in order, consecutive sides sharing their corner vertex).
        positions: dict vertex_index -> Vector (object space) is expected to
        already be baked into `sides` by the caller via `resolve_side_points`.
        """
        raise NotImplementedError


def resolve_side_points(
    sides: list[list[int]], positions: dict[int, mathutils.Vector]
) -> list[list[mathutils.Vector]]:
    """Convert vertex-index sides into Vector-point sides.

    Copies every point: `positions` is the per-mesh table cached by
    `patch_data.analyse`, shared by every caller, and a generator is free to
    hand its input straight through into a preview mesh -- `resample_polyline_
    by_arclength` returns the very objects it was given when the count already
    matches. Without the copy, generating one patch could move a vertex the
    next hover still believes is where the CAD put it.
    """
    return [[positions[vi].copy() for vi in side] for side in sides]
