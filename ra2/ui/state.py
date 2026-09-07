# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
"""Per-client view state (sw-design.md §8.1.2).

**All view state lives in `app.storage.client`**, reached through the typed
dataclasses here. Module-level mutable state leaks between browser tabs and is
banned (§12.8).
"""

from dataclasses import dataclass

from ra2.services.readmodels import SortDir

__all__ = ["TableState"]


@dataclass(slots=True)
class TableState:
    """Sort and page for one table. Independent per table — the two Import
    tables never share sort state."""

    sort_key: str
    sort_dir: SortDir = SortDir.ASC
    page: int = 1
    page_size: int = 10
