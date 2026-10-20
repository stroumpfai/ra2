# STUB — bodies owned by Y1 (feat/p5-mismatch-service). Not frozen.
"""Mismatch review (mvp-spec.md §12, sw-design.md §17).

The list, the tag, the tally and the export rows. **The first service in this
codebase through which a human writes to the database**, and every rule below
follows from that sentence.

**This module imports nothing from `scoring_service` or `ranking_service`, and
that is the contract.** `mvp-spec.md` §12: *"The tag never feeds back into a
metric. Nothing is rescored."* The absence of the edge is what makes it true —
a rule nobody can violate beats a rule everybody remembers, and this one would
be invisible once violated, because a number that moved because of a tag is
not visibly wrong (§17.3, R3). `tests/test_p5_contract.py` asserts the absence
on this module's AST.

**It writes three columns.** `analyst_tag`, `tagged_at` and `note` are review's
half of `mismatch`; `record_value`, `extracted_value` and `evidence_span` are
the scorer's and are never touched here (§17.1). The mirror of that obligation
— the tag-preserving upsert — has been built and tested since phase 4
(`SD21`).

**One run at a time** (§17.6, `SD26`). `list_mismatches` resolves an
evaluation to one of its runs the same way `ResultsService.presence_records`
resolves one model, and there is no "all runs" scope to represent.

**M35 froze the constructor and the signatures; Y1 wrote the bodies.**
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.anonymisation import DeliveredTextAnonymised, anonymisation_marking
from ra2.domain.code_label import DecodedValue, by_code, decode
from ra2.domain.codes import CodeValue
from ra2.domain.feature import Kind, ValueType, derivation_from_json
from ra2.domain.ids import EvaluationId, FeatureId, MismatchId, RunId
from ra2.domain.mismatch import MismatchTag, ReviewTally, TagFilter, TagState, tally
from ra2.domain.span_locate import locate
from ra2.infra.clock import Clock
from ra2.persistence.models import Evaluation, EvaluationFeature, Feature, Mismatch, Record, Run
from ra2.persistence.repositories.mismatch_repo import MismatchListRow, MismatchRepository
from ra2.persistence.session import session_scope
from ra2.services.errors import NotFoundError
from ra2.services.evaluation_service import snapshot_from_json
from ra2.services.feature_service import matching_rule_from_json
from ra2.services.readmodels import (
    MismatchDetailView,
    MismatchFeatureView,
    MismatchFilters,
    MismatchListView,
    MismatchRowView,
    ModelColumnView,
    Page,
    ReviewTallyView,
    SortDir,
)
from ra2.services.run_descriptor import build_descriptor

__all__ = ["MismatchService"]

#: What an export asks the repository for in place of a page. An export has no
#: paging of its own (sw-design.md §7), and this is the same shape
#: `presence.py` already uses for the one it writes.
_EXPORT_LIMIT = 100_000


class MismatchService:
    """Implements `services.protocols.MismatchTally` (structurally — no
    Results surface imports this module)."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        delivered_text_anonymised: DeliveredTextAnonymised = DeliveredTextAnonymised.UNKNOWN,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        #: `SD50`, risk B5: the supplier's answer, as configured. Decides what
        #: the marking may claim for a delivered narrative.
        self._delivered = delivered_text_anonymised

    async def list_mismatches(
        self,
        evaluation_id: EvaluationId,
        *,
        run_id: RunId | None = None,
        feature_id: FeatureId | None = None,
        tag_state: TagFilter = TagState.ANY,
        sort_key: str = "feature",
        sort_dir: SortDir = SortDir.ASC,
        page: int = 1,
        page_size: int = 25,
    ) -> MismatchListView:
        """The whole screen for one run of one evaluation.

        `run_id=None` picks the evaluation's first run, the resolution
        `ResultsService.presence_records` already uses — there is no "all runs"
        option, because a mixed list is the cross-model agreement §16.9 defers
        (§17.6).

        The tallies it returns are scoped to the **same filters** as the rows,
        so the strip under the table can never disagree with the table.
        """
        offset = max(0, (page - 1) * page_size)
        return await self._view(
            evaluation_id,
            run_id=run_id,
            feature_id=feature_id,
            tag_state=tag_state,
            sort_key=sort_key,
            sort_dir=sort_dir,
            page=page,
            page_size=page_size,
            offset=offset,
            limit=page_size,
        )

    async def tag(
        self,
        mismatch_id: MismatchId,
        *,
        tag: MismatchTag,
        note: str | None = None,
    ) -> MismatchRowView:
        """Write one analyst's judgement, and stamp `tagged_at`.

        **Idempotent**: the same tag twice leaves one row. Re-tagging restamps,
        because the second judgement is the current one (Q4 — a judgement made
        on the wrong row must be correctable, or the first mis-click is
        permanent in the one table a human writes to).

        The parameter is a `MismatchTag`, not a `str`: the column is open so a
        fourth tag needs no migration, but nothing in this codebase may *write*
        a value outside the three (`SD24`, §17.5).

        **Changes no `score` row.** There is no path from here to scoring, and
        the test that proves it records every `score` row, tags every mismatch
        and re-reads them byte-identically.
        """
        return await self._write(mismatch_id, tag=tag.value, note=note)

    async def clear_tag(self, mismatch_id: MismatchId) -> MismatchRowView:
        """Remove the tag, **and `tagged_at` with it** (Q4).

        A cleared row that kept its timestamp would read as reviewed in the
        `Reviewed` column while counting as untagged in the tally. `note` is
        cleared too: it annotated a judgement that no longer exists.
        """
        return await self._write(mismatch_id, tag=None, note=None)

    async def detail(self, mismatch_id: MismatchId) -> MismatchDetailView:
        """One row, opened: the narrative with the span located in it, and the
        feature's facts (`SD70`).

        **Read when a row is opened, never with the page.** The narrative is
        record text; a page shows at most one, so loading 25 would move text
        through every render for nothing.

        `NotFoundError` for an unknown id, which is also what a row whose run
        was discarded under an open tab becomes.
        """
        async with self._session_factory() as session:
            found = (
                await session.execute(
                    select(Mismatch, Record, Feature, Evaluation)
                    .join(Record, Record.id == Mismatch.record_id)
                    .join(Feature, Feature.id == Mismatch.feature_id)
                    .join(Run, Run.id == Mismatch.run_id)
                    .join(Evaluation, Evaluation.id == Run.evaluation_id)
                    .where(Mismatch.id == mismatch_id)
                )
            ).first()
            if found is None:
                raise NotFoundError("mismatch", mismatch_id)
            mismatch, record, feature, evaluation = found
            feature_id = FeatureId(feature.id)
            codebook = await _codebook(session, evaluation, feature_id=feature_id)
            return MismatchDetailView(
                mismatch_id=MismatchId(mismatch.id),
                unfall_uid=record.unfall_uid,
                narrative=record.text_raw,
                highlights=locate(record.text_raw, mismatch.evidence_span),
                language=record.language,
                language_confidence=record.language_confidence,
                anonymisation=anonymisation_marking(record.text_anonymised_flag, self._delivered),
                feature_key=feature.key,
                feature_description=feature.description,
                # Narrowed, not trusted: the columns are typed `Kind` and
                # `ValueType`, but a row the session already holds comes back
                # as it was written, which may be the plain string. The read
                # model promises the enum, so this is where it becomes one.
                kind=Kind(feature.kind),
                value_type=ValueType(feature.value_type),
                matching_rule=matching_rule_from_json(feature.matching_rule),
                source_column=feature.source_column,
                derivation=(
                    derivation_from_json(feature.derivation_json)
                    if feature.derivation_json
                    else None
                ),
                record_decoded=codebook.decode(feature_id, mismatch.record_value),
                extracted_decoded=codebook.decode(feature_id, mismatch.extracted_value),
                evidence_span=mismatch.evidence_span,
            )

    async def tally(self, session: AsyncSession, run_id: RunId) -> Mapping[FeatureId, ReviewTally]:
        """`services.protocols.MismatchTally` — per-feature review counts.

        Takes the session because the caller owns the transaction boundary,
        like every other protocol in that module. **Returns counts and nothing
        else**; there is deliberately no sibling that could influence a score.
        """
        grouped = await MismatchRepository(session).tally_for(run_id)
        return {feature_id: tally(counts) for feature_id, counts in grouped.items()}

    async def export_rows(
        self,
        evaluation_id: EvaluationId,
        *,
        run_id: RunId | None = None,
        feature_id: FeatureId | None = None,
        tag_state: TagFilter = TagState.ANY,
        sort_key: str = "feature",
        sort_dir: SortDir = SortDir.ASC,
    ) -> MismatchListView:
        """The same list, **unpaged**, for the CSV.

        A separate entry point rather than a `page_size=None` flag on
        `list_mismatches`, so an export cannot be produced by accident and the
        one that is produced carries the same view — the same descriptor, the
        same run, the same filters — as the screen it was exported from
        (`P4-D3`, sw-design.md §7).
        """
        return await self._view(
            evaluation_id,
            run_id=run_id,
            feature_id=feature_id,
            tag_state=tag_state,
            sort_key=sort_key,
            sort_dir=sort_dir,
            page=1,
            page_size=_EXPORT_LIMIT,
            offset=0,
            limit=_EXPORT_LIMIT,
        )

    # --- one read, two entry points ----------------------------------------
    #
    # `list_mismatches` and `export_rows` differ only in how much they ask for.
    # They share this so a CSV cannot be assembled from a different filter, a
    # different sort or a different run than the screen it was exported from —
    # which is the failure `P4-D3` describes and the reason the exporter takes
    # rows rather than a filter to re-run.

    async def _view(
        self,
        evaluation_id: EvaluationId,
        *,
        run_id: RunId | None,
        feature_id: FeatureId | None,
        tag_state: TagFilter,
        sort_key: str,
        sort_dir: SortDir,
        page: int,
        page_size: int,
        offset: int,
        limit: int,
    ) -> MismatchListView:
        async with self._session_factory() as session:
            evaluation = await session.get(Evaluation, evaluation_id)
            if evaluation is None:
                raise NotFoundError("evaluation", evaluation_id)
            runs = await _runs_for(session, evaluation_id)
            if not runs:
                raise NotFoundError("run", evaluation_id)
            chosen = next((run for run in runs if run.id == run_id), runs[0])
            keys = {
                FeatureId(feature.id): feature.key
                for feature in await _features_for(session, evaluation_id)
            }

            codebook = await _codebook(session, evaluation)
            repo = MismatchRepository(session)
            rows, total = await repo.list_for(
                RunId(chosen.id),
                feature_id=feature_id,
                tag_state=tag_state,
                sort_key=sort_key,
                descending=sort_dir is SortDir.DESC,
                offset=offset,
                limit=limit,
            )
            # Scoped to the same filters as the rows, so the strip under the
            # table and the table itself cannot answer different questions
            # (§17.4). The Feature filter's options are the *unfiltered*
            # counts, because a dropdown that collapsed to the one entry
            # already chosen would be a dead control.
            tallies = await repo.tally_for(
                RunId(chosen.id), feature_id=feature_id, tag_state=tag_state
            )
            options = await repo.tally_for(RunId(chosen.id))

            return MismatchListView(
                descriptor=await build_descriptor(session, evaluation, runs),
                runs=tuple(
                    ModelColumnView(model_id=run.id, tag=run.model_name, digest=run.model_digest)
                    for run in runs
                ),
                run_label=_run_label(chosen, runs),
                run_finished_at=chosen.finished_at,
                features=tuple(
                    MismatchFeatureView(
                        feature_id=found,
                        feature_key=keys.get(found, str(found)),
                        total=sum(counts.values()),
                    )
                    for found, counts in sorted(
                        options.items(), key=lambda item: keys.get(item[0], str(item[0]))
                    )
                ),
                filters=MismatchFilters(
                    run_id=RunId(chosen.id),
                    feature_id=feature_id,
                    tag_state=tag_state,
                ),
                rows=Page(
                    items=tuple(_row_view(row, self._delivered, codebook) for row in rows),
                    total=total,
                    page=page,
                    page_size=page_size,
                    sort_key=sort_key,
                    sort_dir=sort_dir,
                ),
                tallies=tuple(
                    ReviewTallyView(
                        feature_id=found,
                        feature_key=keys.get(found, str(found)),
                        tally=tally(counts),
                    )
                    for found, counts in sorted(
                        tallies.items(), key=lambda item: keys.get(item[0], str(item[0]))
                    )
                ),
            )

    async def _write(
        self, mismatch_id: MismatchId, *, tag: str | None, note: str | None
    ) -> MismatchRowView:
        """The one write in this service, and the only place `tagged_at` is
        stamped.

        `tag` reaches the repository as a plain string because that is what the
        column holds; it arrives here already narrowed to `MismatchTag` or
        `None`, so no caller can widen the vocabulary by passing one through.
        """
        async with session_scope(self._session_factory) as session:
            row = await MismatchRepository(session).set_tag(
                mismatch_id, tag=tag, note=note, now=self._clock.now()
            )
            if row is None:
                raise NotFoundError("mismatch", mismatch_id)
            evaluation = await session.scalar(
                select(Evaluation)
                .join(Run, Run.evaluation_id == Evaluation.id)
                .join(Mismatch, Mismatch.run_id == Run.id)
                .where(Mismatch.id == mismatch_id)
            )
            if evaluation is None:
                raise NotFoundError("mismatch", mismatch_id)
            #: Only this row's feature: a tag click decodes one row, and
            #: parsing every code table in the evaluation for it is waste.
            codebook = await _codebook(session, evaluation, feature_id=row.feature_id)
            return _row_view(row, self._delivered, codebook)


# ---------------------------------------------------------------------------
# Reads. Nothing here reaches a `Score`, an `Outcome` or a `ScoreMetric`, and
# nothing imports a scoring module — §17.3's absent edge, which
# `tests/test_p5_contract.py` asserts on this module's AST.
# ---------------------------------------------------------------------------


async def _runs_for(session: AsyncSession, evaluation_id: EvaluationId) -> list[Run]:
    result = await session.execute(
        select(Run).where(Run.evaluation_id == evaluation_id).order_by(Run.id)
    )
    return list(result.scalars())


async def _features_for(session: AsyncSession, evaluation_id: EvaluationId) -> list[Feature]:
    result = await session.execute(
        select(Feature)
        .join(Evaluation, Evaluation.feature_config_id == Feature.feature_config_id)
        .where(Evaluation.id == evaluation_id)
        .order_by(Feature.ordinal)
    )
    return list(result.scalars())


@dataclass(frozen=True, slots=True)
class _Codebook:
    """The code tables one evaluation's model was shown, and the language it
    was asked in (`SD70`).

    Read from `evaluation_feature.enum_codelist_json`, **not** from the live
    Codelists mapping: a mapping changed after launch must not relabel an
    answer given before it. A feature with no snapshot (not an enum, or an
    evaluation launched before snapshots existed) decodes as `not_enum`.
    """

    language: str
    codes: Mapping[FeatureId, Mapping[str, CodeValue] | None]

    def decode(self, feature_id: FeatureId, value: str | None) -> DecodedValue:
        return decode(value, self.codes.get(feature_id), self.language)


async def _codebook(
    session: AsyncSession, evaluation: Evaluation, *, feature_id: FeatureId | None = None
) -> _Codebook:
    """**One statement per page**, however many rows or features: the
    snapshots are read once, keyed by code once, and every row decodes
    against the result. `feature_id` narrows it to one feature's table."""
    query = select(EvaluationFeature.feature_id, EvaluationFeature.enum_codelist_json).where(
        EvaluationFeature.evaluation_id == evaluation.id
    )
    if feature_id is not None:
        query = query.where(EvaluationFeature.feature_id == feature_id)
    result = await session.execute(query)
    return _Codebook(
        language=evaluation.prompt_language,
        codes={
            FeatureId(found): by_code(snapshot_from_json(payload)) if payload else None
            for found, payload in result.all()
        },
    )


def _row_view(
    row: MismatchListRow, delivered: DeliveredTextAnonymised, codebook: _Codebook
) -> MismatchRowView:
    """The repository's row as the read model `ui/` renders.

    A straight mapping, deliberately: `analyst_tag` crosses **verbatim** and is
    narrowed by `MismatchRowView.tag` / `.is_other`, in one place, so a value
    `MismatchTag` does not name survives to the screen (`SD24`, §17.5). The
    two values cross verbatim too; their decodings travel beside them.
    """
    return MismatchRowView(
        mismatch_id=row.id,
        record_id=row.record_id,
        anonymised=row.anonymised,
        feature_id=row.feature_id,
        feature_key=row.feature_key,
        record_value=row.record_value,
        extracted_value=row.extracted_value,
        evidence_span=row.evidence_span,
        analyst_tag=row.analyst_tag,
        tagged_at=row.tagged_at,
        note=row.note,
        anonymisation=anonymisation_marking(row.anonymised, delivered),
        unfall_uid=row.unfall_uid,
        record_decoded=codebook.decode(row.feature_id, row.record_value),
        extracted_decoded=codebook.decode(row.feature_id, row.extracted_value),
    )


def _run_label(chosen: Run, runs: Sequence[Run]) -> str:
    """`run 2 · qwen3:14b` — which of the evaluation's runs this list shows.

    The ordinal is the run's position within its own evaluation, not its id:
    the toolbar has to name one of two or three models, and an opaque id names
    nothing. `lifecycle_service`'s discard dialog composes its lead sentence
    the same way.
    """
    ordinal = next((i for i, run in enumerate(runs, start=1) if run.id == chosen.id), 1)
    return f"run {ordinal} · {chosen.model_name}"
