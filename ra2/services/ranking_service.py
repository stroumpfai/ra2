# STUB — bodies owned by T3 (feat/p4-ranking-service). Not frozen.
"""Tab 3 (sw-design.md §16.5).

**Every number here is derived from tab 1's scored rows.** This service reads
the same `score` rows `ResultsService` reads and hands them to
`domain/ranking.py`; nothing is stored, nothing is cached independently, and if
this and the extraction tab disagree then this one is wrong by construction.
J13 asserts exactly that, in the browser.

Three columns are **reported, never scored** — median latency, prompt tokens
and VRAM — per the design's own rule 4, "the tie-breaker you apply, not one the
tool applies". **The presence rate joins them** (`SD20`): mvp-spec.md §11.2 is
unambiguous that presence has no independent gold label, and a model that flags
everything present maximises it. A test asserts the negative — change the
presence rate and the ranking must not move.

**M27 freezes the constructor and the signature. T3 writes the body.**
"""

import statistics
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import EvaluationId, FeatureId, RunId
from ra2.domain.ranking import FeatureCell, rank_models, separating_features
from ra2.domain.scoring import ALL_LANGUAGES, ScoreMetric
from ra2.domain.stats import Interval, TiedCell, TieMark, mark_ties, suppressed
from ra2.persistence.models import Evaluation, Extraction, Feature, Run, Score
from ra2.persistence.repositories.score_repo import ScoreRepository
from ra2.services.errors import NotFoundError
from ra2.services.protocols import Scorer
from ra2.services.readmodels import (
    RankingRow,
    RankingTabView,
    RunDescriptorView,
    SeparatingRow,
)

__all__ = ["RankingService"]

#: The verdict copy, composed from the computed ranks and never authored.
TIE_HEADLINE = "Two models are tied at the top. This run does not separate them."
CLEAR_HEADLINE = "{tag} leads on this run."
NO_SEPARATION_DETAIL = (
    "{first} and {second} tie on {tied} of the {scored} scored features and their macro "
    "intervals cross. Pick on cost, not on score \u2014 or run more records to break the tie."
)


class RankingService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        scorer: Scorer,
    ) -> None:
        self._session_factory = session_factory
        self._scorer = scorer

    async def ranking_tab(self, evaluation_id: EvaluationId) -> RankingTabView:
        """The ranking table, the separating features and the verdict.

        Raises nothing when the models tie everywhere: an empty `separating` is
        a **result** — "this run does not separate them" — and the verdict is
        composed from the computed ranks rather than authored.

        Renders the "nothing scoreable" state rather than a blank table when
        every feature is suppressed: `domain.ranking.rank_models` raises there,
        because there is no macro of nothing and a `0.0` prints as a model that
        scored zero (§16.4).
        """
        async with self._session_factory() as session:
            evaluation = await session.get(Evaluation, evaluation_id)
            if evaluation is None:
                raise NotFoundError("evaluation", evaluation_id)
            runs = list(
                (
                    await session.execute(
                        select(Run).where(Run.evaluation_id == evaluation_id).order_by(Run.id)
                    )
                ).scalars()
            )
            features = list(
                (
                    await session.execute(
                        select(Feature)
                        .join(
                            Evaluation,
                            Evaluation.feature_config_id == Feature.feature_config_id,
                        )
                        .where(Evaluation.id == evaluation_id)
                        .order_by(Feature.ordinal)
                    )
                ).scalars()
            )
            floor = evaluation.min_cell_count

            # **Read from the same `score` rows tab 1 reads.** Nothing here is
            # stored and nothing is cached: if this and the extraction tab
            # disagree, this one is wrong by construction (§16.5), and J13
            # asserts exactly that in the browser.
            stored: dict[tuple[str, str], Score] = {}
            for run in runs:
                for row in await ScoreRepository(session).for_run(RunId(run.id)):
                    if row.language == ALL_LANGUAGES and ScoreMetric(row.metric) is ScoreMetric.F1:
                        stored[(row.run_id, row.feature_id)] = row

            cells_by_model = _cells_by_model(runs, features, stored, floor)
            if not any(
                any(not cell.suppressed for cell in cells) for cells in cells_by_model.values()
            ):
                return _nothing_scoreable(evaluation, runs, features)

            rankings = rank_models(cells_by_model)
            separating = separating_features(cells_by_model)
            reported = await _reported_metrics(session, runs)

            by_model = {r.model_id: r for r in rankings}
            ordered = sorted(runs, key=lambda run: (by_model[run.id].rank, run.id))
            rows = tuple(
                RankingRow(
                    model_id=run.id,
                    tag=run.model_name,
                    digest=run.model_digest,
                    rank=by_model[run.id].rank,
                    macro_f1=by_model[run.id].macro_f1,
                    ci_low=by_model[run.id].interval.low,
                    ci_high=by_model[run.id].interval.high,
                    best=by_model[run.id].best,
                    tied=by_model[run.id].tied,
                    worse=by_model[run.id].worse,
                    verdict=_verdict(by_model[run.id]),
                    # Reported, never scored (SD20). None of the four below
                    # takes any part in `rank`.
                    presence_rate=reported[run.id]["presence"],
                    median_latency_ms=int(reported[run.id]["latency"]),
                    prompt_tokens=int(reported[run.id]["tokens"]),
                    vram_bytes=0,
                )
                for run in ordered
                if run.id in by_model
            )

            names = {f.id: f for f in features}
            scored_count = max(
                (sum(1 for c in cells if not c.suppressed) for cells in cells_by_model.values()),
                default=0,
            )
            headline, detail = _compose_verdict(rows, separating, scored_count)
            return RankingTabView(
                descriptor=_ranking_descriptor(evaluation, runs),
                rows=rows,
                separating=tuple(
                    SeparatingRow(
                        feature_id=row.feature_id,
                        name=names[row.feature_id].key,
                        source_label=names[row.feature_id].source_column or "derived",
                        n=stored[(rows[0].model_id, row.feature_id)].n
                        if (rows[0].model_id, row.feature_id) in stored
                        else 0,
                        f1_by_model=row.f1_by_model,
                        delta=row.delta,
                        reading=_reading(row, names[row.feature_id].key, rows),
                    )
                    for row in separating
                    if row.feature_id in names
                ),
                verdict_headline=headline,
                verdict_detail=detail,
                scored_feature_count=scored_count,
                unscored_feature_count=len(features) - scored_count,
            )


def _cells_by_model(
    runs: Sequence[Run],
    features: Sequence[Feature],
    stored: dict[tuple[str, str], Score],
    floor: int,
) -> dict[str, list[FeatureCell]]:
    """Tab 1's cells, rebuilt from the same rows — including their tie marks.

    The marks are recomputed here rather than passed in, because `best/tied/
    worse` must count **the same marks the extraction tab renders**. Computing
    them from the same function over the same rows is what makes that true
    without a shared cache the two could drift apart on.
    """
    cells: dict[str, list[FeatureCell]] = {run.id: [] for run in runs}
    for feature in features:
        per_run = {
            run.id: stored[(run.id, feature.id)] for run in runs if (run.id, feature.id) in stored
        }
        if not per_run:
            continue
        comparable = [
            (run_id, score) for run_id, score in per_run.items() if not suppressed(score.n, floor)
        ]
        marks: dict[str, TieMark] = {}
        if comparable:
            computed = mark_ties(
                [TiedCell(point=score.value, interval=_interval(score)) for _, score in comparable]
            )
            marks = {run_id: mark for (run_id, _), mark in zip(comparable, computed, strict=True)}
        for run_id, score in per_run.items():
            cells[run_id].append(
                FeatureCell(
                    feature_id=FeatureId(feature.id),
                    f1=score.value,
                    interval=_interval(score),
                    suppressed=suppressed(score.n, floor),
                    mark=marks.get(run_id, TieMark.NONE),
                )
            )
    return {model_id: rows for model_id, rows in cells.items() if rows}


def _interval(score: Score) -> Interval:
    return Interval(
        low=score.ci_low if score.ci_low is not None else score.value,
        high=score.ci_high if score.ci_high is not None else score.value,
        n=score.n,
    )


async def _reported_metrics(
    session: AsyncSession, runs: Sequence[Run]
) -> dict[str, dict[str, float]]:
    """Median latency, prompt tokens and the macro presence rate.

    **Reported, never scored** — the design's own rule 4, "the tie-breaker you
    apply, not one the tool applies". The presence rate joins them (SD20):
    §11.2 is unambiguous that presence has no independent gold label, and a
    model that flags everything present maximises it.
    """
    reported: dict[str, dict[str, float]] = {}
    for run in runs:
        # `latency_ms` is nullable: a parse failure records the attempt
        # without a timing. Those rows are excluded rather than counted as 0,
        # which would drag a median toward a number nothing measured.
        latencies = [
            value
            for value in (
                await session.execute(
                    select(Extraction.latency_ms).where(Extraction.run_id == run.id)
                )
            ).scalars()
            if value is not None
        ]
        tokens = list(
            (
                await session.execute(
                    select(Extraction.prompt_tokens).where(Extraction.run_id == run.id)
                )
            ).scalars()
        )
        presence = list(
            (
                await session.execute(
                    select(Score.value).where(
                        Score.run_id == run.id,
                        Score.language == ALL_LANGUAGES,
                        Score.metric == ScoreMetric.PRESENCE_RATE,
                    )
                )
            ).scalars()
        )
        reported[run.id] = {
            "latency": float(statistics.median(latencies)) if latencies else 0.0,
            "tokens": float(sum(t for t in tokens if t is not None)),
            # A macro over the features, equal weight, like every other macro
            # here — and still not a score.
            "presence": statistics.fmean(presence) if presence else 0.0,
        }
    return reported


def _verdict(ranking: object) -> str:
    """The design's `.pill` vocabulary, from the computed marks."""
    rank = ranking.rank  # type: ignore[attr-defined]
    worse = ranking.worse  # type: ignore[attr-defined]
    if rank == 1:
        return "tied for best"
    return f"behind on {worse}"


def _compose_verdict(
    rows: Sequence[RankingRow], separating: Sequence[object], scored: int
) -> tuple[str, str]:
    """Composed from the computed ranks, **never authored**."""
    leaders = [row for row in rows if row.rank == 1]
    if len(leaders) < 2:
        tag = leaders[0].tag if leaders else ""
        return CLEAR_HEADLINE.format(tag=tag), ""
    first, second = leaders[0], leaders[1]
    return (
        TIE_HEADLINE,
        NO_SEPARATION_DETAIL.format(
            first=first.tag,
            second=second.tag,
            tied=scored - len(separating),
            scored=scored,
        ),
    )


def _reading(row: object, name: str, rows: Sequence[RankingRow]) -> str:
    """The plain sentence beside each separating feature."""
    leader = next(
        (r.tag for r in rows if r.model_id == row.leader_model_id),  # type: ignore[attr-defined]
        row.leader_model_id,  # type: ignore[attr-defined]
    )
    return f"{leader} leads alone on {name}"


def _ranking_descriptor(evaluation: Evaluation, runs: Sequence[Run]) -> RunDescriptorView:
    return RunDescriptorView(
        evaluation_id=EvaluationId(evaluation.id),
        corpus_label=evaluation.corpus_id,
        record_count=0,
        model_count=len(runs),
        config_fingerprint=evaluation.feature_config_id,
        is_dev=evaluation.is_dev,
        min_cell_count=evaluation.min_cell_count,
    )


def _nothing_scoreable(
    evaluation: Evaluation, runs: Sequence[Run], features: Sequence[Feature]
) -> RankingTabView:
    """A well-formed "nothing scoreable" payload, never an empty list.

    An empty list is what a UI renders as a blank table, and "no results" is a
    different fact from "not enough data for results" (§16.7).
    """
    return RankingTabView(
        descriptor=_ranking_descriptor(evaluation, runs),
        rows=(),
        separating=(),
        verdict_headline="Nothing in this run could be scored.",
        verdict_detail=(
            "Every labelled feature is below the minimum cell count of "
            f"{evaluation.min_cell_count}, so no model can be ranked against another."
        ),
        scored_feature_count=0,
        unscored_feature_count=len(features),
    )
