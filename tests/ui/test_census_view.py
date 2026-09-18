"""Layer 3 — the Census view (sw-design.md §11.3, "census").

Exactly the bullet list §11.3 names, against the **real** view driven by the
**real** services over a real migrated temp-file SQLite database:

- each chip refilters and resets to page 1;
- default sort is Populated ▼;
- in-config rows are tinted;
- "use as feature" links to Features with the column preselected.

Nothing here stubs a service. `seeded` registers and analyses the committed
hazard files through `DeliveryService` and freezes them into a corpus through
`CorpusService`, which is what materialises the census (SD2) — so every number
the view renders was computed by the pipeline under test, not by a fixture.

**Two of the four bullets need a note.**

`in_config` is `False` on every `CensusColumnView` **this file's fixtures**
produce: the `seeded` fixture only registers, analyses and freezes a
delivery through `DeliveryService`/`CorpusService` — it creates no `Feature`
row, and `in_config` is real from phase 2 on (`CensusService` computes it
from `feature.source_column`), so a column with no feature naming it is
correctly untinted here, not untinted because nothing could ever populate
it. Faking a service to manufacture a tinted row would test the fake. So
the tint is asserted where it is actually decided — the real `ColumnSpec`s
and the real row decorators, rendered by the real `DataTable` onto a harness
page in this file, the same shape as `tests/e2e/conftest.py`'s J4 harness.
`test_no_real_column_is_in_config_in_phase_1` pins the other half: against
this fixture set's data (no features), the tinted path is never taken.

"use as feature" is asserted as a **real link** whose target names the corpus
and the column, which is the whole hand-off: what Features then does with the
two parameters is `tests/ui/test_features_view.py`'s, and the loop closing
back onto a tinted row is J8's.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.element import Element
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction

from ra2.domain.census import BUCKET_ORDER, TypeHint, ValueCount
from ra2.domain.delivery import DeliveryStatus, SourceKind
from ra2.domain.ids import CensusColumnId, CorpusId
from ra2.infra.config import Settings
from ra2.services.container import Services
from ra2.services.readmodels import CensusColumnView, SortDir
from ra2.ui.components import data_table
from ra2.ui.state import TableState
from ra2.ui.views.census_view import (
    BUCKET_LABELS,
    NO_CORPUS_MESSAGE,
    PAGE_SIZE,
    REMINDER_BODY,
    TOOLBAR_CAPTION,
    WITHHELD_LEGEND,
    _census_columns,
    _row_class,
    _row_style,
)

pytestmark = pytest.mark.ui

#: `tests/ui/` -> `tests/`.
_TESTS_ROOT = Path(__file__).resolve().parents[1]
_HAZARDS = _TESTS_ROOT / "fixtures" / "deliveries" / "hazards"

#: One complete cantonal set — `unfall`, `objekt` and `person` — so all three
#: options of the table chip have a real column count behind them, and h08's
#: all-empty column so the profile card's `empty` bucket is not a rendering of
#: zero. Filenames are arbitrary on purpose: kind and canton come from the
#: data (§12.5).
DELIVERY: dict[str, str] = {
    "one.txt": "h08_all_empty_column/unfall.txt",
    "two.txt": "h10_count_mismatch/objekt.txt",
    "three.txt": "h10_count_mismatch/person.txt",
}

#: The harness route for the tinting assertion. Underscored so it can never
#: collide with a nav route, exactly as `tests/e2e/conftest.py`'s J4 page is.
IN_CONFIG_PATH = "/_census/in-config"
#: Risk B1 — one row per sample state: shown, withheld, genuinely empty.
SAMPLE_PATH = "/_census/sample-rule"
#: A column flagged withheld that still carries its values — a state the
#: service never produces, used to prove the view does not rely on it.
CONTRADICTORY_PATH = "/_census/withheld-with-values"
SECRET_VALUE = "2601234.5"

TINTED_COLUMN = "WitterungAusw"
PLAIN_COLUMN = "UnfallTypAusw"
CODED_COLUMN = "Witter0Ausw"
WITHHELD_COLUMN = "Koordinate X"
EMPTY_COLUMN = "StrasseName"

#: The harness page renders the real `ColumnSpec`s, and the action column's
#: link carries a corpus id — this one is never resolved, because the harness
#: never follows the link (`test_use_as_feature_links_to_features` does, on
#: the real view against the real corpus).
HARNESS_CORPUS_ID = CorpusId("corpus-harness")


@dataclass(frozen=True)
class Seeded:
    user: User
    services: Services
    corpus_id: CorpusId


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def delivery_root(tmp_path: Path) -> Path:
    """`DELIVERY` on disk, byte-for-byte, ready to register as a host path."""
    root = tmp_path / "census-delivery"
    root.mkdir(parents=True)
    for name, source in DELIVERY.items():
        (root / name).write_bytes((_HAZARDS / source).read_bytes())
    return root


@pytest.fixture
async def seeded(
    app_factory: Callable[..., FastAPI],
    migrated_db: Settings,
    delivery_root: Path,
) -> AsyncIterator[Seeded]:
    """The real UI-mounted app with one frozen corpus, census and all."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        _register_in_config_harness()
        _register_sample_rule_harness()
        try:
            app = app_factory(mount_ui=True)
            services: Services = app.state.services
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                delivery_id = await services.delivery.register(
                    "census", source_kind=SourceKind.HOST_PATH, root_path=delivery_root
                )
                await services.delivery.analyse(delivery_id)
                await _until_analysed(services, delivery_id)
                corpus_id = await services.corpus.freeze(delivery_id, name="census")
                yield Seeded(User(client), services, corpus_id)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            _restore_nicegui_functions()


@pytest.fixture
async def empty(app_factory: Callable[..., FastAPI], migrated_db: Settings) -> AsyncIterator[User]:
    """The same app with **no corpus at all** — the undesigned empty state."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                yield User(client)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            _restore_nicegui_functions()


def _restore_nicegui_functions() -> None:
    from nicegui.functions.download import download
    from nicegui.functions.navigate import Navigate
    from nicegui.functions.notify import notify

    ui.navigate = Navigate()
    ui.notify = notify
    ui.download = download


def _register_in_config_harness() -> None:
    """One `DataTable` over two rows, one of them `in_config`.

    The **real** `ColumnSpec`s and the **real** `_row_class` / `_row_style`,
    driven by two `CensusColumnView`s built here because phase 1's services
    cannot produce a configured column (see the module docstring). Registered
    before `create_app()`, exactly as the J4 harness is.
    """

    @ui.page(IN_CONFIG_PATH)
    def _page() -> None:
        data_table(
            columns=_census_columns(HARNESS_CORPUS_ID),
            rows=(
                _column_view(TINTED_COLUMN, in_config=True),
                _column_view(PLAIN_COLUMN, in_config=False),
            ),
            state=TableState("populated_rate", SortDir.DESC, 1, PAGE_SIZE),
            row_class=_row_class,
            row_style=_row_style,
            wide=True,
            testid="table-census",
        )


def _column_view(
    column_name: str,
    *,
    in_config: bool,
    type_hint: TypeHint = TypeHint.ENUM,
    top_values: tuple[ValueCount, ...] = (ValueCount(value_raw="1", count=2752, share=0.68),),
    top_values_withheld: bool = False,
) -> CensusColumnView:
    """README §2b's own fixture row, as the read model the service returns."""
    return CensusColumnView(
        census_column_id=CensusColumnId(f"cc-{column_name}"),
        table_name="unfall",
        column_name=column_name,
        type_hint=type_hint,
        record_count=4978,
        populated_count=4047,
        populated_rate=0.813,
        distinct_count=8,
        top_value_share=0.68,
        long_tail=False,
        top_values=top_values,
        in_config=in_config,
        top_values_withheld=top_values_withheld,
    )


def _register_sample_rule_harness() -> None:
    """One `DataTable` over the three states a sample can be in (risk B1).

    Built here rather than seeded, for the same reason the in-config harness
    is: the hazard fixtures contain no column that is both populated and
    uncoded enough to produce all three rows side by side, and the thing under
    test is the renderer's branch, not the pipeline that feeds it.
    """

    @ui.page(SAMPLE_PATH)
    def _page() -> None:
        data_table(
            columns=_census_columns(HARNESS_CORPUS_ID),
            rows=(
                _column_view(CODED_COLUMN, in_config=False),
                _column_view(
                    WITHHELD_COLUMN,
                    in_config=False,
                    type_hint=TypeHint.DECIMAL,
                    top_values=(),
                    top_values_withheld=True,
                ),
                _column_view(
                    EMPTY_COLUMN,
                    in_config=False,
                    type_hint=TypeHint.TEXT,
                    top_values=(),
                ),
            ),
            state=TableState("populated_rate", SortDir.DESC, 1, PAGE_SIZE),
            row_class=_row_class,
            row_style=_row_style,
            wide=True,
            testid="table-census",
        )

    @ui.page(CONTRADICTORY_PATH)
    def _contradictory() -> None:
        data_table(
            columns=_census_columns(HARNESS_CORPUS_ID),
            rows=(
                _column_view(
                    WITHHELD_COLUMN,
                    in_config=False,
                    type_hint=TypeHint.DECIMAL,
                    top_values=(ValueCount(value_raw=SECRET_VALUE, count=1, share=0.25),),
                    top_values_withheld=True,
                ),
            ),
            state=TableState("populated_rate", SortDir.DESC, 1, PAGE_SIZE),
            row_class=_row_class,
            row_style=_row_style,
            wide=True,
            testid="table-census",
        )


async def _until_analysed(services: Services, delivery_id: str) -> None:
    """`TaskRunner` returns immediately — and before the work it scheduled has
    started — so the seed waits for a **terminal** status, exactly as the
    Import view does."""
    for _ in range(500):
        delivery = await services.delivery.get(delivery_id)  # type: ignore[arg-type]
        if delivery.status in (DeliveryStatus.ANALYSED, DeliveryStatus.FAILED):
            assert delivery.status is DeliveryStatus.ANALYSED, delivery.status
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the delivery never finished analysing")


async def _until(predicate: Callable[[], bool]) -> None:
    """Poll until `predicate()` is true.

    A click's handler is dispatched but not awaited by `UserInteraction.click`,
    so an async handler's effects — a filter change, a sort, a page — are not
    guaranteed to be visible the instant `.click()` returns.
    """
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


# --- helpers -----------------------------------------------------------------


def _own_text(element: Element) -> str:
    """A `ui.label`'s own text. `Element` itself has no `text`, which is why
    this goes through `getattr` rather than a cast."""
    return str(getattr(element, "text", ""))


def _ordered(elements: Iterable[Element]) -> list[Element]:
    """NiceGUI hands out ids in creation order, which is document order here."""
    return sorted(elements, key=lambda e: e.id)


def _one(user: User, element: Element) -> UserInteraction[Element]:
    return UserInteraction(user, {element}, None)


def _find(user: User, testid: str) -> list[Element]:
    return _ordered(
        e for e in user.find(kind=ui.element).elements if e._props.get("data-testid") == testid
    )


def _table(user: User) -> Element:
    (table,) = user.find(marker="table-census").elements
    return table


def _within(root: Element, testid: str) -> list[Element]:
    return _ordered(e for e in root.descendants() if e._props.get("data-testid") == testid)


def _column_names(user: User) -> list[str]:
    return [_own_text(e) for e in _within(_table(user), "census-column-name")]


def _table_names(user: User) -> list[str]:
    return [_own_text(e) for e in _within(_table(user), "census-table-name")]


def _percentages(user: User) -> list[str]:
    return [_own_text(e) for e in _within(_table(user), "populated-pct")]


def _range_label(user: User) -> str:
    (label,) = user.find(marker="pagination-range").elements
    return _own_text(label)


def _chip(user: User, name: str) -> Element:
    (element,) = user.find(marker=f"chip-{name}").elements
    return element


def _chip_text(user: User, name: str) -> str:
    return " ".join(_own_text(c) for c in _chip(user, name).descendants()).strip()


async def _pick(user: User, chip: str, option: str) -> None:
    """Open a dropdown chip and choose one of its options."""
    _one(user, _chip(user, chip)).click()
    await _until(lambda: bool(_find(user, f"menu-{chip}")))
    button = next(e for e in _find(user, f"option-{chip}") if e._props.get("aria-label") == option)
    _one(user, button).click()
    await _until(lambda: not _find(user, f"menu-{chip}"))


def _sort_header(user: User, key: str) -> Element:
    (header,) = _within(_table(user), f"sort-{key}")
    return header


# --- §11.3: default sort is Populated ▼ --------------------------------------


async def test_the_default_sort_is_populated_descending(seeded: Seeded) -> None:
    """README §2b: "Sorted **descending** by default (`.sarr.on ▼`)".

    Asserted twice over — on the header's `aria-sort`, and on the rendered
    order, because the direction is a **service-call parameter** and the rows
    are whatever the service returned for it (§8.1.4).
    """
    user = seeded.user
    await user.open("/census")
    await user.should_see(TOOLBAR_CAPTION)

    assert _sort_header(user, "populated_rate")._props["aria-sort"] == "descending"
    for other in ("column_name", "table_name", "type_hint", "distinct_count"):
        assert _sort_header(user, other)._props["aria-sort"] == "none"

    rates = [float(text.removesuffix(" %").replace(" ", "")) for text in _percentages(user)]
    assert rates == sorted(rates, reverse=True)


async def test_a_sort_click_flips_the_direction(seeded: Seeded) -> None:
    """ "Sorting on Column / Table / Type hint / Populated / Distinct,
    two-direction" (README, Interactions)."""
    user = seeded.user
    await user.open("/census")
    _one(user, _sort_header(user, "populated_rate")).click()
    await _until(lambda: _sort_header(user, "populated_rate")._props["aria-sort"] == "ascending")

    rates = [float(text.removesuffix(" %").replace(" ", "")) for text in _percentages(user)]
    assert rates == sorted(rates)


# --- §11.3: each chip refilters and resets to page 1 -------------------------


async def test_the_table_chip_refilters_and_resets_to_page_one(seeded: Seeded) -> None:
    """README, Interactions: "changing any of them refilters and resets to
    page 1". The count on the chip is the census summary's, never counted from
    the page on screen (§8.1.1)."""
    user = seeded.user
    summary = await seeded.services.census.summary(seeded.corpus_id)
    unfall = summary.column_counts_by_table["unfall"]
    await user.open("/census")
    assert _range_label(user).endswith(f"of {summary.total_column_count}")

    # Turn to page 2 first, so "resets to page 1" is a change and not the
    # state the view was already in.
    (following,) = _find(user, "page-next")
    _one(user, following).click()
    await _until(lambda: _range_label(user).startswith(f"{PAGE_SIZE + 1}–"))

    await _pick(user, "table", f"table · unfall {unfall}")
    await _until(lambda: _range_label(user).startswith("1–"))

    assert _range_label(user).endswith(f"of {unfall}")
    assert set(_table_names(user)) == {"unfall"}
    assert _chip_text(user, "table") == f"table · unfall {unfall} ▼"


async def test_the_populated_chip_refilters_and_resets_to_page_one(seeded: Seeded) -> None:
    """ "populated ≥ all ▼" — the minimum fill-rate filter. The thresholds are
    this view's choice (the design shows only the "all" state); the filtering
    is the service's `min_populated_rate`."""
    user = seeded.user
    summary = await seeded.services.census.summary(seeded.corpus_id)
    await user.open("/census")

    (following,) = _find(user, "page-next")
    _one(user, following).click()
    await _until(lambda: _range_label(user).startswith(f"{PAGE_SIZE + 1}–"))

    await _pick(user, "populated", "populated ≥ 100 %")
    await _until(lambda: _range_label(user).startswith("1–"))

    assert _chip_text(user, "populated") == "populated ≥ 100 % ▼"
    fully = await seeded.services.census.columns(
        seeded.corpus_id, min_populated_rate=1.0, page_size=1
    )
    assert 0 < fully.total < summary.total_column_count
    assert _range_label(user).endswith(f"of {fully.total}")
    assert _percentages(user) == ["100 %"] * min(fully.total, PAGE_SIZE)


async def test_the_corpus_chip_refilters_and_resets_to_page_one(
    seeded: Seeded, delivery_root: Path
) -> None:
    """The first chip **is** the corpus selector (README §2a.1).

    A second corpus is frozen from a second delivery, so the chip has two real
    options and switching between them re-reads the census for the corpus the
    chip names.
    """
    user = seeded.user
    services = seeded.services
    other_id = await services.delivery.register(
        "census-2", source_kind=SourceKind.HOST_PATH, root_path=delivery_root
    )
    await services.delivery.analyse(other_id)
    await _until_analysed(services, other_id)
    second = await services.corpus.freeze(other_id, name="census-2")

    await user.open("/census")
    # Newest first, so the second corpus is the default (`_current_corpus`).
    assert _chip_text(user, "corpus").startswith("corpus census-2 · v")

    (following,) = _find(user, "page-next")
    _one(user, following).click()
    await _until(lambda: _range_label(user).startswith(f"{PAGE_SIZE + 1}–"))

    first = await services.corpus.get(seeded.corpus_id)
    await _pick(user, "corpus", f"corpus {first.name} · v{first.version}")
    await _until(lambda: _range_label(user).startswith("1–"))

    assert _chip_text(user, "corpus") == f"corpus {first.name} · v{first.version} ▼"
    assert second != seeded.corpus_id


# --- §11.3: in-config rows are tinted ----------------------------------------


async def test_in_config_rows_are_tinted(seeded: Seeded) -> None:
    """README §2b: "already-in-config rows are highlighted with
    `background:--accent-soft` and the column name at `font-weight:500`".

    Driven through the real `DataTable`, the real `ColumnSpec`s and the real
    row decorators — only the two rows are this test's, because phase 1 has no
    FeatureConfig to produce one (module docstring).
    """
    user = seeded.user
    await user.open(IN_CONFIG_PATH)
    rows = _ordered(e for e in _table(user).descendants() if e.tag == "tr")
    body = [row for row in rows if any(cell.tag == "td" for cell in row.default_slot.children)]
    tinted, plain = body

    assert "in-config" in tinted.classes
    assert tinted._style.get("background") == "var(--accent-soft)"
    assert "in-config" not in plain.classes
    assert "background" not in plain._style

    names = {_own_text(e): e for e in _within(_table(user), "census-column-name")}
    assert names[TINTED_COLUMN]._style.get("font-weight") == "500"
    assert "font-weight" not in names[PLAIN_COLUMN]._style


async def test_the_tinted_row_shows_in_config_instead_of_the_action(seeded: Seeded) -> None:
    """ "already-configured columns show "in config" instead" (README,
    Interactions) — one row each way, on the same harness."""
    user = seeded.user
    await user.open(IN_CONFIG_PATH)
    assert [_own_text(e) for e in _find(user, "in-config")] == ["in config"]
    assert len(_find(user, "use-as-feature")) == 1


async def test_no_column_is_in_config_without_a_feature(seeded: Seeded) -> None:
    """The other half of the tinting bullet: against the real service the
    tinted path is never taken, because this fixture set's delivery creates
    no `Feature` row naming any of its columns (`in_config` is real from
    phase 2 on — see the module docstring)."""
    user = seeded.user
    await user.open("/census")
    assert _find(user, "in-config") == []
    assert len(_find(user, "use-as-feature")) == len(_column_names(user))


# --- §11.3: "use as feature" links to Features -------------------------------


async def test_use_as_feature_links_to_features_with_the_column(seeded: Seeded) -> None:
    """README, Interactions: ""use as feature" navigates to Features with that
    column preselected".

    A `ui.link`, not a scripted button — the whole hand-off is the target,
    which carries the corpus being profiled and the column name and nothing
    else: `features_view` reads the column's table and type hint off the
    census itself. That the rendered element is an `<a href>` a browser
    follows is J5-style DOM ground truth, asserted in `tests/e2e`.
    """
    user = seeded.user
    await user.open("/census")
    actions = _find(user, "use-as-feature")
    assert actions
    names = _column_names(user)
    for action, name in zip(actions, names, strict=True):
        assert isinstance(action, ui.link)
        assert "disabled" not in action._props
        target = urlparse(str(action._props["href"]))
        assert target.path == "/features"
        assert parse_qs(target.query) == {
            "corpus": [seeded.corpus_id],
            "column": [name],
        }


# --- the design's own copy, layout and numbers -------------------------------


async def test_the_toolbar_carries_three_chips_a_caption_and_export(seeded: Seeded) -> None:
    """README §2a: three dropdown chips then the caption on the left, the
    "Export CSV" button pushed right by `margin-left:auto` on the group."""
    user = seeded.user
    summary = await seeded.services.census.summary(seeded.corpus_id)
    await user.open("/census")
    assert _chip_text(user, "corpus").startswith("corpus census · v")
    assert _chip_text(user, "populated") == "populated ≥ all ▼"
    assert _chip_text(user, "table") == f"table · all {summary.total_column_count} ▼"
    await user.should_see(TOOLBAR_CAPTION)

    (export,) = _find(user, "export-csv")
    assert "disabled" not in export._props
    (right_group,) = [
        e
        for e in user.find(kind=ui.element).elements
        if e._style.get("margin-left") == "auto" and export in e.descendants()
    ]
    assert right_group._style.get("flex") == "none"


async def test_the_table_chip_offers_all_three_source_tables_with_live_counts(
    seeded: Seeded,
) -> None:
    """ "Options: All · 162 columns / unfall · 67 / objekt · 77 / person · 18"
    (README §2a.3) — every count from `CensusSummary`."""
    user = seeded.user
    summary = await seeded.services.census.summary(seeded.corpus_id)
    await user.open("/census")
    _one(user, _chip(user, "table")).click()
    await _until(lambda: bool(_find(user, "menu-table")))

    labels = [str(e._props["aria-label"]) for e in _find(user, "option-table")]
    assert labels == [
        f"table · all {summary.total_column_count}",
        *(
            f"table · {name} {summary.column_counts_by_table[name]}"
            for name in ("unfall", "objekt", "person")
        ),
    ]


async def test_the_profile_card_renders_the_six_buckets(seeded: Seeded) -> None:
    """README §2c: the six buckets of `BUCKET_ORDER`, each a number and a
    label, over all tables. The counts are `CensusSummary`'s."""
    user = seeded.user
    summary = await seeded.services.census.summary(seeded.corpus_id)
    counts = {bucket.label: bucket.column_count for bucket in summary.buckets}
    await user.open("/census")
    await user.should_see("Population profile · all tables")

    # `_ordered`, because `find(...).elements` is a **set**: the assertion
    # below is about the buckets' left-to-right order, so document order has
    # to be restored first.
    rendered = {
        str(e._props["data-bucket"]): _own_text(e)
        for e in _ordered(
            e for e in user.find(kind=ui.element).elements if "data-bucket" in e._props
        )
    }
    assert list(rendered) == [label.value for label in BUCKET_ORDER]
    for label in BUCKET_ORDER:
        assert rendered[label.value] == str(counts[label])
        await user.should_see(BUCKET_LABELS[label])
    assert sum(counts.values()) == summary.total_column_count


async def test_the_reminder_card_states_what_empty_means(seeded: Seeded) -> None:
    """README §2c, verbatim: empty means *no value provided*, never "not
    applicable" (mvp-spec.md §8.6)."""
    user = seeded.user
    await user.open("/census")
    await user.should_see("Reminder")
    await user.should_see(REMINDER_BODY)


async def test_the_census_table_pages_twenty_five_at_a_time(seeded: Seeded) -> None:
    """README §2b: "page size **25**, label "1–25 of 162"" — and, as on
    Import, disabled arrows are greyed rather than hidden."""
    user = seeded.user
    summary = await seeded.services.census.summary(seeded.corpus_id)
    await user.open("/census")
    assert len(_column_names(user)) == PAGE_SIZE
    assert _range_label(user) == f"1–{PAGE_SIZE} of {summary.total_column_count}"
    (previous,) = _find(user, "page-prev")
    assert "disabled" in previous._props


async def test_a_view_with_no_corpus_says_so(empty: User) -> None:
    """Undesigned state, in the tone README's "Loading / empty / error"
    section suggests: one centred line, and **no census call at all** — there
    is no corpus id to make one with."""
    await empty.open("/census")
    await empty.should_see(NO_CORPUS_MESSAGE)
    (export,) = _find(empty, "export-csv")
    assert "disabled" in export._props
    # No corpus id, so no chip has anything to name and no census call was
    # made at all — the toolbar is the caption and the disabled button.
    assert _find(empty, "chip") == []


# --- risk B1: the screen holds to the rule the export holds to ---------------


async def test_a_withheld_sample_says_so_and_shows_no_values(seeded: Seeded) -> None:
    """The Census view is the easier of the two places to copy a value out of
    by hand, so it applies the same rule the CSV does — one statement of it in
    `domain.census`, two callers.

    The bar renders its empty track and the legend names the reason. It must
    not read as "no values": an analyst who takes that as an empty column draws
    the opposite conclusion about the column's usefulness as a feature.
    """
    user = seeded.user
    await user.open(SAMPLE_PATH)

    legends = [_own_text(e) for e in _table(user).descendants() if "legend" in e.classes]

    assert WITHHELD_LEGEND in legends
    assert "withheld" in WITHHELD_LEGEND
    assert "no values" not in WITHHELD_LEGEND


async def test_a_coded_column_still_renders_its_distribution(seeded: Seeded) -> None:
    """The rule withholds; it does not blank the view. A coded column keeps its
    segments, which is what the card is for."""
    user = seeded.user
    await user.open(SAMPLE_PATH)

    bars = [e for e in _table(user).descendants() if "distbar" in e.classes]
    segments = [[i for i in bar.descendants() if i.tag == "i"] for bar in bars]

    assert len(bars) == 3, "one bar per row: coded, withheld, empty"
    assert any(row for row in segments if row), "the coded column keeps its segments"
    assert sum(1 for row in segments if not row) == 2, "withheld and empty draw no segments"


async def test_the_view_withholds_on_the_flag_even_if_it_is_handed_values(
    seeded: Seeded,
) -> None:
    """Defence in depth at the render site.

    The read model empties `top_values` for a withheld column, so a harness row
    that carries none proves nothing about the view — it would pass with the
    branch deleted. This hands the renderer the contradictory state instead: a
    column flagged withheld that still carries its values. Nothing of them may
    reach the page, because the view branches on the flag before it looks at
    the tuple, and a second reader of this read model should not have to
    re-derive that.
    """
    user = seeded.user
    await user.open(CONTRADICTORY_PATH)

    rendered = " ".join(
        text for e in _table(user).descendants() if (text := _own_text(e)) is not None
    )

    assert SECRET_VALUE not in rendered
    assert WITHHELD_COLUMN in rendered, "the column itself is still listed"
    assert WITHHELD_LEGEND in rendered
