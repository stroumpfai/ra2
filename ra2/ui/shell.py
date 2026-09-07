# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
#
# NAV_ITEMS is seeded here because `create_app()` registers exactly these seven
# routes and the M0 exit criterion checks for them. A5 owns the rendering; the
# routes and the Import/Census copy are from design/nav-import-census/README.md
# and should not drift.
"""Header, 4 nav groups, 7 items, active state derived from the route."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Final

__all__ = ["NAV_ITEMS", "NAV_WIDTH_PX", "NavItem", "shell"]

#: sw-design.md §8.2 — load-bearing and asserted in E2E (J4).
NAV_WIDTH_PX: Final = 196


@dataclass(frozen=True, slots=True)
class NavItem:
    key: str
    group: str
    label: str
    path: str
    #: The header `h1`.
    title: str
    #: The one-line description under it. Exactly one line, no controls.
    description: str
    #: False -> routes to `placeholder_view` (sw-design.md §8.1.6).
    built: bool


#: The 4 groups x 7 items. Order is the nav's order.
#:
#: Import and Census copy is **verbatim** from the design README. The other five
#: views are not designed yet, so their copy is provisional and lands with the
#: view (phase 2); the route and the label are not.
NAV_ITEMS: Final[tuple[NavItem, ...]] = (
    NavItem(
        key="import",
        group="Data",
        label="Import",
        path="/import",
        title="Import",
        description="One delivery becomes one immutable corpus.",
        built=True,
    ),
    NavItem(
        key="census",
        group="Data",
        label="Census",
        path="/census",
        title="Census",
        description=("How populated each source column is — the basis for choosing features."),
        built=True,
    ),
    NavItem(
        key="codelists",
        group="Data",
        label="Codelists",
        path="/codelists",
        title="Codelists",
        description="Code and label per source column; labels are editable.",
        built=False,
    ),
    NavItem(
        key="features",
        group="Configure",
        label="Features",
        path="/features",
        title="Features",
        description="What to extract: labelled features and exploratory attributes.",
        built=False,
    ),
    NavItem(
        key="evaluation",
        group="Run",
        label="Evaluation",
        path="/evaluation",
        title="Evaluation",
        description="One corpus, one frozen feature config, N models.",
        built=False,
    ),
    NavItem(
        key="results",
        group="Review",
        label="Results",
        path="/results",
        title="Results",
        description="Per-feature, per-model precision, recall and F1, with intervals.",
        built=False,
    ),
    NavItem(
        key="mismatches",
        group="Review",
        label="Mismatches",
        path="/mismatches",
        title="Mismatches",
        description="Every wrong outcome, with its evidence span, for tagging.",
        built=False,
    ),
)


def shell(*, title: str, description: str, active: str) -> AbstractContextManager[None]:
    """Render header + nav and yield the content column.

    A5 builds this from `ui.element`, not `ui.card`/`ui.table`, wherever
    Quasar's defaults fight the design (R2), and will implement it with
    `@contextmanager` — which satisfies this return type.
    """
    raise NotImplementedError
