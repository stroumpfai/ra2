# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
"""Per-client view state (sw-design.md §8.1.2).

**All view state lives in `app.storage.client`**, reached through the typed
dataclasses here. Module-level mutable state leaks between browser tabs and is
banned (§12.8).

`app.storage.client` is a per-browser-tab dict that NiceGUI drops when the tab
closes, which is exactly the lifetime a sort direction or a page number wants.
Nothing here reaches for a module global, and nothing here is a cache of
anything a service owns.
"""

from dataclasses import dataclass
from typing import Final

from nicegui import app

from ra2.services.readmodels import SortDir

__all__ = [
    "EVALUATION_KEY",
    "STORAGE_KEY",
    "EvaluationSetup",
    "TableState",
    "evaluation_setup",
    "set_evaluation_setup",
    "set_table_state",
    "table_state",
]

#: One namespace inside `app.storage.client`, so view state never collides
#: with anything NiceGUI itself keeps there.
STORAGE_KEY: Final = "ra2.tables"

#: The Evaluation view's own namespace, beside the tables' one.
EVALUATION_KEY: Final = "ra2.evaluation"


@dataclass(slots=True)
class TableState:
    """Sort and page for one table. Independent per table — the two Import
    tables never share sort state."""

    sort_key: str
    sort_dir: SortDir = SortDir.ASC
    page: int = 1
    page_size: int = 10

    def toggled(self, key: str) -> TableState:
        """The state after activating column `key`'s sort header.

        Clicking the active column flips direction; clicking another column
        sorts it ascending. Either way the page resets to 1 (README,
        Interactions). This decides *what to ask the service for* — it does
        not sort anything.
        """
        if key == self.sort_key:
            flipped = SortDir.DESC if self.sort_dir is SortDir.ASC else SortDir.ASC
            return TableState(key, flipped, 1, self.page_size)
        return TableState(key, SortDir.ASC, 1, self.page_size)


def table_state(
    name: str,
    *,
    sort_key: str,
    sort_dir: SortDir = SortDir.ASC,
    page_size: int = 10,
) -> TableState:
    """This client's `TableState` for the table called `name`, created on
    first use.

    Every table in the app gets its own entry, which is what makes the two
    Import tables' sort state independent (README, Interactions).
    """
    tables: dict[str, TableState] = app.storage.client.setdefault(STORAGE_KEY, {})
    if name not in tables:
        tables[name] = TableState(sort_key=sort_key, sort_dir=sort_dir, page_size=page_size)
    return tables[name]


def set_table_state(name: str, state: TableState) -> None:
    """Replace this client's `TableState` for `name`."""
    tables: dict[str, TableState] = app.storage.client.setdefault(STORAGE_KEY, {})
    tables[name] = state


# --- Phase 3 (Evaluation) additions -----------------------------------------
#
# Additive only: nothing above this line is touched. `TableState` covers a
# table's sort and page; the Evaluation view needs one more per-client fact —
# *which* evaluation this browser tab is looking at — plus the two picks that
# have to exist before the evaluation row does (design/prompt-evaluation/
# README.md §2, steps 1 and 2: "Save draft" is what creates the row, and the
# corpus and feature set it cites are chosen before it is pressed).


@dataclass(slots=True)
class EvaluationSetup:
    """Which evaluation this client is looking at, and the picks that precede
    it existing.

    All three are plain `str` rather than their `NewType` ids: this is a
    `app.storage.client` payload, and NiceGUI serialises it — a value that
    survives a round trip as a string is stored as one, and the view narrows
    it back to `CorpusId`/`FeatureConfigId`/`EvaluationId` at the service call,
    where the type is actually load-bearing.

    Empty (`EvaluationSetup()`) is the honest state of a fresh tab, and of a
    tab whose remembered evaluation has since been deleted.
    """

    #: `None` until an evaluation exists, or once the remembered one is gone.
    evaluation_id: str | None = None
    #: Step 1's pick while `evaluation_id` is `None`; afterwards the
    #: evaluation's own `corpus_id` is the truth and this is only an echo.
    corpus_id: str | None = None
    #: Step 2's pick, under the same rule.
    feature_config_id: str | None = None


def evaluation_setup() -> EvaluationSetup:
    """This client's `EvaluationSetup`, created empty on first use."""
    stored = app.storage.client.get(EVALUATION_KEY)
    if isinstance(stored, EvaluationSetup):
        return stored
    setup = EvaluationSetup()
    app.storage.client[EVALUATION_KEY] = setup
    return setup


def set_evaluation_setup(setup: EvaluationSetup) -> None:
    """Replace this client's `EvaluationSetup`."""
    app.storage.client[EVALUATION_KEY] = setup
