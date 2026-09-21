# STUB — bodies owned by T1 (feat/p4-scoring-service). Not frozen.
"""The scoring pass (sw-design.md §16.1, §16.6).

A score is not computed when someone looks at it. It is computed once, by a
job, into `score` and `mismatch` rows, and everything the three Results tabs
render is a read over those rows.

**One `(run, feature)`, one commit.** Every `score` row for that pair — the
all-languages row and each per-language row, every metric — plus every
`mismatch` row that feature produced, are written together. Nothing batches
across features, and no transaction is held open across the EAV read that feeds
the next one. This is §15.3's rule one level up and it buys the same property:
**the features of a run with no `score` rows are the work left**, which is a
query rather than bookkeeping.

**No status column.** `status()` derives `ScoringStatus` by counting; see
`services/protocols.py`.

Implements `Scorer` (`services/protocols.py`) via `status()` — T2 and T3 are
handed this class as that protocol and never import it directly, the same seam
`PromptResolver` gave phase 3.

**M27 freezes the constructor and the signatures. T1 writes the bodies.**
"""

import logging
import time
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.extraction import RunStatus
from ra2.domain.feature import Kind, ValueType
from ra2.domain.ids import CorpusId, FeatureId, RecordId, RunId, TaskId
from ra2.domain.scoring import (
    ALL_LANGUAGES,
    ExploratoryCase,
    LabelledCase,
    Outcome,
    ScoreRow,
    aggregate_goal1,
    aggregate_goal2,
    aggregate_goal3,
    classify,
)
from ra2.infra.clock import Clock
from ra2.infra.idgen import IdFactory
from ra2.infra.tasks import ProgressReporter, TaskRunner
from ra2.persistence.models import (
    Evaluation,
    Extraction,
    ExtractionValue,
    Feature,
    Record,
    Run,
    UnfallRow,
)
from ra2.persistence.repositories.mismatch_repo import MismatchRepository, MismatchWrite
from ra2.persistence.repositories.score_repo import ScoreRepository
from ra2.services.errors import NotFoundError, RunNotScoreableError
from ra2.services.feature_service import matching_rule_from_json
from ra2.services.protocols import GroundTruthProvider, ScoringStatus

__all__ = ["ScoringService"]

_log = logging.getLogger(__name__)


class ScoringService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        ground_truth: GroundTruthProvider,
        task_runner: TaskRunner,
        clock: Clock,
        id_factory: IdFactory,
    ) -> None:
        self._session_factory = session_factory
        self._ground_truth = ground_truth
        self._task_runner = task_runner
        self._clock = clock
        self._id_factory = id_factory
        #: Which runs have a pass in flight **right now**, and how many.
        #:
        #: `ScoringStatus.running` was the literal `False` for four phases, so
        #: §16.7's "scoring…" state was unreachable by construction and the
        #: Results view could not tell a pass that was still going from one
        #: that had crashed — both rendered "Not scored yet". The counts come
        #: from committed rows, as F5 requires, and they always will; *this*
        #: is not a count of anything, it is the one fact no row can carry:
        #: whether this process is working on it at this instant.
        #:
        #: A `Counter` rather than a `set` because the guard nests — `submit`
        #: marks the run before the task is scheduled, and the pass it
        #: schedules marks it again — and a set would have the inner exit
        #: clear a flag the outer scope still owns.
        self._in_flight: Counter[RunId] = Counter()

    async def score_run(self, run_id: RunId) -> None:
        """Score one finished run, feature by feature, committing each.

        **Chained off the run worker's terminal `done`**, not triggered by a
        button (`SD17`): every input a score depends on is immutable from the
        launch commit onward, so there is no moment in between where a user
        could make a meaningful decision, and the design draws no such control.

        A `failed` or `interrupted` run raises `RunNotScoreableError` and is
        never scored — a partial corpus produces real-looking numbers over an
        unstated denominator.

        **Resume is implicit.** Re-entering after an interruption scores only
        the features with no rows, because that is what "the work left" means
        here. No separate `resume` entry point exists, and that is deliberate:
        one that skipped the same query would be a second answer to "how far
        did it get".
        """
        await self._score(run_id, rescore=False, reporter=None)

    def submit(self, run_id: RunId) -> TaskId:
        """Chain scoring off a finished run, on the phase-1 `TaskRunner` seam.

        Returns the task id the UI polls through `GET /api/v1/tasks/{id}`,
        exactly as import and runs do (§9). There is no Score button, so this
        is called by the run worker's terminal `done` rather than by a view.

        **The run is marked in flight here, synchronously**, not inside the
        scheduled coroutine: `submit` returns before the event loop gets
        anywhere near `work`, and a Results page that polls in that gap would
        otherwise be told "not scored yet" about a run whose pass is already
        queued — the exact sentence this fix exists to stop being ambiguous.
        """
        self._enter(run_id)

        async def work(reporter: ProgressReporter) -> None:
            try:
                await self._score(run_id, rescore=False, reporter=reporter)
            finally:
                self._exit(run_id)

        try:
            return self._task_runner.submit(f"score:{run_id}", work)
        except BaseException:
            # The work will never run, so nothing will ever clear the mark.
            self._exit(run_id)
            raise

    async def submit_rescore(self, run_id: RunId) -> TaskId:
        """`rescore_run`, scheduled rather than awaited.

        The same pass `rescore_run` runs and the same tag preservation
        (`SD21`); the difference is who waits. `POST /runs/{id}/rescore`
        answers `202 Accepted` with a task id, and a route that held the
        request open for the whole pass was describing something other than
        what it did — it also returned the *run's* id in the `task_id` field,
        which is not a task id and cannot be polled. The UI's Re-score control
        needs this for the same reason import and runs need it: one seam,
        polled one way (§9).

        **`async`, unlike `submit`.** A refusal — no such run, or a run that
        is not `done` — has to reach the caller as a 404 or a 409, and an
        exception raised inside a scheduled task reaches nobody but the task
        table. So the guard is read here, before anything is submitted, and
        `_score` reads it again inside its own transaction: this one decides
        the HTTP status, that one decides whether to write, and a run that
        changed status in between is refused by the one that matters.

        :raises NotFoundError: no such run.
        :raises RunNotScoreableError: the run is not `done`.
        """
        await self._require_scoreable(run_id)
        self._enter(run_id)

        async def work(reporter: ProgressReporter) -> None:
            try:
                await self._score(run_id, rescore=True, reporter=reporter)
            finally:
                self._exit(run_id)

        try:
            return self._task_runner.submit(f"rescore:{run_id}", work)
        except BaseException:
            self._exit(run_id)
            raise

    async def rescore_run(self, run_id: RunId) -> None:
        """Re-score every feature of a run, **preserving analyst tags**.

        The explicit path, and the only reason it exists is that the *scorer's
        own code* can change; no other input can. Per feature it replaces the
        `score` rows — they are a pure function of immutable inputs, so a
        re-score either reproduces them byte-for-byte or the code changed, and
        replacement is correct either way — and **upserts** the `mismatch` rows
        on `(run_id, record_id, feature_id)`, rewriting the derived columns and
        leaving `analyst_tag`, `tagged_at` and `note` alone.

        `DELETE`-then-`INSERT` is the obvious implementation and it destroys
        review work silently, at the moment a developer is most confident
        (§16.6, SD21, R5).
        """
        await self._score(run_id, rescore=True, reporter=None)

    async def status(self, session: AsyncSession, run_id: RunId) -> ScoringStatus:
        """`Scorer`. Derived from committed rows, never from a column —
        **except `running`**, which no row can answer (`_in_flight`)."""
        run = await session.get(Run, run_id)
        if run is None:
            raise NotFoundError("run", run_id)
        evaluation = await session.get(Evaluation, run.evaluation_id)
        if evaluation is None:
            raise NotFoundError("evaluation", run.evaluation_id)
        features = await self._features_for(session, run)
        scored = await ScoreRepository(session).scored_feature_ids(run_id)
        return ScoringStatus(
            run_id=run_id,
            scored_features=len(scored),
            labelled_features=await _scoreable_count(
                session, CorpusId(evaluation.corpus_id), features
            ),
            running=self._in_flight[run_id] > 0,
        )

    # -- in flight ---------------------------------------------------------

    def _enter(self, run_id: RunId) -> None:
        self._in_flight[run_id] += 1

    def _exit(self, run_id: RunId) -> None:
        """Symmetric with `_enter`, and it **removes** the key at zero.

        A `Counter` left holding zeros is a dictionary that grows by one entry
        per run for the life of the process. `status()` reads `[run_id]`,
        which a `Counter` answers with `0` for an absent key, so nothing
        downstream can tell the difference.
        """
        remaining = self._in_flight[run_id] - 1
        if remaining > 0:
            self._in_flight[run_id] = remaining
        else:
            del self._in_flight[run_id]

    @contextmanager
    def _in_flight_for(self, run_id: RunId) -> Iterator[None]:
        self._enter(run_id)
        try:
            yield
        finally:
            self._exit(run_id)

    async def _require_scoreable(self, run_id: RunId) -> None:
        """`submit_rescore`'s pre-flight — the refusal the route reports."""
        async with self._session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise NotFoundError("run", run_id)
            status = RunStatus(run.status)
            if status is not RunStatus.DONE:
                raise RunNotScoreableError(run_id, f"run status is {status.value}")

    # -- the pass ----------------------------------------------------------

    async def _score(
        self, run_id: RunId, *, rescore: bool, reporter: ProgressReporter | None
    ) -> None:
        """The pass itself. **One `(run, feature)`, one commit** (§16.1).

        Nothing batches across features, and no transaction is held open
        across the EAV read that feeds the next one — so an interruption
        leaves whole features done and whole features absent, never a feature
        half-scored from two different reads of the corpus.

        **It says what it did.** Before this, a pass logged nothing at all:
        not a start, not a finish, not a failure. `AsyncioTaskRunner` records
        a crash in an in-memory table and logs nothing either, so a run whose
        scoring raised and a run whose scoring succeeded produced byte-identical
        output — one line from the run worker announcing the submission, and
        then silence. Ids, counts and durations only; `infra/logging.py` owns
        that rule and `data-handling.md` §5 is why.
        """
        started_ms = time.monotonic()
        async with self._session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise NotFoundError("run", run_id)
            status = RunStatus(run.status)
            if status is not RunStatus.DONE:
                # A partial corpus produces real-looking numbers over an
                # unstated denominator — the failure §11.4's floor guards
                # against at the other end of the scale.
                raise RunNotScoreableError(run_id, f"run status is {status.value}")
            evaluation = await session.get(Evaluation, run.evaluation_id)
            if evaluation is None:
                raise NotFoundError("evaluation", run.evaluation_id)
            corpus_id = CorpusId(evaluation.corpus_id)
            features = await self._features_for(session, run)
            if not any(_is_labelled(feature) for feature in features):
                raise RunNotScoreableError(run_id, "the evaluation has no labelled features")

            already = (
                frozenset()
                if rescore
                else await ScoreRepository(session).scored_feature_ids(run_id)
            )
            languages = await _languages(session, corpus_id)

        pending = [f for f in features if FeatureId(f.id) not in already]
        _log.info(
            "run %s: scoring %d feature(s)%s",
            run_id,
            len(pending),
            " (re-score)" if rescore else "",
        )
        with self._in_flight_for(run_id):
            for index, feature in enumerate(pending):
                # A fresh session per feature: the transaction boundary is the
                # point, and holding one open across the EAV read would make an
                # interrupted pass ambiguous about what it had committed.
                try:
                    async with self._session_factory() as session:
                        await self._score_one_feature(
                            session, run_id, corpus_id, feature, languages
                        )
                        await session.commit()
                except Exception as exc:
                    # The count is the part that matters: it says how much of
                    # the pass committed, and therefore what a re-entry has
                    # left to do. The exception itself is re-raised for the
                    # task table to record — `exc_info` is deliberately not
                    # passed, because a SQLAlchemy traceback carries bound
                    # parameters and a bound parameter here is a narrative
                    # (Do-NOT #13).
                    _log.warning(
                        "run %s: scoring failed after %d of %d feature(s) (%s)",
                        run_id,
                        index,
                        len(pending),
                        type(exc).__name__,
                    )
                    raise
                if reporter is not None:
                    reporter.report(index + 1, len(pending), f"scored {feature.key}")
        _log.info(
            "run %s: scored %d feature(s) in %d ms",
            run_id,
            len(pending),
            round((time.monotonic() - started_ms) * 1000),
        )

    async def _score_one_feature(
        self,
        session: AsyncSession,
        run_id: RunId,
        corpus_id: CorpusId,
        feature: Feature,
        languages: Mapping[RecordId, str],
    ) -> None:
        feature_id = FeatureId(feature.id)
        answers = await _model_answers(session, run_id, feature_id)

        if not _is_labelled(feature):
            # Goal 3: no ground truth, so no outcomes — a discovery rate and a
            # span count, and nothing that admits a second model (§11.3).
            discoveries = [
                ExploratoryCase(
                    record_id=record_id,
                    language=languages.get(record_id, ALL_LANGUAGES),
                    reported=value is not None,
                    evidence_span=span,
                )
                for record_id, (value, _flag, span) in answers.items()
            ]
            if not discoveries:
                return
            rows = _per_language(discoveries, aggregate_goal3)
            await ScoreRepository(session).write_feature(run_id, feature_id, rows)
            return

        truth = await self._ground_truth.values_for(session, corpus_id, feature_id)
        value_type = ValueType(feature.value_type) if feature.value_type else ValueType.FREE_TEXT
        rule = matching_rule_from_json(feature.matching_rule)

        cases: list[LabelledCase] = []
        mismatches: list[MismatchWrite] = []
        for record_id, record_value in truth.items():
            model_value, present_flag, span = answers.get(record_id, (None, None, None))
            outcome = classify(record_value, model_value, value_type=value_type, rule=rule)
            if outcome is None:
                # Not a labelled case. §8.6: the record leaves this feature's
                # denominator entirely — it is not a `MISSING`, not a zero,
                # and not a suppressed cell.
                continue
            assert record_value is not None
            cases.append(
                LabelledCase(
                    record_id=record_id,
                    language=languages.get(record_id, ALL_LANGUAGES),
                    outcome=outcome,
                    record_value=record_value,
                    model_value=model_value,
                    present_flag=present_flag,
                )
            )
            if outcome is Outcome.WRONG:
                mismatches.append(
                    MismatchWrite(
                        record_id=record_id,
                        record_value=record_value,
                        extracted_value=model_value,
                        evidence_span=span,
                    )
                )

        if not cases:
            # **§8.6 at the service layer.** A feature with no labelled cases
            # produces NO rows — not rows of zeros, and not a suppressed cell.
            # Suppression is about *too few* labelled cases; this feature has
            # none at all, and a stored `n = 0` would render as a measurement
            # (§16.2). It also leaves the feature out of `scored_feature_ids`,
            # which is correct: there was never anything to score.
            return

        rows = [
            *_per_language(cases, aggregate_goal1),
            *_per_language(cases, aggregate_goal2),
        ]
        await ScoreRepository(session).write_feature(run_id, feature_id, rows)
        # The feature's scores and its mismatches go in together — one
        # `(run, feature)`, one commit.
        await MismatchRepository(session).upsert_feature(
            run_id, feature_id, mismatches, new_id=self._id_factory.new_id
        )

    async def _features_for(self, session: AsyncSession, run: Run) -> Sequence[Feature]:
        result = await session.execute(
            select(Feature)
            .join(Evaluation, Evaluation.feature_config_id == Feature.feature_config_id)
            .where(Evaluation.id == run.evaluation_id)
            .order_by(Feature.ordinal)
        )
        return list(result.scalars())


def _is_labelled(feature: Feature) -> bool:
    """`kind` is stored as a plain `String(16)` (M0-D7), so a reloaded row
    holds the string and an `is` comparison against the enum is always false —
    the trap S4 hit in `ground_truth_repo`."""
    return feature.kind == Kind.LABELLED


class _HasLanguage(Protocol):
    """A read-only property, not a mutable attribute: `LabelledCase` and
    `ExploratoryCase` are frozen slotted dataclasses, and a `language: str`
    declaration would ask them for a settable one they do not have."""

    @property
    def language(self) -> str: ...


class _Aggregator[C](Protocol):
    def __call__(self, cases: Sequence[C], *, language: str) -> tuple[ScoreRow, ...]: ...


def _per_language[C: _HasLanguage](cases: Sequence[C], aggregate: _Aggregator[C]) -> list[ScoreRow]:
    """The all-languages row **and** one row set per language, from a single
    pass over the same cases (mvp-spec.md §11.1: "per (run, feature) and per
    (run, feature, language)").

    Built from one list rather than two queries, so the all-languages `n`
    cannot disagree with the sum of the per-language `n`s — a difference
    nobody would ever see on the screen.

    A language with no cases produces no rows at all, rather than a row of
    zeros: "Mixed / undetermined 15" in the design is a small `n`, and a
    language nobody wrote in is not a measurement of anything.
    """
    rows: list[ScoreRow] = list(aggregate(cases, language=ALL_LANGUAGES))
    for language in sorted({case.language for case in cases}):
        subset = [case for case in cases if case.language == language]
        rows.extend(aggregate(subset, language=language))
    return rows


async def _scoreable_count(
    session: AsyncSession, corpus_id: CorpusId, features: Sequence[Feature]
) -> int:
    """How many labelled features **could** produce rows for this corpus.

    Not simply "how many labelled features there are", and the difference is
    not cosmetic: a feature whose source column is populated for nobody
    produces no `score` rows at all (§8.6, §16.2), so counting it would leave
    a fully-scored run reporting 4 of 5 — and `is_scored` false forever, with
    the UI parked in "scoring..." on a pass that finished.

    Derived features always count: a derivation has a value for every record,
    even when that value is `"0"`.

    One grouped query for the whole corpus rather than an `EXISTS` per
    feature, because this is polled on a timer (§9).
    """
    native = {f.source_column for f in features if _is_labelled(f) and f.source_column}
    derived = sum(1 for f in features if _is_labelled(f) and not f.source_column)
    if not native:
        return derived
    populated = await session.execute(
        select(UnfallRow.column_name)
        .join(Record, Record.id == UnfallRow.record_id)
        .where(Record.corpus_id == corpus_id, UnfallRow.column_name.in_(native))
        .distinct()
    )
    return derived + len(set(populated.scalars()))


async def _languages(session: AsyncSession, corpus_id: CorpusId) -> Mapping[RecordId, str]:
    """One query. The language breakdown is per record, and reading it per
    feature would repeat the whole corpus scan for every feature."""
    result = await session.execute(
        select(Record.id, Record.language).where(Record.corpus_id == corpus_id)
    )
    return {RecordId(record_id): language for record_id, language in result}


async def _model_answers(
    session: AsyncSession, run_id: RunId, feature_id: FeatureId
) -> Mapping[RecordId, tuple[str | None, bool | None, str | None]]:
    """`record -> (normalised value, present flag, evidence span)` for one
    feature of one run. One query for the whole corpus."""
    result = await session.execute(
        select(
            Extraction.record_id,
            ExtractionValue.value_normalised,
            ExtractionValue.present_flag,
            ExtractionValue.evidence_span,
        )
        .join(ExtractionValue, ExtractionValue.extraction_id == Extraction.id)
        .where(Extraction.run_id == run_id, ExtractionValue.feature_id == feature_id)
    )
    return {RecordId(record_id): (value, flag, span) for record_id, value, flag, span in result}
