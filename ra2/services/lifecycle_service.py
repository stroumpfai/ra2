# NEW — reset and discard (sw-design.md §18). Not frozen.
"""The one destructive verb in an append-only pipeline (sw-design.md §18).

Everything else in this layer appends. This service removes — a whole `run`, a
whole `evaluation` or a whole `delivery`, never part of one (§18.1) — and the
whole of it exists to bound that so the invariant survives contact with an
analyst who has three inconclusive evaluations cluttering a screen.

**Why a service and not three repository calls.** The guards are policy, not
persistence: G1 reads a status, G2 counts rows in a different table, and the
delivery guard asks a question about corpora. One place answers all three, and
both adapters get the same answer.

**The cascade is the schema's, not this file's.** `extraction`,
`extraction_value`, `extraction_entity`, `score` and `mismatch` are
`ondelete="CASCADE"` from `run`; `run` and `evaluation_feature` from
`evaluation`; `delivery_file` from `delivery`. Nothing here deletes a child
row by hand — a hand-written cascade is how one table gets forgotten. What
`foreign_keys=ON` (§4.4) already guarantees, the backend test that counts the
rows that went with a run keeps honest.

**Nothing here records that a discard happened** (§18.3). No `deleted_at`, no
tombstone, no "was this exported" flag. The trace is a CSV the analyst chose
to keep, which is what `run_export` is for.
"""

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import SourceKind
from ra2.domain.extraction import RunStatus
from ra2.domain.ids import DeliveryId, EvaluationId, FeatureId, RecordId, RunId
from ra2.infra.config import Settings
from ra2.infra.filestore import FileStore, FileStoreError
from ra2.persistence.models import Evaluation, Feature, Run
from ra2.persistence.repositories.delivery_repo import DeliveryRepository
from ra2.persistence.repositories.evaluation_repo import EvaluationRepository
from ra2.persistence.repositories.mismatch_repo import MismatchRepository
from ra2.persistence.repositories.run_repo import RunRepository
from ra2.persistence.repositories.score_repo import ScoreRepository
from ra2.persistence.session import session_scope
from ra2.services.errors import (
    DeliveryCitedError,
    NotFoundError,
    RunActiveError,
    TaggedWorkPresentError,
)
from ra2.services.readmodels import (
    DataDirView,
    DiscardPreviewView,
    MismatchExportRow,
    RunExportView,
    ScoreExportRow,
)

__all__ = ["LifecycleService"]

#: The three `kind` values a `DiscardPreviewView` carries. Plain strings on
#: purpose (readmodels.py): the routers and the dialog both key on them, and
#: neither owns an enum the other would have to import.
RUN_KIND = "run"
EVALUATION_KIND = "evaluation"
DELIVERY_KIND = "delivery"

#: G1's two statuses. `done`, `failed` and `interrupted` are all discardable —
#: an interrupted run is exactly the debris this verb exists to clear.
ACTIVE_STATUSES = frozenset({RunStatus.QUEUED, RunStatus.RUNNING})


def _file_identity(path: Path) -> tuple[int, int] | None:
    """`(st_dev, st_ino)` — what makes two paths the same *file*.

    A path comparison cannot see this: `just reset-seed` writes the new
    database at exactly the path the old one had. The inode is what changed,
    and it is populated on Windows as well as POSIX, so this needs no branch
    (N3). `None` when the file is not there — during a reset it genuinely is
    not, and "absent" is a third answer, not a replacement.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_dev, stat.st_ino)


class LifecycleService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        upload_store: FileStore,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._upload_store = upload_store
        self._settings = settings
        #: The identity of the database file this process started against —
        #: `(st_dev, st_ino)`, or `None` when there was no file yet.
        #:
        #: Stamped in the constructor rather than at the first read, because
        #: "the file this process opened" is a fact about startup and a lazy
        #: stamp would adopt whatever file happened to be there when the
        #: first page loaded — including one that had already replaced the
        #: original.
        self._database_identity = _file_identity(self._settings.database_path)

    # --- previews ----------------------------------------------------------

    async def run_preview(self, run_id: RunId) -> DiscardPreviewView:
        """What discarding this run would destroy. Counts only; writes
        nothing.

        :raises NotFoundError: no such run.
        """
        async with self._session_factory() as session:
            run = await self._require_run(session, run_id)
            return await self._run_preview(session, run)

    async def evaluation_preview(self, evaluation_id: EvaluationId) -> DiscardPreviewView:
        """The same counts summed over the evaluation's runs.

        An evaluation with no runs previews as all zeros and is discardable —
        a draft nobody launched is the easiest case, not a special one.

        :raises NotFoundError: no such evaluation.
        """
        async with self._session_factory() as session:
            evaluation = await self._require_evaluation(session, evaluation_id)
            runs = await RunRepository(session).list_by_evaluation(evaluation_id)
            previews = [await self._run_preview(session, run) for run in runs]
            active = next((p for p in previews if p.active), None)
            return DiscardPreviewView(
                kind=EVALUATION_KIND,
                target_id=str(evaluation_id),
                label=f"{evaluation.name} · {len(runs)} run(s)",
                runs=len(runs),
                extractions=sum(p.extractions for p in previews),
                scores=sum(p.scores for p in previews),
                mismatches=sum(p.mismatches for p in previews),
                tagged_mismatches=sum(p.tagged_mismatches for p in previews),
                files=0,
                active=active is not None,
                active_detail=None if active is None else active.active_detail,
            )

    async def delivery_preview(self, delivery_id: DeliveryId) -> DiscardPreviewView:
        """What discarding this delivery would remove, and whether it may be.

        `cited_by` is the refusal: a corpus was frozen from these files, and
        `corpus.delivery_id` being `SET NULL` means the database would null the
        provenance link rather than refuse (§18.2).

        :raises NotFoundError: no such delivery.
        """
        async with self._session_factory() as session:
            repo = DeliveryRepository(session)
            delivery = await repo.get(delivery_id)
            if delivery is None:
                raise NotFoundError(DELIVERY_KIND, delivery_id)
            cited_by = await repo.count_citing_corpora(delivery_id)
            return DiscardPreviewView(
                kind=DELIVERY_KIND,
                target_id=str(delivery_id),
                label=delivery.name,
                runs=0,
                extractions=0,
                scores=0,
                mismatches=0,
                tagged_mismatches=0,
                files=len(delivery.files),
                active=False,
                cited_by=cited_by,
            )

    # --- discard -----------------------------------------------------------

    async def discard_run(self, run_id: RunId, *, force: bool = False) -> None:
        """Discard one run and everything derived from it.

        :param force: proceed although tagged mismatches would be destroyed
            (G2). It overrides **only** that guard — G1 has no override, because
            deleting the row a worker is writing to is not a decision a user
            gets to take.
        :raises NotFoundError: no such run.
        :raises RunActiveError: the run is `queued` or `running` (G1).
        :raises TaggedWorkPresentError: tagged mismatches, and no `force` (G2).
        """
        async with session_scope(self._session_factory) as session:
            run = await self._require_run(session, run_id)
            repo = RunRepository(session)
            self._require_inactive(run)
            _, tagged = await repo.count_mismatches(run_id)
            self._require_no_tagged_work(RUN_KIND, str(run_id), tagged, force=force)
            await repo.delete(run)

    async def discard_evaluation(self, evaluation_id: EvaluationId, *, force: bool = False) -> None:
        """Discard an evaluation and its runs.

        The corpus, the feature config and the prompt versions it cites are
        `RESTRICT` and are untouched: discarding an evaluation is not a way to
        delete a corpus (§18.1).

        :raises NotFoundError: no such evaluation.
        :raises RunActiveError: **any** of its runs is active (G1).
        :raises TaggedWorkPresentError: tagged mismatches across its runs (G2).
        """
        async with session_scope(self._session_factory) as session:
            evaluation = await self._require_evaluation(session, evaluation_id)
            run_repo = RunRepository(session)
            runs = await run_repo.list_by_evaluation(evaluation_id)
            for run in runs:
                self._require_inactive(run)
            tagged = 0
            for run in runs:
                _, run_tagged = await run_repo.count_mismatches(RunId(run.id))
                tagged += run_tagged
            self._require_no_tagged_work(EVALUATION_KIND, str(evaluation_id), tagged, force=force)
            await EvaluationRepository(session).delete(evaluation)

    async def discard_delivery(self, delivery_id: DeliveryId) -> None:
        """Discard a delivery, its file rows and — for an upload — its bytes.

        **A host-path delivery's files are the analyst's own and are never
        touched**: `HostPathFileStore` registers them in place and refuses to
        remove them, which is the behaviour this method relies on rather than
        works around. Only the rows go.

        There is no `force` here and no tagged-work question: a delivery
        carries no analyst-authored data. The one refusal is a corpus frozen
        from it.

        :raises NotFoundError: no such delivery.
        :raises DeliveryCitedError: a corpus cites it (§18.2).
        """
        async with session_scope(self._session_factory) as session:
            repo = DeliveryRepository(session)
            delivery = await repo.get(delivery_id)
            if delivery is None:
                raise NotFoundError(DELIVERY_KIND, delivery_id)
            cited_by = await repo.count_citing_corpora(delivery_id)
            if cited_by:
                raise DeliveryCitedError(str(delivery_id), cited_by)
            paths = [row.relative_path for row in delivery.files]
            uploaded = SourceKind(delivery.source_kind) is SourceKind.UPLOAD
            await repo.delete(delivery)

        # **After the commit, deliberately.** The two orders fail differently
        # and only one of them fails safely: bytes removed while the rows
        # survive leaves a delivery pointing at files that are not there,
        # while rows removed and bytes left leaves orphan files that
        # `just reset` clears. Removing them inside the transaction would pick
        # the first, because a commit can still fail after the unlink.
        if uploaded:
            await self._remove_stored_files(delivery_id, paths)

    # --- export before discard ---------------------------------------------

    async def run_export(self, run_id: RunId) -> RunExportView:
        """The run's `score` and `mismatch` rows, ready for the two writers.

        Rows rather than a path, and rows rather than the exporter fetching
        them itself — `P4-D3`'s reasoning, which is that a CSV assembled from a
        second read is a CSV that can disagree with what the caller is looking
        at.

        Feature keys, not feature ids: this file outlives the database rows it
        describes, so an opaque id in it would name nothing.

        :raises NotFoundError: no such run.
        """
        async with self._session_factory() as session:
            run = await self._require_run(session, run_id)
            keys = await self._feature_keys(session)
            scores = await ScoreRepository(session).for_run(run_id)
            mismatches = await MismatchRepository(session).for_run(run_id)
            return RunExportView(
                run_id=run_id,
                evaluation_id=EvaluationId(run.evaluation_id),
                model_tag=run.model_name,
                scores=tuple(
                    ScoreExportRow(
                        feature_key=keys.get(FeatureId(row.feature_id), str(row.feature_id)),
                        language=row.language,
                        metric=str(row.metric),
                        value=row.value,
                        n=row.n,
                        ci_low=row.ci_low,
                        ci_high=row.ci_high,
                    )
                    for row in scores
                ),
                mismatches=tuple(
                    MismatchExportRow(
                        mismatch_id=str(row.id),
                        record_id=RecordId(row.record_id),
                        feature_key=keys.get(FeatureId(row.feature_id), str(row.feature_id)),
                        record_value=row.record_value,
                        extracted_value=row.extracted_value,
                        evidence_span=row.evidence_span,
                        analyst_tag=row.analyst_tag,
                        tagged_at=row.tagged_at,
                        note=row.note,
                    )
                    for row in mismatches
                ),
            )

    # --- the header chip ---------------------------------------------------

    def data_dir(self) -> DataDirView:
        """Which database this process is looking at (§2.1 item 6), and
        **whether it is still the one it opened**.

        Synchronous and touching no session: it is a `Settings` value, and the
        reason it comes through a service at all is that `ra2/ui/` may not
        import `ra2/infra/` (§1.1). The identity check is one `os.stat` of a
        path this process already knows, on a call every page makes once —
        which is the cheapest place in the app to notice a swapped file, and
        the only one every screen passes through.

        **A file appearing where there was none is not a replacement.** The
        app can legitimately start before `alembic upgrade head` has created
        the database; the stamp is adopted then, and only a change from one
        known identity to a different one is reported.
        """
        identity = _file_identity(self._settings.database_path)
        replaced = False
        if self._database_identity is None:
            self._database_identity = identity
        elif identity is not None and identity != self._database_identity:
            replaced = True
        return DataDirView(
            data_dir=str(self._settings.data_dir),
            database_path=str(self._settings.database_path),
            database_replaced=replaced,
        )

    # --- internals ---------------------------------------------------------

    async def _run_preview(self, session: AsyncSession, run: Run) -> DiscardPreviewView:
        run_id = RunId(run.id)
        repo = RunRepository(session)
        status = RunStatus(run.status)
        active = status in ACTIVE_STATUSES
        mismatches, tagged = await repo.count_mismatches(run_id)
        return DiscardPreviewView(
            kind=RUN_KIND,
            target_id=str(run_id),
            label=f"{run_id} · {run.model_name}",
            runs=1,
            extractions=await repo.count_done(run_id),
            scores=await repo.count_scores(run_id),
            mismatches=mismatches,
            tagged_mismatches=tagged,
            files=0,
            active=active,
            active_detail=f"{run_id} is {status.value}" if active else None,
        )

    async def _require_run(self, session: AsyncSession, run_id: RunId) -> Run:
        run = await RunRepository(session).get(run_id)
        if run is None:
            raise NotFoundError(RUN_KIND, run_id)
        return run

    async def _require_evaluation(
        self, session: AsyncSession, evaluation_id: EvaluationId
    ) -> Evaluation:
        evaluation = await EvaluationRepository(session).get(evaluation_id)
        if evaluation is None:
            raise NotFoundError(EVALUATION_KIND, evaluation_id)
        return evaluation

    @staticmethod
    def _require_inactive(run: Run) -> None:
        """G1. Raised for the **active run**, not for the object the caller
        named, so the message says which one is in the way."""
        status = RunStatus(run.status)
        if status in ACTIVE_STATUSES:
            raise RunActiveError(str(run.id), status.value)

    @staticmethod
    def _require_no_tagged_work(kind: str, key: str, tagged: int, *, force: bool) -> None:
        """G2. Warn and allow — `force` is the whole difference between this
        and a block nobody can get past (R-D3)."""
        if tagged and not force:
            raise TaggedWorkPresentError(kind, key, tagged)

    async def _remove_stored_files(self, delivery_id: DeliveryId, paths: Sequence[str]) -> None:
        """Drop an upload delivery's bytes through the same `FileStore` seam
        intake used.

        A file already gone is not an error: the rows are the record of what
        was registered, and a hand-deleted file must not be able to block a
        discard. **The now-empty `{data_dir}/deliveries/{id}/` directory is
        left behind** — `FileStore` has no directory verb, and reaching around
        it with `pathlib` here would put filesystem knowledge in the one layer
        the seam exists to keep it out of. `just reset` is what removes the
        tree.
        """
        for relative_path in paths:
            try:
                await self._upload_store.remove(delivery_id, relative_path)
            except FileStoreError:
                continue

    @staticmethod
    async def _feature_keys(session: AsyncSession) -> dict[FeatureId, str]:
        """`feature id -> key` for the export's two tables. One query; the
        configs in play are small enough that narrowing it to a run's
        evaluation would cost a join to save nothing."""
        result = await session.execute(select(Feature.id, Feature.key))
        return {FeatureId(feature_id): key for feature_id, key in result}
