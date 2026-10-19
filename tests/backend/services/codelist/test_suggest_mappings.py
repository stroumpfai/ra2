"""Layer 2 — `CodelistService.suggest_mappings` / `apply_mappings`
(plan-codelists-usability.md §4.2), over a real migrated temp-file SQLite.

Three corpora and the c06 code table:

| corpus  | name    | v | imported | mapped                                    |
|---------|---------|---|----------|-------------------------------------------|
| `old`   | `deliv` | 1 | first    | UnfTypAusw→accident_type,                 |
|         |         |   |          | LichtAusw→light_condition,                |
|         |         |   |          | WitterAusw→weather                        |
| `new`   | `deliv` | 2 | second   | — (the one suggestions are asked for)     |
| `other` | `other` | 1 | last     | VerlAusw→weather (wrong on purpose)       |

`new`'s `UnfTypAusw` lost its leading zeros (`1`, `2` where the codes are
`01`…`04`), so the copied mapping is offered *and* shows it covers nothing.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.conftest import FrozenClock
from tests.fixtures.factories import make_census_input, make_census_table_input, seed_corpus

from ra2.domain.codelist_suggest import SuggestionSource
from ra2.domain.ids import CodeAttributeId, CorpusId, RecordId
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import CodeValue, ColumnMapping, Record, UnfallRow
from ra2.services.census_materialiser import RelationalCensusMaterialiser
from ra2.services.codelist_service import CodelistService
from ra2.services.errors import NotFoundError
from ra2.services.readmodels import MappingSuggestionsView, MappingSuggestionView

OLD = CorpusId("old")
NEW = CorpusId("new")
OTHER = CorpusId("other")

Seeder = Callable[..., Awaitable[None]]


@pytest.fixture
def seed_columns(db_session_factory: async_sessionmaker[AsyncSession]) -> Seeder:
    """One corpus with several `unfall` enum columns and the EAV cells behind
    them — `seed_enum_column`, widened to more than one column and to a
    corpus name, version and import time of the test's choosing."""

    async def _seed(
        corpus_id: CorpusId,
        *,
        name: str,
        version: int,
        imported_at: datetime,
        columns: dict[str, Sequence[str]],
    ) -> None:
        record_count = len(next(iter(columns.values())))
        async with db_session_factory() as session:
            await seed_corpus(
                session,
                corpus_id,
                name=name,
                version=version,
                imported_at=imported_at,
                record_count=record_count,
            )
            for index in range(record_count):
                record_id = RecordId(f"{corpus_id}-r{index}")
                session.add(
                    Record(
                        id=record_id,
                        corpus_id=corpus_id,
                        unfall_uid=f"{corpus_id}-u{index}",
                        language="de",
                        language_confidence=1.0,
                    )
                )
                await session.flush()
                for column_name, values in columns.items():
                    session.add(
                        UnfallRow(
                            record_id=record_id, column_name=column_name, value_raw=values[index]
                        )
                    )
            await session.flush()
            cells = [(column, value) for column, values in columns.items() for value in values]
            census = make_census_input(
                record_count=record_count,
                tables=[make_census_table_input("unfall", tuple(columns), cells)],
            )
            materialiser = RelationalCensusMaterialiser(
                ids=SeededFactory(seed=sum(map(ord, corpus_id)))
            )
            await materialiser.materialise(session, corpus_id, census)
            await session.commit()

    return _seed


async def _keys(service: CodelistService) -> dict[str, CodeAttributeId]:
    return {a.key: a.code_attribute_id for a in await service.list_attributes()}


@pytest.fixture
async def three_corpora(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_columns: Seeder,
) -> CodelistService:
    await codelist_service.import_file("codelist.json", codelist_bytes("c06_automap"))
    await seed_columns(
        OLD,
        name="deliv",
        version=1,
        imported_at=datetime(2026, 9, 1, tzinfo=UTC),
        columns={"UnfTypAusw": ("01", "02"), "LichtAusw": ("1", "2"), "WitterAusw": ("1", "2")},
    )
    await seed_columns(
        NEW,
        name="deliv",
        version=2,
        imported_at=datetime(2026, 9, 2, tzinfo=UTC),
        columns={
            "UnfTypAusw": ("1", "2", "2", "1"),
            "LichtAusw": ("1", "2", "1", "1"),
            "WitterAusw": ("1", "7", "7", "1"),
            "VerlAusw": ("1", "2", "3", "2"),
        },
    )
    await seed_columns(
        OTHER,
        name="other",
        version=1,
        imported_at=datetime(2026, 9, 3, tzinfo=UTC),
        columns={"VerlAusw": ("1", "2")},
    )
    keys = await _keys(codelist_service)
    for column, key in (
        ("UnfTypAusw", "accident_type"),
        ("LichtAusw", "light_condition"),
        ("WitterAusw", "weather"),
    ):
        await codelist_service.map_column(OLD, column, keys[key])
    await codelist_service.map_column(OTHER, "VerlAusw", keys["weather"])
    return codelist_service


def _by_column(view: MappingSuggestionsView) -> dict[str, MappingSuggestionView]:
    return {s.column_name: s for s in view.suggestions}


def _summary(view: MappingSuggestionsView) -> dict[str, tuple[str, SuggestionSource, int, int]]:
    return {
        s.column_name: (s.attribute_key, s.source, s.contained, s.distinct)
        for s in view.suggestions
    }


async def _mapping_count(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(ColumnMapping)) or 0)


async def _code_value_count(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(CodeValue)) or 0)


# --- suggest -------------------------------------------------------------------


async def test_the_default_source_is_the_previous_version_of_the_same_name(
    three_corpora: CodelistService,
) -> None:
    """`other` is newer and mapped, but `old` is `new`'s previous version."""
    view = await three_corpora.suggest_mappings(NEW)
    assert view.source_corpus_id == OLD
    assert view.sources == (OTHER, OLD)


async def test_copied_suggestions_carry_their_overlap_and_the_rest_is_overlap(
    three_corpora: CodelistService,
) -> None:
    """Every column `old` mapped is copied — `UnfTypAusw` covering *none* of
    its values, which the analyst sees as `0 / 2` — and `VerlAusw`, which
    `old` never mapped, gets the tightest attribute that covers it."""
    assert _summary(await three_corpora.suggest_mappings(NEW)) == {
        "UnfTypAusw": ("accident_type", SuggestionSource.COPIED, 0, 2),
        "LichtAusw": ("light_condition", SuggestionSource.COPIED, 2, 2),
        "WitterAusw": ("weather", SuggestionSource.COPIED, 2, 2),
        "VerlAusw": ("injury_severity", SuggestionSource.OVERLAP, 3, 3),
    }


async def test_an_explicit_source_replaces_the_default(three_corpora: CodelistService) -> None:
    """From `other`, only `VerlAusw` is copied; the bare `1`/`2` columns go
    to the smallest attribute containing them, and `7` only fits `weather`."""
    view = await three_corpora.suggest_mappings(NEW, source_corpus_id=OTHER)
    assert view.source_corpus_id == OTHER
    assert _summary(view) == {
        "UnfTypAusw": ("injury_severity", SuggestionSource.OVERLAP, 2, 2),
        "LichtAusw": ("injury_severity", SuggestionSource.OVERLAP, 2, 2),
        "WitterAusw": ("weather", SuggestionSource.OVERLAP, 2, 2),
        "VerlAusw": ("weather", SuggestionSource.COPIED, 3, 3),
    }


async def test_a_copied_key_the_current_import_lacks_is_unresolved_not_guessed(
    three_corpora: CodelistService, codelists_dir: Path, clock: FrozenClock
) -> None:
    """The next generation drops `light_condition`. `LichtAusw` gets no
    suggestion at all — not an overlap fall-back — and is reported; the keys
    that survive resolve to the **current** generation's attributes."""
    # Later than the first generation, so "current" does not rest on the
    # id tie-break (`get_latest_import`).
    clock.advance(seconds=60)
    next_generation = codelists_dir / "c06_automap" / "codelist_next.json"
    result = await three_corpora.import_file("codelist_next.json", next_generation.read_bytes())
    assert not result.no_change
    view = await three_corpora.suggest_mappings(NEW)

    assert "LichtAusw" not in _by_column(view)
    assert [(u.column_name, u.table_name, u.attribute_key) for u in view.unresolved] == [
        ("LichtAusw", "unfall", "light_condition")
    ]
    current = await _keys(three_corpora)
    assert _by_column(view)["UnfTypAusw"].code_attribute_id == current["accident_type"]


async def test_an_existing_mapping_is_flagged_and_an_identical_one_dropped(
    three_corpora: CodelistService,
) -> None:
    keys = await _keys(three_corpora)
    await three_corpora.map_column(NEW, "WitterAusw", keys["weather"])
    await three_corpora.map_column(NEW, "VerlAusw", keys["weather"])
    suggestions = _by_column(await three_corpora.suggest_mappings(NEW))

    assert "WitterAusw" not in suggestions  # the same as what is there: nothing to apply
    assert suggestions["VerlAusw"].attribute_key == "injury_severity"
    assert suggestions["VerlAusw"].currently == "weather"
    assert suggestions["LichtAusw"].currently is None


async def test_suggesting_writes_nothing(
    three_corpora: CodelistService, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    before = await _mapping_count(db_session_factory)
    await three_corpora.suggest_mappings(NEW)
    assert await _mapping_count(db_session_factory) == before


async def test_with_no_mapped_corpus_there_is_no_source_and_overlap_only(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_columns: Seeder,
) -> None:
    await codelist_service.import_file("codelist.json", codelist_bytes("c06_automap"))
    await seed_columns(
        NEW,
        name="deliv",
        version=1,
        imported_at=datetime(2026, 9, 2, tzinfo=UTC),
        columns={"VerlAusw": ("1", "2", "3")},
    )
    view = await codelist_service.suggest_mappings(NEW)
    assert (view.source_corpus_id, view.sources, view.unresolved) == (None, (), ())
    assert _summary(view) == {"VerlAusw": ("injury_severity", SuggestionSource.OVERLAP, 3, 3)}


async def test_with_no_codelist_there_is_nothing_to_suggest(
    codelist_service: CodelistService, seed_columns: Seeder
) -> None:
    await seed_columns(
        NEW,
        name="deliv",
        version=1,
        imported_at=datetime(2026, 9, 2, tzinfo=UTC),
        columns={"VerlAusw": ("1",)},
    )
    view = await codelist_service.suggest_mappings(NEW)
    assert view.suggestions == ()


# --- apply ---------------------------------------------------------------------


async def test_applying_maps_every_pick(three_corpora: CodelistService) -> None:
    view = await three_corpora.suggest_mappings(NEW)
    picks = [(s.column_name, s.code_attribute_id) for s in view.suggestions]

    assert await three_corpora.apply_mappings(NEW, picks) == 4
    mapped = {
        c.column_name: c.mapped_attribute.key if c.mapped_attribute else None
        for c in await three_corpora.list_columns(NEW, language="de")
    }
    assert mapped == {
        "UnfTypAusw": "accident_type",
        "LichtAusw": "light_condition",
        "WitterAusw": "weather",
        "VerlAusw": "injury_severity",
    }


async def test_applying_never_touches_the_code_table(
    three_corpora: CodelistService, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    before = await _code_value_count(db_session_factory)
    view = await three_corpora.suggest_mappings(NEW)
    await three_corpora.apply_mappings(
        NEW, [(s.column_name, s.code_attribute_id) for s in view.suggestions]
    )
    assert await _code_value_count(db_session_factory) == before


async def test_an_unknown_attribute_applies_nothing_at_all(
    three_corpora: CodelistService, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """One transaction: the valid pick before the bad one is not kept."""
    keys = await _keys(three_corpora)
    before = await _mapping_count(db_session_factory)
    with pytest.raises(NotFoundError):
        await three_corpora.apply_mappings(
            NEW,
            [("VerlAusw", keys["injury_severity"]), ("LichtAusw", CodeAttributeId("no-such"))],
        )
    assert await _mapping_count(db_session_factory) == before


async def test_an_unknown_column_applies_nothing_at_all(
    three_corpora: CodelistService, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    keys = await _keys(three_corpora)
    before = await _mapping_count(db_session_factory)
    with pytest.raises(NotFoundError):
        await three_corpora.apply_mappings(
            NEW, [("VerlAusw", keys["weather"]), ("NoSuchAusw", keys["weather"])]
        )
    assert await _mapping_count(db_session_factory) == before
