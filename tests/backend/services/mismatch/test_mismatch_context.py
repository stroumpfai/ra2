"""What a mismatch row carries to tell a hallucination from a record error
(`plan-mismatch-context.md`, `SD70`).

The fixture is `scored_corpus`, scored for real, with two changes made while
seeding and before anything reads it:

- **the UIDs run backwards** against the surrogate ids, so a `record` sort
  that still ordered by `record.id` would come out reversed rather than
  accidentally right;
- (later steps add the codelist snapshots and the narrative hazards.)
"""

import csv
import io
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.domain.mismatch import MismatchTag
from ra2.persistence.models import Record
from ra2.services.export_service import CSV_DELIMITER, ExportService
from ra2.services.mismatch_service import MismatchService
from ra2.services.readmodels import SortDir
from ra2.services.scoring_service import ScoringService

pytestmark = pytest.mark.backend

RECORDS = 40


def _uid(index: int) -> str:
    """32 characters, the column's width (`_UID_LEN`), and **descending** as
    the surrogate id ascends."""
    return f"CH{RECORDS - index:030d}"


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
