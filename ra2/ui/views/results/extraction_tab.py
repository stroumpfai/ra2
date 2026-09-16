# STUB — signature only at M27, body owned by V1 (feat/p4-results-extraction).
"""Tab 1 — Goal 1, extraction (design/results/README.md §1).

The only tab with ground truth, and the input every other tab is read against.

Renders from `ExtractionTabView` alone. Three things it must get right, each
with a named test behind it:

- a **suppressed row** is tinted, its `n` is in `--danger`, and all three model
  cells are replaced by **one** `colspan` notice stating the count and the
  floor. Never a number in grey.
- the **breakdown** expands one feature at a time, and carries the
  "Hallucination is *not* computed — it is a review tag on the mismatch list"
  note **verbatim**. That is `D1` and §11.1's warning, not a caption: it
  renders even though the mismatch list is phase 5, which is how the product
  keeps a promise by not making a claim.
- the **by-language card's footer** is reproduced verbatim: the upstream
  encoding conversion drops characters commoner in French than in German,
  "**This cannot be quantified** — do not read the gap as a model weakness."
  mvp-spec.md §13 requires that standing caveat on the language breakdown.

`.mk` markers are **shape-coded** — filled / outlined / empty — on the neutral
accent (plan-phase-4.md §1 Q6, F9). Do not reach for a hue.

**M27 freezes the signature. V1 writes the body.**
"""

from ra2.services.readmodels import ExtractionTabView

__all__ = ["render_extraction_tab"]


def render_extraction_tab(*, view: ExtractionTabView) -> None:
    raise NotImplementedError
