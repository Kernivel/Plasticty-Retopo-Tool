from . import base
from . import quad
from . import triangle
from . import wedge
from . import nside
from . import ring

# Order matters: the first generator whose matches() accepts the side count
# wins, so the specialised ones come before the general N-Side fallback.
GENERATORS = [
    wedge.WedgeGenerator(),
    triangle.TriangleGenerator(),
    quad.QuadGenerator(),
    nside.NSideGenerator(),
]

# Not in GENERATORS on purpose: a ring is recognised by its patch having two
# boundary loops, not by a side count, so operators reaches for it directly.
RING = ring.RingGenerator()


def find_generator(num_sides):
    for gen in GENERATORS:
        if gen.matches(num_sides):
            return gen
    return None
