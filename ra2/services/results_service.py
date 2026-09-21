# STUB — bodies owned by T2 (feat/p4-results-service). Not frozen.
"""Tabs 1 and 2 (sw-design.md §16.7).

Reads `score` and `mismatch` rows and assembles the read models. **This is
where suppression is applied** — every cell is computed and stored by T1, and
this layer substitutes `SuppressedCell` when `n < evaluation.min_cell_count`
(`SD19`). Two things follow, and both are the point: changing the floor never
requires a re-score, and a suppressed cell is a shape carrying its `n` rather
than a number, an empty string or a `None`.

Two invariants this module must not lose:

- **Suppressed rows sort last, in both directions** — never as `0`. A
  suppressed row sorting as zero silently ranks the least-evidenced feature as
  the worst-performing one (R7).
- **Goal 2 numbers never travel without their Goal 1 companions** (§11.2). The
  read model makes that a type error (`PresenceRow.goal1`), but the query has
  to fetch them, and a "just the rates" shortcut is the thing not to add.

**M27 freezes the constructor and the signatures. T2 writes the bodies.**
"""

import json
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.extraction import RunStatus
from ra2.domain.feature import Kind
from ra2.domain.ids import EvaluationId, FeatureId, RecordId, RunId
from ra2.domain.scoring import ALL_LANGUAGES, ScoreMetric
from ra2.domain.stats import Interval, TiedCell, TieMark, mark_ties, suppressed
from ra2.persistence.models import (
    Evaluation,
    Extraction,
    ExtractionValue,
    Feature,
    Record,
    Run,
    Score,
    UnfallRow,
)
from ra2.persistence.repositories.score_repo import ScoreRepository
from ra2.services.errors import NotFoundError
from ra2.services.protocols import Scorer
from ra2.services.readmodels import (
    BreakdownRowView,
    BreakdownView,
    ByLanguageRow,
    ByLanguageView,
    Cell,
    CrossTabView,
    ExtractionTabView,
    FeatureScoreRow,
    FlagInconsistencyRow,
    Goal1Companion,
    MetricCell,
    ModelColumnView,
    Page,
    PerRecordRow,
    PresenceRow,
    PresenceTabView,
    ScoringStatusView,
    SortDir,
    SuppressedCell,
)
from ra2.services.run_descriptor import build_descriptor

__all__ = ["ResultsService"]

#: The per-record finding, `design/results/README.md` §2e's own sentence.
#: Composed here rather than in `ui/` because `PerRecordRow.finding` is a
#: frozen field of the read model — but it is **copy**, and the wording lives
#: in exactly this one place for the same reason `FindingCode` wording does.
PRESENCE_FINDING = "This report does not say what the {feature} was."

#: `(run, feature, language) -> {metric: Score}` — the shape every read below
#: works from. Built once per request, because five tables' worth of cells all
#: come out of the same rows.
type _Cells = Mapping[tuple[str, str, str], Mapping[ScoreMetric, Score]]


class ResultsService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        scorer: Scorer,
    ) -> None:
        self._session_factory = session_factory
        self._scorer = scorer

    async def scoring_status(self, evaluation_id: EvaluationId) -> tuple[ScoringStatusView, ...]:
        """One status per run — which of §16.7's three states each tab renders."""
        async with self._session_factory() as session:
            runs = await _runs_for(session, evaluation_id)
            statuses = []
            for run in runs:
                status = await self._scorer.status(session, RunId(run.id))
                statuses.append(
                    ScoringStatusView(
                        run_id=RunId(run.id),
                        scored_features=status.scored_features,
                        labelled_features=status.labelled_features,
                        running=status.running,
                        # Read off the row this loop already holds. The
                        # `Scorer` seam answers "how far did the scoring get";
                        # "is the run over" is the run's own column, and
                        # widening the protocol to carry it would make
                        # `ScoringStatus` a second place to ask.
                        run_status=RunStatus(run.status),
                    )
                )
            return tuple(statuses)

    async def extraction_tab(
        self,
        evaluation_id: EvaluationId,
        *,
        page: int = 1,
        page_size: int = 10,
        sort_key: str = "name",
        sort_dir: SortDir = SortDir.ASC,
        expanded_feature_id: FeatureId | None = None,
        by_language_feature_id: FeatureId | None = None,
        by_language_model_id: str | None = None,
    ) -> ExtractionTabView:
        """Tab 1. Suppressed rows sort **last** whichever way `sort_dir` points."""
        async with self._session_factory() as session:
            evaluation = await session.get(Evaluation, evaluation_id)
            if evaluation is None:
                raise NotFoundError("evaluation", evaluation_id)
            runs = await _runs_for(session, evaluation_id)
            features = await _features_for(session, evaluation_id)
            cells = await _load_cells(session, runs)
            floor = evaluation.min_cell_count

            models = tuple(
                ModelColumnView(model_id=run.id, tag=run.model_name, digest=run.model_digest)
                for run in runs
            )
            rows = [
                _feature_row(feature, runs, cells, floor)
                for feature in features
                if feature.kind == Kind.LABELLED
            ]
            # A feature with no `score` rows at all was never scoreable (§8.6);
            # it is absent from the table rather than rendered as an empty row.
            rows = [row for row in rows if row.n > 0]
            rows = _sorted(rows, sort_key=sort_key, sort_dir=sort_dir)

            total = len(rows)
            start = max(0, (page - 1) * page_size)
            paged = rows[start : start + page_size]

            breakdown = None
            if expanded_feature_id is not None:
                breakdown = _breakdown(expanded_feature_id, features, runs, cells)
            by_language = None
            if by_language_feature_id is not None and by_language_model_id is not None:
                by_language = _by_language(
                    by_language_feature_id, by_language_model_id, features, cells, floor
                )

            return ExtractionTabView(
                descriptor=await build_descriptor(session, evaluation, runs),
                models=models,
                features=Page(
                    items=tuple(paged),
                    total=total,
                    page=page,
                    page_size=page_size,
                    sort_key=sort_key,
                    sort_dir=sort_dir,
                ),
                breakdown=breakdown,
                by_language=by_language,
                exploratory=(),
            )

    async def breakdown(self, run_ids: tuple[RunId, ...], feature_id: FeatureId) -> BreakdownView:
        """The expanded row: P · R · F1 · hit · wrong · missing per model."""
        async with self._session_factory() as session:
            runs = await _runs_by_id(session, run_ids)
            feature = await session.get(Feature, feature_id)
            if feature is None:
                raise NotFoundError("feature", feature_id)
            cells = await _load_cells(session, runs)
            view = _breakdown(feature_id, [feature], runs, cells)
            assert view is not None, "the feature was fetched by id above"
            return view

    async def by_language(self, run_id: RunId, feature_id: FeatureId) -> ByLanguageView:
        """One feature × model across languages, with the standing encoding
        caveat this breakdown may never be shown without (mvp-spec.md §13)."""
        async with self._session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise NotFoundError("run", run_id)
            feature = await session.get(Feature, feature_id)
            if feature is None:
                raise NotFoundError("feature", feature_id)
            evaluation = await session.get(Evaluation, run.evaluation_id)
            assert evaluation is not None
            cells = await _load_cells(session, [run])
            view = _by_language(feature_id, run_id, [feature], cells, evaluation.min_cell_count)
            assert view is not None, "the feature was fetched by id above"
            return view

    async def presence_tab(
        self,
        evaluation_id: EvaluationId,
        *,
        model_id: str | None = None,
        feature_key: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> PresenceTabView:
        """Tab 2, one model at a time. `model_id=None` picks the first run's."""
        async with self._session_factory() as session:
            evaluation = await session.get(Evaluation, evaluation_id)
            if evaluation is None:
                raise NotFoundError("evaluation", evaluation_id)
            runs = await _runs_for(session, evaluation_id)
            if not runs:
                raise NotFoundError("run", evaluation_id)
            chosen = next((r for r in runs if r.id == model_id), runs[0])
            features = await _features_for(session, evaluation_id)
            # Every run's cells, not just the chosen one's: the rate table and
            # the cross-tab are one model at a time, but the flag-inconsistency
            # card is **one row per model** (design README §2d) — it exists so
            # the flag itself can be compared across models.
            cells = await _load_cells(session, runs)
            floor = evaluation.min_cell_count

            rows = tuple(
                row
                for feature in features
                if feature.kind == Kind.LABELLED
                for row in _presence_row(feature, chosen, cells, floor)
            )
            return PresenceTabView(
                descriptor=await build_descriptor(session, evaluation, runs),
                models=tuple(
                    ModelColumnView(model_id=r.id, tag=r.model_name, digest=r.model_digest)
                    for r in runs
                ),
                model_id=chosen.id,
                rows=rows,
                cross_tab=_cross_tab(features, chosen, cells, feature_key),
                flag_inconsistency=_flag_inconsistency(runs, features, cells, floor),
                records=await self._presence_records(
                    session, chosen, features, feature_key, page=page, page_size=page_size
                ),
            )

    async def presence_records(
        self,
        evaluation_id: EvaluationId,
        *,
        model_id: str | None = None,
        feature_key: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Page[PerRecordRow]:
        """**The actionable form of Goal 2** (design README §2e).

        Every record whose column *is* populated and which the model flagged as
        **not present** in the narrative: "this report does not say what the
        weather was". Goal 2 is consumed as a record list to act on, not as a
        rate, which is why this is a first-class read rather than a detail of
        the tab.
        """
        async with self._session_factory() as session:
            evaluation = await session.get(Evaluation, evaluation_id)
            if evaluation is None:
                raise NotFoundError("evaluation", evaluation_id)
            runs = await _runs_for(session, evaluation_id)
            if not runs:
                raise NotFoundError("run", evaluation_id)
            chosen = next((r for r in runs if r.id == model_id), runs[0])
            features = await _features_for(session, evaluation_id)
            page_view = await self._presence_records(
                session, chosen, features, feature_key, page=page, page_size=page_size
            )
            if page_view is None:
                raise NotFoundError("feature", feature_key or "")
            return page_view

    async def _presence_records(
        self,
        session: AsyncSession,
        run: Run,
        features: Sequence[Feature],
        feature_key: str | None,
        *,
        page: int,
        page_size: int,
    ) -> Page[PerRecordRow] | None:
        feature = next(
            (f for f in features if feature_key is not None and f.key == feature_key),
            next((f for f in features if f.kind == Kind.LABELLED), None),
        )
        if feature is None:
            return None
        rows = await _records_not_written(session, run, feature)
        start = max(0, (page - 1) * page_size)
        return Page(
            items=tuple(rows[start : start + page_size]),
            total=len(rows),
            page=page,
            page_size=page_size,
            sort_key="record_id",
            sort_dir=SortDir.ASC,
        )


# ---------------------------------------------------------------------------
# Reads. Suppression lives here (SD19): every cell is computed and stored by
# T1, and this layer substitutes the insufficient-data shape from the stored
# `n` against the evaluation's own floor — which is what lets the floor change
# without a re-score.
# ---------------------------------------------------------------------------


async def _runs_for(session: AsyncSession, evaluation_id: EvaluationId) -> list[Run]:
    result = await session.execute(
        select(Run).where(Run.evaluation_id == evaluation_id).order_by(Run.id)
    )
    return list(result.scalars())


async def _runs_by_id(session: AsyncSession, run_ids: Sequence[RunId]) -> list[Run]:
    result = await session.execute(select(Run).where(Run.id.in_(run_ids)).order_by(Run.id))
    return list(result.scalars())


async def _features_for(session: AsyncSession, evaluation_id: EvaluationId) -> list[Feature]:
    result = await session.execute(
        select(Feature)
        .join(Evaluation, Evaluation.feature_config_id == Feature.feature_config_id)
        .where(Evaluation.id == evaluation_id)
        .order_by(Feature.ordinal)
    )
    return list(result.scalars())


async def _load_cells(session: AsyncSession, runs: Sequence[Run]) -> _Cells:
    """Every stored cell for these runs, in one query per run.

    The whole tab is a read over `score`, so fetching per feature would turn a
    13-feature table into 13 round trips for numbers that all live in the same
    rows.
    """
    cells: dict[tuple[str, str, str], dict[ScoreMetric, Score]] = {}
    for run in runs:
        for row in await ScoreRepository(session).for_run(RunId(run.id)):
            key = (row.run_id, row.feature_id, row.language)
            cells.setdefault(key, {})[ScoreMetric(row.metric)] = row
    return cells


def _cell(
    stored: Mapping[ScoreMetric, Score] | None, metric: ScoreMetric, floor: int, *, mark: TieMark
) -> Cell | None:
    """One rendered cell, or `None` when this feature was never scored here.

    **This is where `mvp-spec.md` §11.4 is enforced.** Below the floor the
    number does not travel: `SuppressedCell` has no `value` field, so it cannot
    be formatted into a string by accident and cannot be sorted as zero.
    """
    if not stored or metric not in stored:
        return None
    row = stored[metric]
    if suppressed(row.n, floor):
        return SuppressedCell(n=row.n, floor=floor)
    return MetricCell(
        value=row.value,
        ci_low=row.ci_low if row.ci_low is not None else row.value,
        ci_high=row.ci_high if row.ci_high is not None else row.value,
        n=row.n,
        mark=mark,
    )


def _feature_row(
    feature: Feature, runs: Sequence[Run], cells: _Cells, floor: int
) -> FeatureScoreRow:
    """One row of tab 1: the feature, its `n`, and one cell per model."""
    stored = {run.id: cells.get((run.id, feature.id, ALL_LANGUAGES)) for run in runs}
    counts = [row[ScoreMetric.F1].n for row in stored.values() if row and ScoreMetric.F1 in row]
    n = max(counts) if counts else 0
    row_suppressed = bool(counts) and suppressed(n, floor)

    # Marks are computed over the **non-suppressed** cells only: a suppressed
    # cell has no point estimate to compare, and including it would let a
    # feature nobody measured decide who leads (§16.4).
    comparable = [
        (run.id, row[ScoreMetric.F1])
        for run in runs
        if (row := stored.get(run.id))
        and ScoreMetric.F1 in row
        and not suppressed(row[ScoreMetric.F1].n, floor)
    ]
    marks: dict[str, TieMark] = {}
    if comparable:
        computed = mark_ties(
            [
                TiedCell(
                    point=score.value,
                    interval=Interval(
                        low=score.ci_low if score.ci_low is not None else score.value,
                        high=score.ci_high if score.ci_high is not None else score.value,
                        n=score.n,
                    ),
                )
                for _, score in comparable
            ]
        )
        marks = {run_id: mark for (run_id, _), mark in zip(comparable, computed, strict=True)}

    return FeatureScoreRow(
        feature_id=FeatureId(feature.id),
        name=feature.key,
        source_label=_source_label(feature),
        n=n,
        suppressed=row_suppressed,
        cells={
            run.id: cell
            for run in runs
            if (
                cell := _cell(
                    stored.get(run.id),
                    ScoreMetric.F1,
                    floor,
                    mark=marks.get(run.id, TieMark.NONE),
                )
            )
            is not None
        },
    )


def _source_label(feature: Feature) -> str:
    """`Witter0Ausw · enum`, or `derived · count_objects · integer`."""
    value_type = feature.value_type or ""
    if feature.source_column:
        return f"{feature.source_column} · {value_type}"
    kind = ""
    if feature.derivation_json:
        kind = str(json.loads(feature.derivation_json).get("type", ""))
    return f"derived · {kind} · {value_type}"


def _sorted(
    rows: Sequence[FeatureScoreRow], *, sort_key: str, sort_dir: SortDir
) -> list[FeatureScoreRow]:
    """**Suppressed rows sort last, in both directions** (R7).

    A suppressed row sorting as zero silently ranks the least-evidenced
    feature as the worst-performing one — which is the opposite of what
    suppression is for.
    """
    descending = sort_dir is SortDir.DESC

    numeric = sort_key == "n" or any(sort_key in row.cells for row in rows)

    def numeric_key(row: FeatureScoreRow) -> tuple[bool, float, str]:
        if sort_key == "n":
            value = float(row.n)
        else:
            cell = row.cells.get(sort_key)
            # A suppressed cell has no value to sort on, and `0.0` is exactly
            # the wrong stand-in — the flag below is what keeps it last.
            value = cell.value if isinstance(cell, MetricCell) else 0.0
        # Negating for descending rather than reversing the whole list is what
        # keeps `suppressed` pushing rows DOWN in both directions (R7).
        return (row.suppressed, -value if descending else value, row.name)

    if numeric:
        return sorted(rows, key=numeric_key)
    # Two stable passes: order by name, then float the suppressed rows to the
    # bottom. `sorted` is stable, so the name order survives inside each group
    # — and the suppressed rows stay last whichever way the names run (R7).
    by_name = sorted(rows, key=lambda row: row.name, reverse=descending)
    return sorted(by_name, key=lambda row: row.suppressed)


def _breakdown(
    feature_id: FeatureId, features: Sequence[Feature], runs: Sequence[Run], cells: _Cells
) -> BreakdownView | None:
    feature = next((f for f in features if f.id == feature_id), None)
    if feature is None:
        return None
    rows: list[BreakdownRowView] = []
    for run in runs:
        stored = cells.get((run.id, feature_id, ALL_LANGUAGES))
        if not stored or ScoreMetric.F1 not in stored:
            continue
        rows.append(
            BreakdownRowView(
                model_id=run.id,
                precision=stored[ScoreMetric.PRECISION].value,
                recall=stored[ScoreMetric.RECALL].value,
                f1=stored[ScoreMetric.F1].value,
                # Stored, not back-derived from P and R (SD18).
                hit=int(stored[ScoreMetric.HIT].value),
                wrong=int(stored[ScoreMetric.WRONG].value),
                missing=int(stored[ScoreMetric.MISSING].value),
            )
        )
    return BreakdownView(feature_id=feature_id, feature_name=feature.key, rows=tuple(rows))


def _by_language(
    feature_id: FeatureId,
    model_id: str,
    features: Sequence[Feature],
    cells: _Cells,
    floor: int,
) -> ByLanguageView | None:
    feature = next((f for f in features if f.id == feature_id), None)
    if feature is None:
        return None
    languages = sorted(
        language
        for (run_id, stored_feature, language) in cells
        if run_id == model_id and stored_feature == feature_id and language != ALL_LANGUAGES
    )
    rows = [
        ByLanguageRow(language=language, cell=cell)
        for language in languages
        if (
            cell := _cell(
                cells.get((model_id, feature_id, language)),
                ScoreMetric.F1,
                floor,
                mark=TieMark.NONE,
            )
        )
        is not None
    ]
    return ByLanguageView(
        feature_id=feature_id,
        feature_name=feature.key,
        model_id=model_id,
        rows=tuple(rows),
    )


def _presence_row(feature: Feature, run: Run, cells: _Cells, floor: int) -> list[PresenceRow]:
    """One feature's presence rates **and its Goal 1 companions**.

    mvp-spec.md §11.2: "Goal 2 numbers are never published without the
    corresponding Goal 1 numbers — a weak extractor manufactures false
    'missing' flags." `PresenceRow.goal1` is a required field, so this function
    cannot return a row without them; if the Goal 1 rows are missing the
    presence row is withheld entirely rather than rendered bare.
    """
    overall = cells.get((run.id, feature.id, ALL_LANGUAGES))
    if not overall or ScoreMetric.PRESENCE_RATE not in overall:
        return []
    if ScoreMetric.F1 not in overall:
        return []

    languages = sorted(
        language
        for (run_id, stored_feature, language) in cells
        if run_id == run.id and stored_feature == feature.id
    )
    rates: dict[str, Cell] = {}
    for language in languages:
        cell = _cell(
            cells.get((run.id, feature.id, language)),
            ScoreMetric.PRESENCE_RATE,
            floor,
            mark=TieMark.NONE,
        )
        if cell is not None:
            rates[language] = cell
    return [
        PresenceRow(
            feature_key=feature.key,
            rates=rates,
            goal1=Goal1Companion(
                f1=overall[ScoreMetric.F1].value,
                precision=overall[ScoreMetric.PRECISION].value,
                recall=overall[ScoreMetric.RECALL].value,
            ),
        )
    ]


def _cross_tab(
    features: Sequence[Feature], run: Run, cells: _Cells, feature_key: str | None
) -> CrossTabView | None:
    """The Goal 1 × presence contingency table for one feature × model."""
    chosen = next(
        (f for f in features if feature_key is not None and f.key == feature_key),
        next((f for f in features if f.kind == Kind.LABELLED), None),
    )
    if chosen is None:
        return None
    stored = cells.get((run.id, chosen.id, ALL_LANGUAGES))
    if not stored or ScoreMetric.HIT_PRESENT not in stored:
        return None
    return CrossTabView(
        feature_key=chosen.key,
        model_id=run.id,
        hit_present=int(stored[ScoreMetric.HIT_PRESENT].value),
        hit_absent=int(stored[ScoreMetric.HIT_ABSENT].value),
        wrong_present=int(stored[ScoreMetric.WRONG_PRESENT].value),
        wrong_absent=int(stored[ScoreMetric.WRONG_ABSENT].value),
        missing_present=int(stored[ScoreMetric.MISSING_PRESENT].value),
        missing_absent=int(stored[ScoreMetric.MISSING_ABSENT].value),
    )


def _flag_inconsistency(
    runs: Sequence[Run], features: Sequence[Feature], cells: _Cells, floor: int
) -> tuple[FlagInconsistencyRow, ...]:
    """`present = false`, yet the extracted value matched — per model.

    The one Goal 2 number that is a quality signal rather than a description,
    because it is a self-contradiction rather than a comparison against a gold
    label nobody has (§11.2).
    """
    labelled = next((f for f in features if f.kind == Kind.LABELLED), None)
    if labelled is None:
        return ()
    rows = []
    for run in runs:
        cell = _cell(
            cells.get((run.id, labelled.id, ALL_LANGUAGES)),
            ScoreMetric.FLAG_INCONSISTENCY_RATE,
            floor,
            mark=TieMark.NONE,
        )
        if cell is not None:
            rows.append(FlagInconsistencyRow(model_id=run.id, cell=cell))
    return tuple(rows)


async def _records_not_written(
    session: AsyncSession, run: Run, feature: Feature
) -> list[PerRecordRow]:
    """The records behind the presence rate — "N records where weather is
    recorded but not written".

    A labelled case (the column is populated) that the model flagged
    `present = false`. The record's own value travels with it, because the
    point of the list is to act on the gap, and an analyst cannot act on a
    record id alone.

    `anonymised` rides on every row: mvp-spec.md §13 requires the per-record
    anonymisation marking **wherever text is shown**, and this list shows the
    record's value.
    """
    evaluation = await session.get(Evaluation, run.evaluation_id)
    assert evaluation is not None
    if not feature.source_column:
        # Only a native column can be "recorded but not written": a derived
        # value was never written anywhere to begin with.
        return []

    result = await session.execute(
        select(
            Record.id,
            Record.text_anonymised_flag,
            Record.language,
            Record.language_confidence,
            UnfallRow.value_raw,
        )
        .join(UnfallRow, UnfallRow.record_id == Record.id)
        .join(Extraction, Extraction.record_id == Record.id)
        .join(
            ExtractionValue,
            (ExtractionValue.extraction_id == Extraction.id)
            & (ExtractionValue.feature_id == feature.id),
        )
        .where(
            Record.corpus_id == evaluation.corpus_id,
            UnfallRow.column_name == feature.source_column,
            Extraction.run_id == run.id,
            ExtractionValue.present_flag.is_(False),
        )
        .order_by(Record.id)
    )
    finding = PRESENCE_FINDING.format(feature=feature.key)
    return [
        PerRecordRow(
            record_id=RecordId(record_id),
            anonymised=bool(anonymised),
            record_value=value or "",
            finding=finding,
            language=language,
            language_confidence=confidence,
        )
        for record_id, anonymised, language, confidence, value in result
        # An empty cell is not a labelled case, so it cannot be "recorded but
        # not written" either (§8.6).
        if value is not None and value.strip()
    ]
