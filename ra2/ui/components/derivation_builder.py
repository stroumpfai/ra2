# STUB — signature only at M9, body owned by G3 (feat/p2-feature-components).
"""Case C's closed-catalogue derivation builder
(design/code-feature/README.md, Screen 2 · Case C).

Declared at M9 (plan-phase-2.md §3) so G2 (the Features view) and G3 (this
component) can build in Wave 4 in parallel: G2 places this component and
wires `on_change` into the feature draft; G2 never reaches inside it.
"""

from collections.abc import Callable

from nicegui.element import Element

from ra2.domain.feature import DerivationSpec

__all__ = ["derivation_builder"]


def derivation_builder(
    *, value: DerivationSpec | None, on_change: Callable[[DerivationSpec], None]
) -> Element:
    """A tinted box of `.tok` chips: derivation type, its column/operator/
    value chips, and a "+ code" control — never free text (the catalogue is
    closed, mvp-spec.md §8.3).

    Round-trips a `DerivationSpec` through the chip UI without loss.
    """
    raise NotImplementedError
