"""Names and small facts every layer of the addon has to agree on.

Generator names are the addon's real cross-module vocabulary: the panel, the
viewport overlay, the span registry and the commit path all branch on them, and
they are compared as *strings* because a generator is looked up by side count,
never held as a type. That makes a typo silent -- "Nside" simply matches
nothing and the patch quietly falls into the single-span branch.

This module exists so those strings, and the sets built from them, are written
once. It imports nothing from the package on purpose: `overlay` runs inside a
draw handler and must never reach `operators` (which imports it back), so a
leaf module is the only place both of them can share a constant.
"""

# --- generator names -------------------------------------------------------
#
# The value of `Generator.name` for each generator, and what
# `state.generator_name` holds while that generator is driving the preview.

QUAD = "Quad"
TRIANGLE = "Triangle"
WEDGE = "Wedge"
NSIDE = "N-Side"
RING = "Ring"
NGON = "N-gon"

# Generators driven by two spans, so Tab switches which one the wheel and the
# number keys adjust: quad U/V, wedge along/across, ring around/across.
# Everything else has a single span shared by all of its sides.
TWO_SPAN_GENERATORS = frozenset({QUAD, WEDGE, RING})

# How the two spans are labelled in the panel, per generator. Falls back to
# along/across, which is what a wedge's pair means.
SPAN_LABELS: dict[str, tuple[str, str]] = {
    QUAD: ("Span U", "Span V"),
    RING: ("Span (around)", "Span (across)"),
}
DEFAULT_SPAN_LABELS = ("Span (along)", "Span (across)")


def span_labels(generator_name: str) -> tuple[str, str]:
    return SPAN_LABELS.get(generator_name, DEFAULT_SPAN_LABELS)
