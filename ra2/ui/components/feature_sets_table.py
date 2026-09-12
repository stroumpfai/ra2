# STUB — signature only at M9, body owned by G3 (feat/p2-feature-components).
"""The feature-sets strip below the Features split
(design/code-feature/README.md, Screen 2 · "Feature sets table").

Declared at M9 (plan-phase-2.md §3), same reasoning as `derivation_builder.py`
— G2 places this component; G3 owns its body in Wave 4.

`sets` is typed `FeatureSetSummary` (`services/readmodels.py`), not the
`FeatureSetView` name plan-phase-2.md §3's snippet used loosely — the actual
read model this wave defines is `FeatureSetSummary`; there is no second type
to reconcile.
"""

from collections.abc import Callable, Sequence

from nicegui.element import Element

from ra2.services.readmodels import FeatureSetSummary

__all__ = ["feature_sets_table"]


def feature_sets_table(
    *,
    sets: Sequence[FeatureSetSummary],
    selected_id: str | None,
    on_select: Callable[[str], None],
    on_rename: Callable[[str, str], None],
    on_delete: Callable[[str], None],
    on_new_set: Callable[[], None],
) -> Element:
    """`table-layout:fixed`, fixed-width content columns plus a trailing
    filler column that absorbs all remaining width (README, Screen 2).

    A locked row's rename/delete controls are **absent**, not merely
    disabled.
    """
    raise NotImplementedError
