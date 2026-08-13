from . import base
from . import quad
from . import triangle
from . import wedge
from . import nside

# Order matters: the first generator whose matches() accepts the side count
# wins, so the specialised ones come before the general N-Side fallback.
GENERATORS = [
    wedge.WedgeGenerator(),
    triangle.TriangleGenerator(),
    quad.QuadGenerator(),
    nside.NSideGenerator(),
]


def find_generator(num_sides):
    for gen in GENERATORS:
        if gen.matches(num_sides):
            return gen
    return None
