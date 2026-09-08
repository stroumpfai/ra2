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

__all__ = ["STORAGE_KEY", "TableState", "set_table_state", "table_state"]

#: One namespace inside `app.storage.client`, so view state never collides
#: with anything NiceGUI itself keeps there.
STORAGE_KEY: Final = "ra2.tables"


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
