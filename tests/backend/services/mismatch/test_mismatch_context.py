"""What a mismatch row carries to tell a hallucination from a record error
(`plan-mismatch-context.md`, `SD70`).

The fixture is `scored_corpus`, scored for real, with changes made while
seeding and before anything reads it:

- **the UIDs run backwards** against the surrogate ids, so a `record` sort
  that still ordered by `record.id` would come out reversed rather than
  accidentally right;
- **launch snapshots** for every feature, carrying the codelist hazards: a
  code labelled only in French under a German evaluation, and `s06`'s `99`,
  which is in no table;
- **a live code table that disagrees with the snapshot**, mapped to the
  weather column, so a decoder that read Codelists instead of the snapshot
  shows the wrong words and fails.
"""

import csv
import io
import json
from collections.abc import AsyncIterator
from typing import Final

import pytest
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import (
    ALL_EMPTY,
    LIGHT,
    NOW,
    RIGHT_OF_WAY,
    WEATHER,
    ScoredCorpus,
    seed_scored_corpus,
)

from ra2.domain.anonymisation import AnonymisationMarking
from ra2.domain.code_label import LabelState
from ra2.domain.codes import CodeValue as DomainCodeValue
from ra2.domain.feature import CountObjects, Kind, MatchingRuleKind, ValueType
from ra2.domain.ids import CodeAttributeId, CodeTableImportId, ColumnMappingId, MismatchId
from ra2.domain.mismatch import MismatchTag
from ra2.persistence.models import (
    CodeAttribute,
    CodeTableImport,
    CodeValue,
    ColumnMapping,
    EvaluationFeature,
    ExtractionValue,
    Record,
)
from ra2.services.errors import NotFoundError
from ra2.services.evaluation_service import snapshot_to_json
from ra2.services.export_service import CSV_DELIMITER, ExportService
from ra2.services.mismatch_service import MismatchService
from ra2.services.readmodels import MismatchDetailView, MismatchRowView, SortDir
from ra2.services.scoring_service import ScoringService

pytestmark = pytest.mark.backend

RECORDS = 40

#: The weather snapshot: 1-4 labelled in German, 5 **only in French**. The
#: first model's wrong weather answers are `index % 4 + 2` on every ninth
#: record, so record 27's 5 decodes as `no_label` under this German evaluation.
WEATHER_LABELS: Final = {
    "1": {"de": "trocken", "fr": "sec"},
    "2": {"de": "nass", "fr": "mouillé"},
    "3": {"de": "Schnee", "fr": "neige"},
    "4": {"de": "Eis", "fr": "glace"},
    "5": {"fr": "brouillard"},
}
LIGHT_LABELS: Final = {
    "1": {"de": "Tag", "fr": "jour"},
    "2": {"de": "Dämmerung", "fr": "crépuscule"},
    "3": {"de": "Nacht", "fr": "nuit"},
}


def _uid(index: int) -> str:
    """32 characters, the column's width (`_UID_LEN`), and **descending** as
    the surrogate id ascends."""
    return f"CH{RECORDS - index:030d}"


#: The narrative hazards (`plan-mismatch-context.md` §7), on the records whose
#: weather the first model gets wrong (every ninth). Its span is
#: "Schneefall" unless the entry changes it.
TWICE: Final = 9  # the span occurs twice
ACROSS_NEWLINE: Final = 18  # the span crosses the narrative's line break
NO_NARRATIVE: Final = 27  # the record has no text at all
#: Record 0 keeps `s05`'s lossy French, which does not contain the span.
NOT_THERE: Final = 0
#: A derived answer made wrong, so a `vehicles` mismatch exists to open.
WRONG_COUNT: Final = 1


async def _narrative_hazards(session: AsyncSession, corpus: ScoredCorpus) -> None:
    texts: dict[int, str | None] = {
        TWICE: "Schneefall am Morgen, Schneefall am Abend.",
        ACROSS_NEWLINE: "Der Lenker fuhr bei\nstarkem Schneefall auf die A1.",
        NO_NARRATIVE: None,
    }
    for index, text in texts.items():
        record = await session.get(Record, corpus.record_ids[index])
        assert record is not None
        record.text_raw = text
    weather = corpus.feature_ids[WEATHER]
    quoted = await session.get(ExtractionValue, (f"ext-s-0-{ACROSS_NEWLINE:03d}", weather))
    assert quoted is not None
    quoted.evidence_span = "bei starkem Schneefall"
    count = await session.get(
        ExtractionValue, (f"ext-s-0-{WRONG_COUNT:03d}", corpus.feature_ids["vehicles"])
    )
    assert count is not None
    count.value_raw = count.value_normalised = "3"


def _snapshot(key: str, labels: dict[str, dict[str, str]]) -> str:
    return snapshot_to_json(
        [DomainCodeValue(attribute_key=key, code=code, label=lab) for code, lab in labels.items()]
    )


@pytest.fixture
async def context(
    db_session_factory: async_sessionmaker[AsyncSession],
    scorer: ScoringService,
) -> AsyncIterator[ScoredCorpus]:
    async with db_session_factory() as session:
        corpus = await seed_scored_corpus(session, records=RECORDS)
        for index, record_id in enumerate(corpus.record_ids):
            record = await session.get(Record, record_id)
            assert record is not None
            record.unfall_uid = _uid(index)
        await _narrative_hazards(session, corpus)
        snapshots = {
            WEATHER: _snapshot("weather", WEATHER_LABELS),
            LIGHT: _snapshot("light", LIGHT_LABELS),
            RIGHT_OF_WAY: _snapshot("right_of_way", {"2": {"de": "rechts vor links"}}),
            ALL_EMPTY: _snapshot("never", {}),
            "vehicles": None,
        }
        for key, payload in snapshots.items():
            session.add(
                EvaluationFeature(
                    evaluation_id=corpus.evaluation_id,
                    feature_id=corpus.feature_ids[key],
                    enum_codelist_json=payload,
                    fingerprint="e" * 64,
                )
            )
        # The live mapping, changed after launch: every label is different.
        session.add(
            CodeTableImport(
                id=CodeTableImportId("cti-live"),
                source_file="codes.json",
                source_hash="0" * 64,
                imported_at=NOW,
            )
        )
        # Parents first: these models carry foreign keys without the
        # relationships that would let the unit of work order the inserts.
        await session.flush()
        session.add(
            CodeAttribute(
                id=CodeAttributeId("attr-live"),
                code_table_import_id=CodeTableImportId("cti-live"),
                key="weather",
                name_json=json.dumps({"de": "Wetter"}),
            )
        )
        await session.flush()
        for code in WEATHER_LABELS:
            session.add(
                CodeValue(
                    id=f"cv-live-{code}",
                    code_attribute_id=CodeAttributeId("attr-live"),
                    code=code,
                    label_json=json.dumps({"de": f"LIVE {code}", "fr": f"LIVE {code}"}),
                )
            )
        session.add(
            ColumnMapping(
                id=ColumnMappingId("map-live"),
                corpus_id=corpus.corpus_id,
                source_column=WEATHER,
                code_attribute_id=CodeAttributeId("attr-live"),
                mapped_at=NOW,
            )
        )
        await session.commit()
    for run_id in corpus.run_ids:
        await scorer.score_run(run_id)
    yield corpus


# --- P1: the record key ------------------------------------------------------


async def test_every_row_carries_its_records_unfall_uid(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    """mvp-spec.md §12 names the record key as part of the row. The surrogate
    `record.id` is in no delivery, so it identifies nothing to an analyst."""
    view = await mismatch_service.list_mismatches(context.evaluation_id, page_size=1000)

    assert view.rows.items
    expected = {record_id: _uid(i) for i, record_id in enumerate(context.record_ids)}
    for row in view.rows.items:
        assert row.unfall_uid == expected[row.record_id]
        assert len(row.unfall_uid) == 32


async def test_the_record_sort_orders_by_the_uid_and_is_total(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    """The `record` key keeps its name (`MISMATCH_SORT_KEYS` is closed) and
    now orders by what the column shows. The fixture's UIDs run against the
    surrogate ids, so the old order would fail this both ways round."""
    asc = await mismatch_service.list_mismatches(
        context.evaluation_id, sort_key="record", page_size=1000
    )
    desc = await mismatch_service.list_mismatches(
        context.evaluation_id, sort_key="record", sort_dir=SortDir.DESC, page_size=1000
    )

    asc_uids = [row.unfall_uid for row in asc.rows.items]
    assert asc_uids == sorted(asc_uids)
    assert [row.unfall_uid for row in desc.rows.items] == sorted(asc_uids, reverse=True)
    #: Total: several features mismatch on one record, and paging must not
    #: reshuffle them. Two pages stitched together are the one-page list.
    first = await mismatch_service.list_mismatches(
        context.evaluation_id, sort_key="record", page_size=5
    )
    second = await mismatch_service.list_mismatches(
        context.evaluation_id, sort_key="record", page=2, page_size=5
    )
    stitched = [row.mismatch_id for row in (*first.rows.items, *second.rows.items)]
    assert stitched == [row.mismatch_id for row in asc.rows.items[:10]]


async def test_a_tag_write_returns_the_row_with_its_uid(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    """The handler redraws from the row `tag` returns, so it has to come back
    through the same join as the list."""
    view = await mismatch_service.list_mismatches(context.evaluation_id, page_size=1)
    (row,) = view.rows.items
    tagged = await mismatch_service.tag(row.mismatch_id, tag=MismatchTag.UNCLEAR)
    assert tagged.unfall_uid == row.unfall_uid
    #: …and decoded against the same snapshot (SD70).
    assert tagged.record_decoded == row.record_decoded
    assert tagged.extracted_decoded == row.extracted_decoded
    assert tagged.record_decoded.state is LabelState.LABELLED


async def test_the_csv_appends_the_uid_and_moves_no_earlier_column(
    mismatch_service: MismatchService,
    context: ScoredCorpus,
    export_service: ExportService,
) -> None:
    """Appended, never inserted: a script reading the file by position keeps
    working."""
    rows = await mismatch_service.export_rows(context.evaluation_id)
    table = _csv_rows(
        export_service.mismatches_csv(
            rows.rows.items,
            evaluation_id=context.evaluation_id,
            run_label=rows.run_label,
            filter_label="all",
        )
    )
    header = table[0]
    assert header[:10] == [
        "mismatch_id",
        "record_id",
        "anonymised",
        "feature_key",
        "record_value",
        "extracted_value",
        "evidence_span",
        "analyst_tag",
        "tagged_at",
        "note",
    ]
    assert header[10] == "unfall_uid"
    assert [row[10] for row in table[1:]] == [row.unfall_uid for row in rows.rows.items]


def _csv_rows(payload: bytes) -> list[list[str]]:
    """The header and the data rows, through a real CSV reader: a span with a
    `;` or a newline in it is quoted, and splitting by hand would misread it.
    The first two lines are the classification and the comment."""
    body = payload.decode("utf-8-sig").split("\r\n", 2)[2]
    return [row for row in csv.reader(io.StringIO(body), delimiter=CSV_DELIMITER) if row]


# --- P2: code · label ----------------------------------------------------------


async def _all_rows(
    mismatch_service: MismatchService, context: ScoredCorpus, run: int = 1
) -> tuple[MismatchRowView, ...]:
    view = await mismatch_service.list_mismatches(
        context.evaluation_id, run_id=context.run_ids[run], page_size=1000
    )
    return view.rows.items


async def test_labels_come_from_the_launch_snapshot_not_the_live_mapping(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    """The live mapping says `LIVE n` for every code. The model was shown the
    snapshot, so the snapshot's words are the only right ones (`SD70`)."""
    rows = [r for r in await _all_rows(mismatch_service, context) if r.feature_key == WEATHER]
    assert rows
    for row in rows:
        decoded = row.record_decoded
        assert decoded.state is LabelState.LABELLED
        assert decoded.raw == row.record_value
        assert decoded.label == WEATHER_LABELS[row.record_value or ""]["de"]
        assert decoded.language == "de"
    labels = {r.record_decoded.label for r in rows} | {r.extracted_decoded.label for r in rows}
    assert not any(label and label.startswith("LIVE") for label in labels)


async def test_a_code_with_no_label_in_the_prompt_language_says_so(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    """Code 5 is labelled only in French; the evaluation asked in German."""
    rows = await _all_rows(mismatch_service, context, run=0)
    fives = [r for r in rows if r.feature_key == WEATHER and r.extracted_value == "5"]
    assert fives, "the first model's wrong weather answers include 5 (record 27)"
    for row in fives:
        assert row.extracted_decoded.state is LabelState.NO_LABEL
        assert row.extracted_decoded.label is None


async def test_a_code_outside_the_snapshot_is_said_to_be_outside_it(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    """`s06`: one extracted light code is 99, which is in no table."""
    rows = await _all_rows(mismatch_service, context, run=0)
    (row,) = [r for r in rows if r.feature_key == LIGHT and r.extracted_value == "99"]
    assert row.extracted_decoded.state is LabelState.NOT_IN_TABLE
    assert row.record_decoded.state is LabelState.LABELLED


async def test_a_feature_with_no_snapshot_crosses_undecoded(
    mismatch_service: MismatchService,
    context: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An evaluation launched before snapshots existed, simulated by removing
    weather's row. The values cross as they are, and the live mapping is
    **not** reached for as a fallback. (Only weather and light mismatch in
    this fixture, and an empty value is `missing`, never `wrong`: the `empty`
    state is the unit tests'.)"""
    async with db_session_factory() as session:
        await session.execute(
            delete(EvaluationFeature).where(
                EvaluationFeature.feature_id == context.feature_ids[WEATHER]
            )
        )
        await session.commit()
    rows = [r for r in await _all_rows(mismatch_service, context) if r.feature_key == WEATHER]
    assert rows
    assert {r.record_decoded.state for r in rows} == {LabelState.NOT_ENUM}
    assert {r.extracted_decoded.state for r in rows} == {LabelState.NOT_ENUM}
    assert all(r.record_decoded.raw == r.record_value for r in rows)


async def test_decoding_costs_one_statement_per_page_not_per_row(
    mismatch_service: MismatchService,
    context: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`R4`: the snapshots are read once and every row decodes against the
    parsed result, so a page of 5 and a page of 1000 cost the same."""
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context_, executemany):
        statements.append(statement)

    engine = db_session_factory.kw["bind"]
    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        await mismatch_service.list_mismatches(context.evaluation_id, page_size=5)
        small = len(statements)
        statements.clear()
        await mismatch_service.list_mismatches(context.evaluation_id, page_size=1000)
        large = len(statements)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert small == large
    snapshot_reads = [
        s for s in statements if "enum_codelist_json" in s and "FROM evaluation_feature" in s
    ]
    assert len(snapshot_reads) == 1


async def test_the_csv_appends_both_labels_after_the_uid(
    mismatch_service: MismatchService,
    context: ScoredCorpus,
    export_service: ExportService,
) -> None:
    rows = await mismatch_service.export_rows(context.evaluation_id, run_id=context.run_ids[0])
    table = _csv_rows(
        export_service.mismatches_csv(
            rows.rows.items,
            evaluation_id=context.evaluation_id,
            run_label=rows.run_label,
            filter_label="all",
        )
    )
    assert table[0][10:] == [
        "unfall_uid",
        "record_label",
        "extracted_label",
        "record_label_state",
        "extracted_label_state",
    ]
    for csv_row, row in zip(table[1:], rows.rows.items, strict=True):
        assert csv_row[11] == (row.record_decoded.label or "")
        assert csv_row[12] == (row.extracted_decoded.label or "")
        assert csv_row[13] == row.record_decoded.state.value
        assert csv_row[14] == row.extracted_decoded.state.value
    assert any(csv_row[11] == "trocken" for csv_row in table[1:])
    #: An invented code is not a blank in the file either.
    (invented,) = [r for r in table[1:] if r[5] == "99"]
    assert invented[12] == ""
    assert invented[14] == LabelState.NOT_IN_TABLE.value


# --- P3 + P5: the detail -------------------------------------------------------


async def _open(
    mismatch_service: MismatchService, context: ScoredCorpus, index: int, feature: str = WEATHER
) -> MismatchDetailView:
    rows = await _all_rows(mismatch_service, context, run=0)
    (row,) = [
        r for r in rows if r.record_id == context.record_ids[index] and r.feature_key == feature
    ]
    return await mismatch_service.detail(row.mismatch_id)


def _highlighted(detail: MismatchDetailView) -> list[str]:
    assert detail.narrative is not None
    return [detail.narrative[start:end] for start, end in detail.highlights]


async def test_the_detail_carries_the_narrative_and_every_place_the_span_is(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    detail = await _open(mismatch_service, context, TWICE)
    assert detail.narrative == "Schneefall am Morgen, Schneefall am Abend."
    assert _highlighted(detail) == ["Schneefall", "Schneefall"]
    assert detail.unfall_uid == _uid(TWICE)
    assert detail.evidence_span == "Schneefall"


async def test_a_span_across_a_line_break_is_highlighted_in_the_original_text(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    detail = await _open(mismatch_service, context, ACROSS_NEWLINE)
    assert _highlighted(detail) == ["bei\nstarkem Schneefall"]


async def test_a_span_not_in_the_text_is_neither_highlighted_nor_flagged(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    """`D1`: the detail locates and never judges. There is no field that
    could say "not found", and the empty tuple is the whole answer."""
    detail = await _open(mismatch_service, context, NOT_THERE)
    assert detail.narrative is not None and "Schneefall" not in detail.narrative
    assert detail.highlights == ()
    assert not any("found" in name for name in MismatchDetailView.__dataclass_fields__)


async def test_a_record_without_a_narrative_opens_with_none(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    detail = await _open(mismatch_service, context, NO_NARRATIVE)
    assert detail.narrative is None
    assert detail.highlights == ()


async def test_the_detail_carries_the_language_and_the_marking(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    """mvp-spec.md §13: the marking wherever text is shown. Record 0 is the
    fixture's French record and falls back to the anonymised column."""
    detail = await _open(mismatch_service, context, NOT_THERE)
    assert detail.language == "fr"
    assert detail.language_confidence == pytest.approx(0.41)
    assert detail.anonymisation is AnonymisationMarking.ANONYMISED_COLUMN


async def test_a_native_enum_feature_opens_with_its_column_rule_and_labels(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    detail = await _open(mismatch_service, context, TWICE)
    assert detail.feature_key == WEATHER
    assert detail.feature_description == f"{WEATHER} for scoring tests"
    assert detail.kind is Kind.LABELLED
    assert detail.value_type is ValueType.ENUM
    assert detail.matching_rule.kind is MatchingRuleKind.EXACT
    assert detail.source_column == WEATHER
    assert detail.derivation is None
    #: Record 9: the record says 2, the model said 3 (`index % 4 + 2`).
    assert (detail.record_decoded.raw, detail.record_decoded.label) == ("2", "nass")
    assert (detail.extracted_decoded.raw, detail.extracted_decoded.label) == ("3", "Schnee")


async def test_a_derived_feature_opens_with_its_derivation_and_no_column(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    detail = await _open(mismatch_service, context, WRONG_COUNT, feature="vehicles")
    assert detail.source_column is None
    assert isinstance(detail.derivation, CountObjects)
    assert detail.value_type is ValueType.INTEGER
    assert detail.extracted_decoded.state is LabelState.NOT_ENUM
    assert (detail.record_decoded.raw, detail.extracted_decoded.raw) == ("0", "3")


async def test_opening_an_unknown_mismatch_is_not_found(
    mismatch_service: MismatchService, context: ScoredCorpus
) -> None:
    with pytest.raises(NotFoundError):
        await mismatch_service.detail(MismatchId("gone"))


async def test_the_list_never_carries_the_narrative() -> None:
    """Fetched on open, never with the page (`SD70`): the row type has no
    field that could hold it."""
    assert "narrative" not in MismatchRowView.__dataclass_fields__
