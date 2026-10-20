"""A freeze stores only scrubbed narratives (sw-design.md §19, `SD62`, `SD66`).

Everything here runs the real `CorpusService.freeze` over h18, a committed
hazard delivery with invented personal data in the three places a narrative is
stored: a delivered narrative, an `UnfHergangTextAnonym` cell that differs
from it, and a fallback narrative that *is* the cell.
"""

import hashlib
from collections.abc import Awaitable, Callable, Iterable

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.backend.services.scrub.conftest import generator, scrub_bytes

from ra2.domain.findings import FindingCode
from ra2.domain.ids import CorpusId, DeliveryId, ScrubListId, ScrubRulesetId
from ra2.domain.scrub import ListKind
from ra2.infra.clock import FrozenClock
from ra2.infra.lingua_detector import LinguaDetector
from ra2.persistence.models import Corpus, Record, ScrubList, ScrubRuleset, UnfallRow
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.errors import BlockingFindingsError, NotFoundError
from ra2.services.scrub_service import ScrubService

pytestmark = pytest.mark.backend

H18 = generator()
ONE, TWO, THREE = H18.uid("aa", 1), H18.uid("aa", 2), H18.uid("aa", 3)

#: h18's narratives under the four fixture files (s01-s04). `Fuchs` is on the
#: whitelist and is a fox here; `14.30 Uhr` and `80 km/h` are protected.
SCRUBBED = {
    ONE: (
        "Herr <Lastname_1> (<Phone_1>) fuhr mit <LicensePlate_1> auf G1 auf. "
        "Zeugin <Firstname_1> <Lastname_2>, <Email_1>, bestätigte. "
        "Ein Fuchs querte vorher die Fahrbahn."
    ),
    TWO: "Frau <Lastname_1> meldete <LicensePlate_1> um 14.30 Uhr.",
    THREE: (
        "Madame <Lastname_1>, <Phone_1>, roulait à 80 km/h quand Monsieur <Lastname_2> a freiné."
    ),
}
#: The `UnfHergangTextAnonym` cells. `aa..2`'s is its narrative, so it is the
#: same scrubbed text; `aa..3`'s is the generator's default, with nothing in it.
SCRUBBED_CELLS = {
    ONE: "B1 fuhr auf G1 auf. Halter <LicensePlate_1>, Tel. <Phone_1>.",
    TWO: SCRUBBED[TWO],
    THREE: "Fahrzeug A bremste, Fahrzeug B fuhr auf.",
}

FreezeH18 = Callable[..., Awaitable[CorpusId]]


@pytest.fixture
def freeze_h18(
    h18_delivery: Callable[[], Awaitable[DeliveryId]], corpus_service: CorpusService
) -> FreezeH18:
    async def _freeze(**kwargs: object) -> CorpusId:
        return await corpus_service.freeze(await h18_delivery(), name="h18", **kwargs)  # type: ignore[arg-type]

    return _freeze


async def _records(
    factory: async_sessionmaker[AsyncSession], corpus_id: CorpusId
) -> dict[str, Record]:
    async with factory() as session:
        rows = await session.scalars(select(Record).where(Record.corpus_id == corpus_id))
        return {r.unfall_uid: r for r in rows}


async def _anonym_cells(
    factory: async_sessionmaker[AsyncSession], corpus_id: CorpusId
) -> dict[str, str]:
    async with factory() as session:
        rows = await session.execute(
            select(Record.unfall_uid, UnfallRow.value_raw)
            .join(UnfallRow, UnfallRow.record_id == Record.id)
            .where(Record.corpus_id == corpus_id, UnfallRow.column_name == "UnfHergangTextAnonym")
        )
        return {str(uid): str(value) for uid, value in rows.tuples()}


async def _corpus(factory: async_sessionmaker[AsyncSession], corpus_id: CorpusId) -> Corpus:
    async with factory() as session:
        corpus = await session.get(Corpus, corpus_id)
        assert corpus is not None
        return corpus


# --- what is stored -----------------------------------------------------------


async def test_every_narrative_is_stored_scrubbed(
    freeze_h18: FreezeH18,
    import_fixture_lists: Callable[[], Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await import_fixture_lists()
    corpus_id = await freeze_h18()
    records = await _records(db_session_factory, corpus_id)
    assert {uid: r.text_raw for uid, r in records.items()} == SCRUBBED
    assert records[TWO].text_anonymised_flag is True


async def test_the_anonymised_column_is_stored_scrubbed_too(
    freeze_h18: FreezeH18,
    import_fixture_lists: Callable[[], Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await import_fixture_lists()
    corpus_id = await freeze_h18()
    assert await _anonym_cells(db_session_factory, corpus_id) == SCRUBBED_CELLS


async def test_the_corpus_records_what_it_was_scrubbed_with(
    freeze_h18: FreezeH18,
    import_fixture_lists: Callable[[], Awaitable[None]],
    scrub_service: ScrubService,
    corpus_service: CorpusService,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await import_fixture_lists()
    active = await scrub_service.active()
    corpus_id = await freeze_h18()
    corpus = await _corpus(db_session_factory, corpus_id)
    assert corpus.scrub_ruleset_id == active.ruleset_id
    assert corpus.scrub_fingerprint == active.fingerprint
    assert '"id":"license-plate"' in (corpus.scrub_mandatory_json or "")
    view = await corpus_service.get(corpus_id)
    assert (view.scrubbed, view.scrub_version) == (True, 4)


async def test_every_rule_that_ran_is_counted_in_the_import_report(
    freeze_h18: FreezeH18,
    import_fixture_lists: Callable[[], Awaitable[None]],
    corpus_service: CorpusService,
) -> None:
    await import_fixture_lists()
    view = await corpus_service.get(await freeze_h18())
    counts = {c.rule_id: (c.tag, c.source, c.hits, c.records) for c in view.scrub_counts}
    assert counts == {
        "license-plate": ("LicensePlate", "mandatory", 3, 2),
        "phone": ("Phone", "mandatory", 3, 2),
        "email": ("Email", "mandatory", 1, 1),
        "iban-ch": ("IBAN", "imported", 0, 0),
        "ahv": ("AHV", "imported", 0, 0),
        "date": ("Date", "imported", 0, 0),
        "firstnames": ("Firstname", "list", 1, 1),
        "lastnames": ("Lastname", "list", 5, 3),
        "both-lists": ("Name", "list", 0, 0),
    }


async def test_the_dry_run_counts_what_the_freeze_then_stores(
    h18_delivery: Callable[[], Awaitable[DeliveryId]],
    import_fixture_lists: Callable[[], Awaitable[None]],
    corpus_service: CorpusService,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await import_fixture_lists()
    delivery_id = await h18_delivery()
    preview = await corpus_service.scrub_preview(delivery_id)
    async with db_session_factory() as session:
        before = await session.scalar(select(func.count()).select_from(Corpus))
    assert before == 0, "a dry run writes nothing"

    view = await corpus_service.get(await corpus_service.freeze(delivery_id, name="h18"))
    assert preview.counts == view.scrub_counts
    assert (preview.records, preview.records_changed) == (3, 3)
    assert preview.version == view.scrub_version


async def test_the_canary_and_the_language_read_the_original(
    freeze_h18: FreezeH18,
    import_fixture_lists: Callable[[], Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`D’Alessandro`'s apostrophe is a cp1252 canary character inside a
    scrubbed span: the corpus counts it, though no stored text holds it."""
    await import_fixture_lists()
    corpus_id = await freeze_h18()
    corpus = await _corpus(db_session_factory, corpus_id)
    records = await _records(db_session_factory, corpus_id)
    assert corpus.cp1252_canary_count == 1
    assert not any("’" in (r.text_raw or "") for r in records.values())

    original = (
        "Madame D’Alessandro, +41 79 765 43 21, roulait à 80 km/h quand Monsieur Rossi a freiné."
    )
    detector = LinguaDetector()
    on_original = detector.detect(original)
    on_scrubbed = detector.detect(SCRUBBED[THREE])
    assert records[THREE].language == on_original.language.value
    # A float through SQLite keeps ~15 digits; the two candidates differ in
    # the third, so the comparison still says which text was read.
    assert records[THREE].language_confidence == pytest.approx(on_original.confidence, abs=1e-9)
    assert abs(on_original.confidence - on_scrubbed.confidence) > 1e-3


async def test_freezing_twice_scrubs_identically(
    freeze_h18: FreezeH18,
    import_fixture_lists: Callable[[], Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await import_fixture_lists()
    first = await _records(db_session_factory, await freeze_h18())
    second = await _records(db_session_factory, await freeze_h18())
    assert {u: r.text_raw for u, r in first.items()} == {u: r.text_raw for u, r in second.items()}


# --- the leak test --------------------------------------------------------------


async def test_no_planted_value_is_anywhere_in_the_database(
    freeze_h18: FreezeH18,
    import_fixture_lists: Callable[[], Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Every text column of every table, read back raw.

    The exports, the prompt preview, the Results and Mismatches screens all
    read `record.text_raw` and the EAV cells; this checks them at the source.
    `scrub_list` is the one table excluded: it holds the public name lists
    themselves, which is what they are for.
    """
    await import_fixture_lists()
    await freeze_h18()
    planted = [value.casefold() for value in H18.H18_PLANTED]
    found: list[str] = []
    async with db_session_factory() as session:
        tables = (
            await session.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'scrub_list'")
            )
        ).scalars()
        for table in list(tables):
            rows = (await session.execute(text(f'SELECT * FROM "{table}"'))).all()
            for row in rows:
                for value in row:
                    if isinstance(value, str):
                        lowered = value.casefold()
                        found.extend(f"{table}: {p}" for p in planted if p in lowered)
    assert found == []


async def test_the_raw_preview_shows_no_planted_value(
    h18_delivery: Callable[[], Awaitable[DeliveryId]],
    import_fixture_lists: Callable[[], Awaitable[None]],
    delivery_service: DeliveryService,
) -> None:
    await import_fixture_lists()
    delivery_id = await h18_delivery()
    view = await delivery_service.get(delivery_id)
    lines: list[str] = []
    for file in view.files:
        lines.extend(await delivery_service.preview(delivery_id, file.file_id))
    assert lines, "the preview reads the files"
    shown = "\n".join(lines).casefold()
    assert [p for p in H18.H18_PLANTED if p.casefold() in shown] == []
    assert "<lastname_1>" in shown


# --- which rule set ---------------------------------------------------------------


async def test_with_nothing_imported_the_mandatory_rules_still_run(
    freeze_h18: FreezeH18,
    corpus_service: CorpusService,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus_id = await freeze_h18()
    records = await _records(db_session_factory, corpus_id)
    assert records[ONE].text_raw == (
        "Herr Müller (<Phone_1>) fuhr mit <LicensePlate_1> auf G1 auf. "
        "Zeugin Anna Meier, <Email_1>, bestätigte. "
        "Ein Fuchs querte vorher die Fahrbahn."
    )
    view = await corpus_service.get(corpus_id)
    assert (view.scrubbed, view.scrub_version) == (True, None)
    assert [c.rule_id for c in view.scrub_counts] == ["license-plate", "phone", "email"]


async def test_a_freeze_applies_the_version_its_dry_run_showed(
    h18_delivery: Callable[[], Awaitable[DeliveryId]],
    scrub_service: ScrubService,
    corpus_service: CorpusService,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """v1 has no whitelist, so `Fuchs` is a surname; v2 adds one. A freeze
    told to use v1 uses v1, though v2 became active in between."""
    first = await scrub_service.import_list(
        ListKind.LASTNAME, "l.txt", scrub_bytes("s02_lastnames.txt")
    )
    delivery_id = await h18_delivery()
    shown = await corpus_service.scrub_preview(delivery_id)
    await scrub_service.import_list(ListKind.WHITELIST, "w.txt", scrub_bytes("s03_whitelist.txt"))

    assert shown.ruleset_id == first.ruleset.ruleset_id
    corpus_id = await corpus_service.freeze(
        delivery_id, name="h18", scrub_ruleset_id=shown.ruleset_id
    )
    records = await _records(db_session_factory, corpus_id)
    assert "Ein <Lastname_3> querte" in (records[ONE].text_raw or "")
    assert (await _corpus(db_session_factory, corpus_id)).scrub_ruleset_id == shown.ruleset_id


async def test_an_unknown_version_is_not_found(
    h18_delivery: Callable[[], Awaitable[DeliveryId]], corpus_service: CorpusService
) -> None:
    delivery_id = await h18_delivery()
    with pytest.raises(NotFoundError):
        await corpus_service.freeze(
            delivery_id, name="h18", scrub_ruleset_id=ScrubRulesetId("no-such-version")
        )
    with pytest.raises(NotFoundError):
        await corpus_service.scrub_preview(delivery_id, scrub_ruleset_id=ScrubRulesetId("no"))


# --- failing closed (SD66) ------------------------------------------------------------


async def _plant_slow_rule(factory: async_sessionmaker[AsyncSession], clock: FrozenClock) -> None:
    """A rule set whose rule backtracks catastrophically, written straight to
    the database. The import would refuse it (`pattern_too_slow`); this is the
    pattern that only blows up on data the import never saw."""
    content = scrub_bytes("s06_slow_rule.toml")
    async with factory() as session:
        session.add(
            ScrubList(
                id=ScrubListId("slow-list"),
                kind=ListKind.REGEX,
                filename="s06_slow_rule.toml",
                sha256=hashlib.sha256(content).hexdigest(),
                imported_at=clock.now(),
                entry_count=1,
                content_text=content.decode("utf-8"),
                import_report_json="[]",
            )
        )
        await session.flush()
        session.add(
            ScrubRuleset(
                id=ScrubRulesetId("slow-set"),
                version=1,
                created_at=clock.now(),
                fingerprint="slow",
                regex_list_id=ScrubListId("slow-list"),
            )
        )
        await session.commit()


@pytest.fixture
def slow_delivery(
    analysed_delivery: Callable[[str, Iterable[tuple[str, bytes]]], Awaitable[DeliveryId]],
) -> Callable[[], Awaitable[DeliveryId]]:
    """One record whose narrative ends in a run `(a|aa)+$` cannot finish."""

    async def _build() -> DeliveryId:
        unfall = H18.structured(H18.FileKind.UNFALL, [H18.unfall_row(ONE, canton=H18.AG)])
        narrative = H18.text_file([(ONE, "Zeuge " + "a" * 60 + "!")])
        return await analysed_delivery(
            "slow", [("unfall.txt", unfall.encode()), ("text.csv", narrative.encode())]
        )

    return _build


async def test_a_rule_that_times_out_fails_the_freeze_and_writes_nothing(
    slow_delivery: Callable[[], Awaitable[DeliveryId]],
    corpus_service: CorpusService,
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    await _plant_slow_rule(db_session_factory, clock)
    delivery_id = await slow_delivery()
    with pytest.raises(BlockingFindingsError) as refused:
        await corpus_service.freeze(delivery_id, name="slow")
    [finding] = refused.value.findings
    assert (finding.code, finding.key, finding.detail) == (
        FindingCode.TEXT_SCRUB_TIMEOUT,
        ONE,
        {"rule_id": "slow"},
    )
    async with db_session_factory() as session:
        for model in (Corpus, Record, UnfallRow):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_the_dry_run_names_the_rule_that_would_time_out(
    slow_delivery: Callable[[], Awaitable[DeliveryId]],
    corpus_service: CorpusService,
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    await _plant_slow_rule(db_session_factory, clock)
    preview = await corpus_service.scrub_preview(await slow_delivery())
    assert preview.timed_out_rule == "slow"


async def test_the_preview_shows_what_it_replaced_and_the_totals_agree(
    import_fixture_lists: Callable[[], Awaitable[None]],
    h18_delivery: Callable[[], Awaitable[DeliveryId]],
    corpus_service: CorpusService,
) -> None:
    """SD70: examples per rule, each adding up to that rule's count, with the
    matched span as delivered and the context already scrubbed."""
    await import_fixture_lists()
    preview = await corpus_service.scrub_preview(await h18_delivery())

    assert [r.rule_id for r in preview.examples] == [c.rule_id for c in preview.counts]
    for count, rule in zip(preview.counts, preview.examples, strict=True):
        assert sum(v.hits for v in rule.values) + rule.other_hits == count.hits
    plate = next(r for r in preview.examples if r.rule_id == "license-plate")
    assert plate.values and all(v.examples for v in plate.values)
