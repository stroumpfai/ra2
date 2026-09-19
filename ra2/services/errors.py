# FROZEN — see CONTRACTS.md
"""Service-layer errors, and the HTTP status each maps to.

The API translates these; the UI renders them. Neither invents its own
vocabulary, so a blocking freeze looks the same through both adapters.
"""

from collections.abc import Sequence

from ra2.domain.codes import CodeImportError
from ra2.domain.findings import Finding
from ra2.domain.llm import LlmEndpointError
from ra2.domain.prompt import PromptValidationError

__all__ = [
    "BlockingFindingsError",
    "CodelistImportError",
    "CorpusLockedError",
    "DeliveryCitedError",
    "DeliveryNotAnalysedError",
    "EvaluationLockedError",
    "FeatureConfigFrozenError",
    "FeatureValidationError",
    "LlmEndpointError",
    "NotFoundError",
    "PromptTemplateCitedError",
    "PromptTemplateInvalidError",
    "RunActiveError",
    "RunNotActiveError",
    "RunNotScoreableError",
    "RunNotScoredError",
    "ServiceError",
    "TaggedWorkPresentError",
]


class ServiceError(Exception):
    """Base for everything a service raises on purpose."""


class NotFoundError(ServiceError):
    """No such delivery, file, corpus or task. -> HTTP 404."""

    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"{kind} not found: {key}")
        self.kind = kind
        self.key = key


class BlockingFindingsError(ServiceError):
    """Cross-file validation refused the freeze. -> HTTP 422.

    **Nothing was written.** The findings go back to the analyst naming the
    offending key (mvp-spec.md §4.3, J2).
    """

    def __init__(self, findings: Sequence[Finding]) -> None:
        super().__init__(f"{len(findings)} blocking finding(s)")
        self.findings = tuple(findings)


class CorpusLockedError(ServiceError):
    """An evaluation cites this corpus, so it cannot be deleted. -> HTTP 409.

    The runs that cite it would stop being reproducible (sw-design.md §6.3, J3).
    """

    def __init__(self, corpus_id: str, evaluation_count: int) -> None:
        super().__init__(f"corpus {corpus_id} is cited by {evaluation_count} evaluation(s)")
        self.corpus_id = corpus_id
        self.evaluation_count = evaluation_count


class DeliveryNotAnalysedError(ServiceError):
    """Freeze was asked for before analysis finished. -> HTTP 409."""

    def __init__(self, delivery_id: str) -> None:
        super().__init__(f"delivery {delivery_id} has not been analysed")
        self.delivery_id = delivery_id


class CodelistImportError(ServiceError):
    """The uploaded file failed structural validation. -> HTTP 422.

    **Nothing was written** — sw-design.md §14.1 step 1 fails the whole
    import, never a partial one.
    """

    def __init__(self, import_errors: Sequence[CodeImportError]) -> None:
        super().__init__(f"{len(import_errors)} codelist import error(s)")
        self.import_errors = tuple(import_errors)


class FeatureValidationError(ServiceError):
    """One or more features block "Create a feature set". -> HTTP 422.

    mvp-spec.md §7/§8.2: an unmapped or codeless `enum` column, or a
    non-scalar grain, blocks the feature it belongs to. Raised only by
    `freeze()` — `add_feature`/`edit_feature` surface the same problems on
    the returned view instead of raising, so a draft can hold an error row.
    """

    def __init__(self, validation_errors: Sequence[str]) -> None:
        super().__init__(f"{len(validation_errors)} feature validation error(s)")
        self.validation_errors = tuple(validation_errors)


class FeatureConfigFrozenError(ServiceError):
    """An edit was attempted on a frozen feature set. -> HTTP 409.

    Frozen sets are immutable the moment "Create a feature set" is pressed
    (plan-phase-2.md F2) — cloning, not editing, is the only way forward.
    """

    def __init__(self, feature_config_id: str) -> None:
        super().__init__(f"feature config {feature_config_id} is frozen")
        self.feature_config_id = feature_config_id


# ===========================================================================
# Prompts and evaluation — phase 3 (M17), mvp-spec.md §9/§10,
# sw-design.md §15.
#
# **No new `FindingCode`s.** A parse failure is a recorded outcome on the
# `extraction` row, counted and visible (mvp-spec.md §10.4) — which is how
# Do-NOT #6 is satisfied without inventing a report vocabulary for a table
# that already stores the evidence. Phase 2 set this precedent with
# `CodelistImportError`.
# ===========================================================================


class PromptTemplateInvalidError(ServiceError):
    """A template failed `domain.prompt.validate_template`. -> HTTP 422.

    **Nothing was written** — validation runs on save and blocks it
    (sw-design.md §15.1). The payloads are `domain.prompt`'s, the same split
    `CodelistImportError` has from `domain.codes.CodeImportError`: the domain
    names the problem, the service raises the family the routers map.

    Named `…InvalidError` rather than plan-phase-3.md §5.1's
    `PromptValidationError` so it does not collide with the domain payload
    type of that name, which §5.1 also asks for (P3-D1 in CONTRACTS.md).
    """

    def __init__(self, validation_errors: Sequence[PromptValidationError]) -> None:
        super().__init__(f"{len(validation_errors)} prompt validation error(s)")
        self.validation_errors = tuple(validation_errors)


class PromptTemplateCitedError(ServiceError):
    """A delete or in-place edit of a version some run cites. -> HTTP 409.

    Copy-on-write: saving never mutates a cited version, it writes the next
    one and leaves the old text byte-identical, because the runs citing it
    must keep resolving to the exact text they used (sw-design.md §15.1). The
    design renders such a version `locked`.
    """

    def __init__(self, prompt_template_id: str, run_count: int) -> None:
        super().__init__(f"prompt template {prompt_template_id} is cited by {run_count} run(s)")
        self.prompt_template_id = prompt_template_id
        self.run_count = run_count


class EvaluationLockedError(ServiceError):
    """An edit was attempted after launch. -> HTTP 409.

    An evaluation is editable while `launched_at IS NULL` and immutable after
    (sw-design.md §15.2): a draft is a saved setup, an evaluation is a pinned
    one, and the runs citing it would stop being reproducible.
    """

    def __init__(self, evaluation_id: str) -> None:
        super().__init__(f"evaluation {evaluation_id} is launched")
        self.evaluation_id = evaluation_id


# ---------------------------------------------------------------------------
# Phase 4 (M27) — scoring. Two errors, and deliberately no new `FindingCode`s:
# a suppressed cell and an unscoreable feature are *rendered states*, not
# import defects, and Do-NOT #6 is about rows silently repaired or dropped
# during ingest. Phases 2 and 3 set this precedent twice.
# ---------------------------------------------------------------------------


class RunNotScoredError(ServiceError):
    """A result was asked for on a run that has no `score` rows. -> HTTP 409.

    Raised only where a *caller* has no way to render a state — an export, say.
    **The read paths do not raise it**: `GET .../results` on an unscored run is
    **200 with `scored: false`**, never a 404, because the UI renders a state
    and an error status would force the toast §16.7 rejects. The same reasoning
    §15.5 applied to an unreachable endpoint.
    """

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} has not been scored")
        self.run_id = run_id


class RunNotScoreableError(ServiceError):
    """This run cannot be scored at all. -> HTTP 422.

    Two causes, and the message names which:

    - the run is `failed` or `interrupted`. A partial corpus produces
      real-looking numbers over an unstated denominator, which is exactly the
      failure §11.4's suppression rule guards against at the other end of the
      scale. Only a `done` run is scored (sw-design.md §16.1).
    - the evaluation has **no labelled features** — every feature is
      exploratory, so there is no ground truth anywhere to score against
      (§11.3). Distinct from "every feature is suppressed", which *is*
      scoreable and renders as suppression.
    """

    def __init__(self, run_id: str, reason: str) -> None:
        super().__init__(f"run {run_id} cannot be scored: {reason}")
        self.run_id = run_id
        self.reason = reason


# ---------------------------------------------------------------------------
# Reset and discard (sw-design.md §18). Three errors, one per guard, and
# **no fourth guard added without §18.2 changing first** — each one is a rule
# a user has to learn from a message.
#
# No new `FindingCode`s, for the third time: a refused discard is a rendered
# state, not an import defect (phases 2, 3 and 4 each set this precedent).
# ---------------------------------------------------------------------------


class RunActiveError(ServiceError):
    """G1 — a `queued` or `running` run cannot be discarded. -> HTTP 409.

    `done`, `failed` and `interrupted` all can be: an interrupted run is
    exactly the debris this verb exists to clear, and refusing it would leave
    the only way to remove one being the SQLite file (sw-design.md §18.2).

    `run_id` is the **active** run, which for an evaluation discard is one of
    its runs rather than the object the caller named — so the message can say
    which one is in the way.
    """

    def __init__(self, run_id: str, status: str) -> None:
        super().__init__(f"run {run_id} is {status}")
        self.run_id = run_id
        self.status = status


class RunNotActiveError(ServiceError):
    """`RunActiveError`'s mirror — a run that is **not** `queued` or `running`
    has nothing to stop. -> HTTP 409.

    Two verbs guard on the same two statuses from opposite sides, which is why
    both errors exist. Discard refuses an active run, because a worker is
    writing to it (G1). Stop refuses an inactive one, because there is nothing
    executing it — and a Stop that silently "succeeded" on a run that had
    already finished would be the interesting case: it would rewrite a `done`
    run's outcome as an interruption that never happened.
    """

    def __init__(self, run_id: str, status: str) -> None:
        super().__init__(f"run {run_id} is {status}, not running")
        self.run_id = run_id
        self.status = status


class TaggedWorkPresentError(ServiceError):
    """G2 — the discard would destroy analyst tags. -> HTTP 409 **with the
    count**, and it is overridable.

    `mismatch.analyst_tag` is the one human-authored column in the pipeline.
    SD21 argues that a re-score must not lose it; a discard earns the identical
    argument and gets a weaker remedy on purpose — `force=True` proceeds.
    A hard block leaves no way to ever remove the run and pushes people to the
    database file (sw-design.md §18.2, R-D3).
    """

    def __init__(self, kind: str, key: str, tagged_count: int) -> None:
        super().__init__(f"{kind} {key} carries {tagged_count} tagged mismatch(es)")
        self.kind = kind
        self.key = key
        self.tagged_count = tagged_count


class DeliveryCitedError(ServiceError):
    """A corpus was frozen from this delivery. -> HTTP 409.

    Not policy so much as a hole in the schema: `corpus.delivery_id` is
    `ondelete="SET NULL"` (SD4 — a corpus outlives its delivery), so the
    database would quietly null the reference rather than refuse. The guard
    lives in the service because that is the only place it can (§18.2).
    """

    def __init__(self, delivery_id: str, corpus_count: int) -> None:
        super().__init__(f"delivery {delivery_id} is cited by {corpus_count} corpus/corpora")
        self.delivery_id = delivery_id
        self.corpus_count = corpus_count


# `LlmEndpointError` is **not defined here** — it lives in `ra2/domain/llm.py`,
# beside `EndpointStatus` and the `LLMClient` protocol whose implementations
# raise it, and is re-exported above so both adapters keep one import site.
#
# It moved down by amendment (feat/p3-llm-adapter). M17 put it here and
# documented it as "raised by `OllamaLLMClient` at construction" — but
# `ra2/infra/` may import `domain` only, so the module that raises it could
# not import it. The alternative was an `ignore_imports` edge inverting the
# layer rule permanently; moving the class costs four lines and puts the
# exception with the protocol it guards.
#
# It is deliberately **not** a `ServiceError`: nothing catches it. A
# non-loopback endpoint fails `create_app()` outright, and "unreachable" is
# not an exception at all — `GET /api/v1/models` returns 200 with
# `reachable: false`, because a 502 would force exactly the toast the design
# rejects (sw-design.md §15.5).
