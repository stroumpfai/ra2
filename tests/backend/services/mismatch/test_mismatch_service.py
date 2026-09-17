"""`MismatchService` — the list, the tag, the tally and the export rows
(mvp-spec.md §12, sw-design.md §17).

**The first service in this codebase through which a human writes to the
database**, and the two tests that carry this phase are both about what that
write must *not* do:

- `test_tagging_changes_no_score_row` — mvp-spec.md §12's "the tag never feeds
  back into a metric. Nothing is rescored." Asserted by recording every `score`
  row, tagging every mismatch, and re-reading them byte-identically. The
  structural half of the same guarantee is in `tests/test_p5_contract.py`,
  which asserts on this module's AST that it imports no scoring module (R3).
- `test_the_tally_agrees_with_the_list_for_the_same_filter` — the strip under
  the table and the table itself come from one filter shape, so they cannot
  end up answering different questions (§17.4).
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import WEATHER, ScoredCorpus

from ra2.domain.ids import EvaluationId, MismatchId
from ra2.domain.mismatch import MismatchTag, TagState
from ra2.persistence.models import Score
from ra2.services.errors import NotFoundError
from ra2.services.export_service import ExportService
from ra2.services.mismatch_service import MismatchService
from ra2.services.readmodels import MismatchListView, SortDir
from ra2.services.scoring_service import ScoringService

pytestmark = pytest.mark.backend


# --- the list ---------------------------------------------------------------


async def test_the_list_renders_the_rows_the_scorer_wrote(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """Phase 5 is a view over data that already exists (plan-phase-4.md Q1).

    These rows come out of the fixture's real wrong answers, scored by the real
    pass — not from a hand-written insert, which would test the view against a
    shape the scorer does not produce.
    """
    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=100)

    assert view.rows.total > 0, "the fixture's wrong answers must produce mismatches"
    assert all(row.feature_key for row in view.rows.items)
    assert all(row.analyst_tag is None for row in view.rows.items), (
        "analyst_tag has been NULL since phase 4, deliberately"
    )
    #: §12's own list: the record value, the extracted value and the span.
    assert any(row.evidence_span for row in view.rows.items)


async def test_the_list_is_scoped_to_one_run_and_names_which(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """`SD26`, §17.6. There is no "all runs" option, because a list mixing two
    models' mismatches for the same record and feature **is** the cross-model
    agreement §16.9 defers.

    The toolbar names the run instead, which is also what makes `run_finished_at`
    well-defined (`SD25`).
    """
    first = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=100)
    second = await mismatch_service.list_mismatches(
        scored.evaluation_id, run_id=scored.run_ids[1], page_size=100
    )

    assert first.filters.run_id == scored.run_ids[0], "absent `run` picks the first"
    assert second.filters.run_id == scored.run_ids[1]
    assert first.run_label.startswith("run 1 · ")
    assert second.run_label.startswith("run 2 · ")
    assert len(first.runs) == 2, "both runs are offered as the filter's options"
    #: And the two lists are disjoint: every row belongs to the run named.
    assert {row.mismatch_id for row in first.rows.items} & {
        row.mismatch_id for row in second.rows.items
    } == set()


async def test_an_unknown_evaluation_is_a_not_found_error(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """`NotFoundError`, not a new exception type: phase 5 adds no error, because
    it introduces no new failure (plan-phase-5.md §5.1)."""
    with pytest.raises(NotFoundError):
        await mismatch_service.list_mismatches(EvaluationId("nope"))


async def test_a_filter_that_matches_nothing_is_an_empty_page_with_a_real_total(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """Zero is a **result**, not an error.

    Nothing has been tagged yet, so filtering to `unclear` matches nothing —
    and the analyst who filtered there needs a page that says "none", not an
    exception that says something went wrong (the §16.7 reasoning, reapplied).
    """
    view = await mismatch_service.list_mismatches(
        scored.evaluation_id, tag_state=MismatchTag.UNCLEAR, page_size=100
    )

    assert view.rows.items == ()
    assert view.rows.total == 0
    assert view.tallies == ()
    #: The filter options survive an empty page — otherwise the analyst has no
    #: way back out of the filter they just applied.
    assert view.features != ()
    assert view.runs != ()


async def test_the_work_queue_and_the_reviewed_list_are_both_one_filter(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """`TagState`. An analyst's work queue is `untagged`; what they have done
    is `tagged`; a review of one judgement is a named tag.

    All three are the same closed field, because the toolbar is one control —
    and `tagged` means **any** tag, including one `MismatchTag` does not name,
    since an `other` row has been reviewed whatever the word was (§17.5).
    """
    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=1000)
    total = view.rows.total
    for row in view.rows.items[:4]:
        await mismatch_service.tag(row.mismatch_id, tag=MismatchTag.UNCLEAR)

    untagged = await mismatch_service.list_mismatches(
        scored.evaluation_id, tag_state=TagState.UNTAGGED, page_size=1000
    )
    tagged = await mismatch_service.list_mismatches(
        scored.evaluation_id, tag_state=TagState.TAGGED, page_size=1000
    )
    named = await mismatch_service.list_mismatches(
        scored.evaluation_id, tag_state=MismatchTag.UNCLEAR, page_size=1000
    )
    every = await mismatch_service.list_mismatches(
        scored.evaluation_id, tag_state=TagState.ANY, page_size=1000
    )

    assert tagged.rows.total == named.rows.total == 4
    assert untagged.rows.total == total - 4
    assert every.rows.total == total
    #: And the strip agrees with each of them.
    assert sum(entry.tally.total for entry in untagged.tallies) == untagged.rows.total
    assert sum(entry.tally.reviewed for entry in tagged.tallies) == 4


async def test_paging_and_sorting_are_carried_on_the_page_itself(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """The design's "1–25 of 162" needs both numbers, and pagination disables
    rather than hides — so the page has to say what it is a page of."""
    first = await mismatch_service.list_mismatches(
        scored.evaluation_id, sort_key="record", sort_dir=SortDir.DESC, page=1, page_size=3
    )
    second = await mismatch_service.list_mismatches(
        scored.evaluation_id, sort_key="record", sort_dir=SortDir.DESC, page=2, page_size=3
    )

    assert first.rows.page == 1
    assert first.rows.page_size == 3
    assert first.rows.sort_key == "record"
    assert first.rows.sort_dir is SortDir.DESC
    assert first.rows.total == second.rows.total > 3
    assert len(first.rows.items) == 3
    #: Two pages of a total sort share no row (`Mismatch.id` is the tie-break).
    assert {row.mismatch_id for row in first.rows.items} & {
        row.mismatch_id for row in second.rows.items
    } == set()


async def test_the_descriptor_marks_a_dev_sized_result(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """mvp-spec.md §13: the "smoke test, not a result" marker is required on
    **every** dev-sized result wherever its numbers appear — and a mismatch
    list is somewhere they appear."""
    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=1)

    assert view.descriptor.evaluation_id == scored.evaluation_id
    assert view.descriptor.model_count == 2
    assert isinstance(view.descriptor.is_dev, bool)


# --- the write --------------------------------------------------------------


async def test_tagging_a_row_and_re_reading_the_list_returns_the_tag(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """The round trip the whole phase exists for."""
    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=100)
    target = view.rows.items[0]

    tagged = await mismatch_service.tag(
        target.mismatch_id, tag=MismatchTag.HALLUCINATION, note="invented a value"
    )
    assert tagged.tag is MismatchTag.HALLUCINATION
    assert tagged.tagged_at is not None
    assert tagged.note == "invented a value"
    assert tagged.reviewed is True

    again = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=100)
    stored = next(row for row in again.rows.items if row.mismatch_id == target.mismatch_id)
    assert stored.analyst_tag == "hallucination"
    assert stored.tagged_at == tagged.tagged_at


async def test_tagging_is_idempotent_and_re_tagging_replaces(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """`Q4`: a judgement made on the wrong row must be correctable, or the
    first mis-click is permanent in the one table a human writes to.

    Nothing is versioned — §12 asks for a tally, not an audit trail, and the
    tag feeds no metric, so there is nothing downstream to reconcile.
    """
    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=100)
    target = view.rows.items[0].mismatch_id
    before = view.rows.total

    await mismatch_service.tag(target, tag=MismatchTag.UNCLEAR)
    await mismatch_service.tag(target, tag=MismatchTag.UNCLEAR)
    corrected = await mismatch_service.tag(target, tag=MismatchTag.STRUCTURED_DATA_ERROR)

    after = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=100)
    assert after.rows.total == before, "tagging added or removed a row"
    assert corrected.tag is MismatchTag.STRUCTURED_DATA_ERROR
    _, tagged = _counts(after, MismatchTag.STRUCTURED_DATA_ERROR)
    assert tagged == 1


async def test_clearing_removes_the_tag_the_timestamp_and_the_note(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """A cleared row that kept its `tagged_at` would read as reviewed in the
    Reviewed column while counting as untagged in the tally — two numbers on
    one screen, disagreeing."""
    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=100)
    target = view.rows.items[0].mismatch_id
    await mismatch_service.tag(target, tag=MismatchTag.UNCLEAR, note="hard to call")

    cleared = await mismatch_service.clear_tag(target)

    assert cleared.analyst_tag is None
    assert cleared.tag is None
    assert cleared.tagged_at is None
    assert cleared.note is None
    assert cleared.reviewed is False
    #: And the scorer's half is untouched by either write.
    assert cleared.evidence_span == view.rows.items[0].evidence_span
    assert cleared.record_value == view.rows.items[0].record_value
    assert cleared.extracted_value == view.rows.items[0].extracted_value


async def test_tagging_an_unknown_mismatch_is_a_not_found_error(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    with pytest.raises(NotFoundError):
        await mismatch_service.tag(MismatchId("nope"), tag=MismatchTag.UNCLEAR)
    with pytest.raises(NotFoundError):
        await mismatch_service.clear_tag(MismatchId("nope"))


async def test_tagging_changes_no_score_row(
    mismatch_service: MismatchService,
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**The test this phase exists to make** (mvp-spec.md §12, §17.3, R3).

    "The tag never feeds back into a metric. Nothing is rescored." The
    violation would be one convenient import and would be **invisible once
    made**: a number that moved because of a tag is not visibly wrong, it is
    just wrong.

    So: record every `score` row, tag every mismatch in the run with all three
    tags, and re-read them byte-identically. `n`, `value`, `ci_low` and
    `ci_high` are compared as stored, not rounded.
    """
    async with db_session_factory() as session:
        before = _score_rows(await _all_scores(session))
    assert before, "the fixture must produce scores for this test to mean anything"

    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=1000)
    assert view.rows.total > 0
    tags = (MismatchTag.HALLUCINATION, MismatchTag.STRUCTURED_DATA_ERROR, MismatchTag.UNCLEAR)
    for index, row in enumerate(view.rows.items):
        await mismatch_service.tag(row.mismatch_id, tag=tags[index % 3], note=f"note {index}")

    async with db_session_factory() as session:
        after = _score_rows(await _all_scores(session))

    assert after == before, "a tag moved a score row"


async def test_a_tag_survives_a_rescore_from_the_analysts_side(
    mismatch_service: MismatchService,
    scored: ScoredCorpus,
    scorer: ScoringService,
) -> None:
    """`SD21` re-asserted from the side a person would notice it (§11's second
    named assertion).

    Phase 4 proves the upsert preserves the column. This proves the analyst
    gets their judgement back through the surface they wrote it with — the one
    path where losing it would be discovered by a person rather than a test.
    """
    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=100)
    target = view.rows.items[0].mismatch_id
    await mismatch_service.tag(target, tag=MismatchTag.HALLUCINATION, note="kept")

    await scorer.rescore_run(scored.run_ids[0])

    after = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=100)
    stored = next((row for row in after.rows.items if row.mismatch_id == target), None)
    assert stored is not None, "the re-score dropped a tagged row"
    assert stored.tag is MismatchTag.HALLUCINATION
    assert stored.note == "kept"


# --- the tally --------------------------------------------------------------


async def test_the_tally_agrees_with_the_list_for_the_same_filter(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """**The second test this phase exists to make** (§17.4).

    One filter shape reaches both reads, so the strip under the table cannot
    disagree with the table. A strip that did would be worse than no strip:
    two numbers on one screen, and no way to tell which is the lie.
    """
    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=1000)
    assert view.rows.total > 4, "this needs a mix — some tagged, some not"
    for index, row in enumerate(view.rows.items[:4]):
        await mismatch_service.tag(
            row.mismatch_id,
            tag=MismatchTag.HALLUCINATION if index % 2 else MismatchTag.UNCLEAR,
        )

    after = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=1000)

    from_rows: dict[str, int] = {}
    for row in after.rows.items:
        if row.analyst_tag:
            from_rows[row.analyst_tag] = from_rows.get(row.analyst_tag, 0) + 1
    from_tally: dict[str, int] = {}
    for entry in after.tallies:
        for tag, count in entry.tally.counts.items():
            from_tally[tag.value] = from_tally.get(tag.value, 0) + count

    assert {tag: n for tag, n in from_tally.items() if n} == from_rows
    assert sum(entry.tally.total for entry in after.tallies) == after.rows.total
    assert sum(entry.tally.reviewed for entry in after.tallies) == 4
    #: And the untagged half, which is the one an all-tagged fixture would
    #: never exercise.
    assert sum(entry.tally.untagged for entry in after.tallies) == after.rows.total - 4


async def test_the_tally_is_per_feature_and_keyed_by_the_feature_key(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """mvp-spec.md §12's output is "a tally **per feature**"."""
    view = await mismatch_service.list_mismatches(
        scored.evaluation_id, feature_id=scored.feature_ids[WEATHER], page_size=100
    )

    assert [entry.feature_id for entry in view.tallies] == [scored.feature_ids[WEATHER]]
    assert view.tallies[0].feature_key == WEATHER
    assert view.tallies[0].tally.total == view.rows.total


async def test_the_feature_filter_options_are_not_narrowed_by_the_filter(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """A dropdown that collapsed to the one entry already chosen would be a
    dead control — there would be no way back out of the filter.

    The tally strip *is* scoped to the filter; the options are not, and the two
    being different lists is why `MismatchFeatureView` exists separately from
    `ReviewTallyView` (amendment: feat/p5-mismatch-domain-persistence).
    """
    unfiltered = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=1)
    filtered = await mismatch_service.list_mismatches(
        scored.evaluation_id, feature_id=scored.feature_ids[WEATHER], page_size=1
    )

    assert len(unfiltered.features) > 1
    assert [f.feature_id for f in filtered.features] == [f.feature_id for f in unfiltered.features]
    assert all(option.total > 0 for option in filtered.features)


async def test_the_protocol_tally_returns_counts_and_nothing_else(
    mismatch_service: MismatchService,
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`MismatchTally`, called the way a later Results surface would — with a
    session it owns, and keyed by `RunId` (§3.1, §17.6).

    It returns integers. The absence of anything else on that protocol is the
    contract, not an oversight.
    """
    async with db_session_factory() as session:
        counts = await mismatch_service.tally(session, scored.run_ids[0])

    assert counts, "the run has mismatches, so it has a tally"
    assert all(entry.reviewed == 0 for entry in counts.values()), "nothing tagged yet"
    assert all(entry.total == entry.untagged for entry in counts.values())


# --- the export -------------------------------------------------------------


async def test_the_csv_carries_the_tag_and_the_note(
    mismatch_service: MismatchService,
    scored: ScoredCorpus,
    export_service: ExportService,
) -> None:
    """`C6`. An export whose point is review has to carry the review — those
    three columns are the only data in the pipeline no re-run can reproduce."""
    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=1000)
    await mismatch_service.tag(
        view.rows.items[0].mismatch_id, tag=MismatchTag.UNCLEAR, note="text disagrees"
    )

    rows = await mismatch_service.export_rows(scored.evaluation_id)
    payload = export_service.mismatches_csv(
        rows.rows.items,
        evaluation_id=scored.evaluation_id,
        run_label=rows.run_label,
        filter_label="all tags",
    )
    text = payload.decode("utf-8-sig")

    assert payload.startswith(b"\xef\xbb\xbf"), "N3 — Excel on Windows needs the BOM"
    assert ";" in text
    assert "analyst_tag;tagged_at;note" in text
    assert "unclear" in text
    assert "text disagrees" in text
    #: mvp-spec.md §13 — the marking travels, because a CSV is read somewhere
    #: this app cannot see.
    assert "anonymised" in text


async def test_the_csv_honours_the_filter_and_the_sort_it_was_handed(
    mismatch_service: MismatchService,
    scored: ScoredCorpus,
    export_service: ExportService,
) -> None:
    """`P4-D3`, sw-design.md §7: an export writes the **currently filtered,
    currently sorted** table.

    Re-fetching inside the exporter is how a CSV comes to disagree with the
    screen it was exported from, which is why `mismatches_csv` takes the rows.
    """
    view = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=1000)
    for row in view.rows.items[:2]:
        await mismatch_service.tag(row.mismatch_id, tag=MismatchTag.HALLUCINATION)

    filtered = await mismatch_service.export_rows(
        scored.evaluation_id, tag_state=MismatchTag.HALLUCINATION
    )
    payload = export_service.mismatches_csv(
        filtered.rows.items,
        evaluation_id=scored.evaluation_id,
        run_label=filtered.run_label,
        filter_label="hallucination",
    )
    lines = payload.decode("utf-8-sig").splitlines()

    assert len(filtered.rows.items) == 2
    #: comment + header + two rows, and **not** the whole run.
    assert len(lines) == 4
    assert lines[0].startswith("# evaluation ")
    assert "hallucination" in lines[0]
    assert "2 mismatches, 2 reviewed" in lines[0]


async def test_the_export_is_unpaged_where_the_list_is_paged(
    mismatch_service: MismatchService, scored: ScoredCorpus
) -> None:
    """An export has no paging of its own (sw-design.md §7). It is a separate
    entry point so one cannot be produced by accident."""
    paged = await mismatch_service.list_mismatches(scored.evaluation_id, page_size=2)
    whole = await mismatch_service.export_rows(scored.evaluation_id)

    assert len(paged.rows.items) == 2
    assert len(whole.rows.items) == whole.rows.total == paged.rows.total
    assert whole.rows.total > 2


# --- helpers ----------------------------------------------------------------


async def _all_scores(session: AsyncSession) -> list[Score]:
    result = await session.execute(select(Score).order_by(Score.run_id, Score.feature_id))
    return list(result.scalars())


def _score_rows(rows: list[Score]) -> list[tuple[object, ...]]:
    """Every stored column of every `score` row, as comparable tuples.

    Values are compared **as stored**, not rounded: a re-score that shifted a
    rate in the fifteenth decimal would still be a re-score.
    """
    return sorted(
        (
            row.run_id,
            row.feature_id,
            row.language,
            row.metric,
            row.value,
            row.n,
            row.ci_low,
            row.ci_high,
        )
        for row in rows
    )


def _counts(view: MismatchListView, tag: MismatchTag) -> tuple[int, int]:
    """(total, rows carrying `tag`) across the view's tallies."""
    total = sum(entry.tally.total for entry in view.tallies)
    tagged = sum(entry.tally.counts[tag] for entry in view.tallies)
    return total, tagged
