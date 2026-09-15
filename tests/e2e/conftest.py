"""Layer-4 fixtures — a real server, a real Chromium (sw-design.md §11.5).

Owned by A5. One **session** server on a random port, built by the same
`create_app()` production uses, with a temp `RA2_DATA_DIR`, a `FrozenClock`
and a `SeededFactory` injected as keyword arguments. **There is no test mode
in production code** (§12.12, §3) — the substitutes go in through the
composition root's ordinary parameters.

One process may mount NiceGUI once (CONTRACTS.md M0-D6), which is the other
reason the server is session-scoped.

`demo_tables_url` is the J4 harness: the real Import layout — the
`minmax(0,1fr) minmax(0,1fr)` grid, two `.card`s, two `DataTable`s, two
pagination rows — driven by fixture rows instead of a `DeliveryService` whose
body is Wave 2's. The layout invariants J4 asserts belong to the shell and the
component kit, so they are asserted against the shell and the component kit;
wiring fixture rows into `import_view.py` to get the same coverage would be a
demo branch inside production code.
"""

import socket
import threading
import time
from argparse import Namespace
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from nicegui import ui
from tests.fixtures.fake_llm import (
    FakeLLMClient,
    StaticEndpointProber,
    StaticModelCatalog,
)

from ra2.infra.config import Settings
from ra2.infra.gpu import GpuInfo, StaticGpuProbe
from ra2.main import create_app
from ra2.services.readmodels import SortDir
from ra2.ui.components import (
    ColumnSpec,
    add_button,
    bar,
    card,
    card_header,
    data_table,
    distribution_bar,
    footnote,
    format_count,
    icon_button,
    pagination_row,
    tick,
)
from ra2.ui.components.icons import CLIPBOARD, REFRESH, TRASH
from ra2.ui.shell import shell
from ra2.ui.state import TableState

#: The J4 harness route. Underscored so it can never collide with a nav route.
DEMO_PATH = "/_demo/tables"

#: `tests/conftest.py`'s instant, repeated rather than imported: the root
#: conftest is frozen and pytest loads it as the module `conftest`, which is
#: not a name a sibling conftest should reach for (X8 — duplication inside an
#: owned path beats a shared-utility module five agents write to).
FROZEN_NOW = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)


class _FrozenClock:
    def now(self) -> datetime:
        return FROZEN_NOW


class _SeededFactory:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"id-{self._n:08d}"


# --- the J4 harness ---------------------------------------------------------


@dataclass(frozen=True)
class FileRow:
    name: str
    rows: int
    state: str
    state_class: str
    selected: bool = True


#: design/nav-import-census/README.md §1a, "Fixture data".
STRUCTURED_ROWS = (
    FileRow("vum_AG_unfall.txt", 1204, "ok", "ok"),
    FileRow("vum_AG_objekt.txt", 2981, "ok", "ok"),
    FileRow("vum_AG_person.txt", 3150, "ok", "ok"),
    FileRow("vum_BE_unfall.txt", 1876, "ok", "ok"),
    FileRow("vum_BE_objekt.txt", 4402, "2 rejected", "danger"),
    FileRow("vum_BE_person.txt", 4613, "ok", "ok"),
    FileRow("vum_VD_… (3 files)", 7848, "ok", "ok"),
)
TEXT_ROWS = (FileRow("Unfallhergang.csv", 4982, "3 recovered", "warn"),)

STRUCTURED_NOTE = (
    "Deselected files stay in the list and are excluded from the corpus. "
    "The report icon opens that file's parse findings; re-parse after changing "
    "its encoding or delimiter."
)
TEXT_NOTE = (
    "A UnfallUid collision attaches the wrong narrative — uniqueness is checked "
    "across the whole delivery."
)


def _columns() -> tuple[ColumnSpec[FileRow], ...]:
    """The Import file table, widths verbatim from README §1a."""
    return (
        ColumnSpec(
            key="selection",
            width="30px",
            header_style="padding-right:0;",
            cell_style="padding-right:0;",
            header_render=lambda: tick(checked=True, label="Select all"),
            render=lambda row: tick(checked=row.selected, label=f"Select {row.name}"),
        ),
        ColumnSpec(key="name", label="File", sortable=True, render=_render_name),
        ColumnSpec(
            key="rows",
            label="Rows",
            width="52px",
            align="right",
            sortable=True,
            cell_class="mono",
            render=lambda row: ui.label(format_count(row.rows)),
        ),
        ColumnSpec(
            key="state",
            label="State",
            width="86px",
            sortable=True,
            render=lambda row: ui.label(row.state).classes(row.state_class),
        ),
        ColumnSpec(
            key="action",
            width="92px",
            align="right",
            cell_style="padding-right:14px;",
            render=_render_actions,
        ),
    )


def _render_actions(row: FileRow) -> None:
    """The row's three actions (P3-D22), at the metrics `import_view` uses.

    J4 measures **this** table, so it has to be the same shape as the real
    one or the layout tripwire is measuring fiction.
    """
    with ui.element("div").style(
        "display:inline-flex;align-items:center;justify-content:flex-end;gap:4px;"
    ):
        icon_button(CLIPBOARD, label=f"Report for {row.name}", size=22, glyph=13, stroke=1.9)
        icon_button(REFRESH, label=f"Re-parse {row.name}", size=22, glyph=13, stroke=1.9)
        icon_button(
            TRASH,
            label=f"Delete {row.name}",
            size=22,
            glyph=13,
            stroke=1.9,
            extra_class="danger-hover",
        )


def _render_name(row: FileRow) -> None:
    with ui.element("div").style("display:flex;align-items:center;overflow:hidden;"):
        ui.label(row.name).classes("mono").style(
            "font-size:11.5px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;"
        )


def _file_card(
    *,
    title: str,
    count: str,
    count_class: str,
    rows: tuple[FileRow, ...],
    total: int,
    note: str,
    note_tone: str,
    add_label: str,
    testid: str,
) -> None:
    with card().props(f'data-card="{testid}"'):
        with card_header(title=title, count=count, count_class=count_class):
            add_button(label=add_label)
        # The **table well**: fixed 404px, so both cards are the same height
        # regardless of how many rows they hold (README §1a.2).
        with (
            ui.element("div")
            .props(f'data-testid="well-{testid}"')
            .style("height:404px;overflow:auto;flex:none;")
        ):
            data_table(
                columns=_columns(),
                rows=rows,
                state=TableState("name", SortDir.ASC, page=1, page_size=10),
                on_sort=lambda key: None,
                testid=f"table-{testid}",
            )
        pagination_row(state=TableState("name", page_size=10), total=total, shown=len(rows))
        footnote(note, tone=note_tone)


def _register_demo() -> None:
    @ui.page(DEMO_PATH)
    def _page() -> None:
        with shell(
            title="Import",
            description="One delivery becomes one immutable corpus.",
            active="import",
        ):
            with (
                ui.element("div")
                .props('data-testid="file-grid"')
                .style(
                    "display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);"
                    "gap:16px;align-items:start;"
                )
            ):
                _file_card(
                    title="Structured sets",
                    count="9 files · 9 selected",
                    count_class="",
                    rows=STRUCTURED_ROWS,
                    total=9,
                    note=STRUCTURED_NOTE,
                    note_tone="muted",
                    add_label="Add set",
                    testid="structured",
                )
                _file_card(
                    title="Text file",
                    count="1 file · 1 selected",
                    count_class="",
                    rows=TEXT_ROWS,
                    total=1,
                    note=TEXT_NOTE,
                    note_tone="info",
                    add_label="Add file",
                    testid="text",
                )
            # The two bar components, so their fixed sizes are assertable
            # without a Census view to hang them on.
            with card(), ui.element("div").style("padding:12px 14px;"):
                bar(fill_pct=81.3)
                distribution_bar(segments=(62, 26, 9, 3), legend="2 · 62 %  1 · 26 %  3 · 9 %")


# --- the server -------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


#: `tests/e2e/conftest.py` -> `tests/e2e` -> `tests` -> the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]


def _migrate(settings: Settings) -> None:
    """`alembic upgrade head` against the session server's own database.

    `create_app()` does not migrate — `just migrate` does — so without this
    every view that reads a service (from M6, Import is one) meets a database
    with no tables. The schema comes from the real migration chain here, the
    same way `tests/backend/conftest.py` and `tests/ui/conftest.py` get it;
    `metadata.create_all()` is banned in tests as much as in the app (§12.10).
    """
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "ra2" / "persistence" / "migrations"))
    # Mirrors what `-x url=...` would set from the CLI.
    config.cmd_opts = Namespace(x=[f"url={settings.database_url}"])
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)

    # On its own thread: `migrations/env.py` calls `asyncio.run`, and by the
    # time this session fixture runs, pytest-asyncio already has a loop on the
    # main thread — `asyncio.run` refuses to re-enter one. A fresh thread has
    # no loop, which is the whole trick.
    failures: list[BaseException] = []

    def _run() -> None:
        try:
            command.upgrade(config, "head")
        except BaseException as exc:  # re-raised on the calling thread below
            failures.append(exc)

    worker = threading.Thread(target=_run)
    worker.start()
    worker.join()
    if failures:
        raise failures[0]


@pytest.fixture(scope="session")
def server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A real RA2 on a random port, for the whole session."""
    data_dir: Path = tmp_path_factory.mktemp("ra2-e2e")
    settings = Settings(data_dir=data_dir, _env_file=None)
    _migrate(settings)
    _register_demo()
    app = create_app(
        settings=settings,
        clock=_FrozenClock(),
        ids=_SeededFactory(),
        # Phase 3: the LLM seam and the GPU probe are substituted here for the
        # same reason the clock and the id factory are — **no test in layers
        # 1-4 talks to a live endpoint or a real GPU** (plan-phase-3.md §11).
        # The whole suite has to pass on a machine with nothing listening on
        # 11434 and no NVIDIA card, and leaving the real adapters in would
        # make that a per-journey discipline instead of a property of the
        # fixture. They still go in through the composition root's ordinary
        # keyword arguments — there is no test mode in production code.
        llm_client=FakeLLMClient(),
        model_catalog=StaticModelCatalog(),
        endpoint_prober=StaticEndpointProber(),
        gpu_probe=StaticGpuProbe(GpuInfo(name="RTX 4090", total_vram_bytes=24_000_000_000)),
        mount_ui=True,
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the E2E server did not start within 30s")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)


@pytest.fixture
def demo_tables_url(server_url: str) -> str:
    """The J4 harness page: two `DataTable` cards side by side."""
    return f"{server_url}{DEMO_PATH}"
