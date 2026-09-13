# FROZEN — see CONTRACTS.md
"""Service-layer errors, and the HTTP status each maps to.

The API translates these; the UI renders them. Neither invents its own
vocabulary, so a blocking freeze looks the same through both adapters.
"""

from collections.abc import Sequence

from ra2.domain.codes import CodeImportError
from ra2.domain.findings import Finding
from ra2.domain.llm import EndpointStatus
from ra2.domain.prompt import PromptValidationError

__all__ = [
    "BlockingFindingsError",
    "CodelistImportError",
    "CorpusLockedError",
    "DeliveryNotAnalysedError",
    "EvaluationLockedError",
    "FeatureConfigFrozenError",
    "FeatureValidationError",
    "LlmEndpointError",
    "NotFoundError",
    "PromptTemplateCitedError",
    "PromptTemplateInvalidError",
    "ServiceError",
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


class LlmEndpointError(ServiceError):
    """The configured endpoint cannot be used. -> HTTP 422 at construction.

    Two causes, one type:

    - `REFUSED_NOT_LOOPBACK` — the configured `base_url`'s host is not
      loopback. Raised by `OllamaLLMClient` **at construction**, naming N1.
      There is deliberately **no opt-out setting**: an opt-out is how "no data
      leaves the host" becomes "no data leaves the host by default"
      (mvp-spec.md §19.10, sw-design.md §15.5).
    - `UNREACHABLE` — nothing is listening. This one is normally **not** an
      exception at all: `evaluation_service` hands the view an empty model
      list and a reason, and the view disables Launch beside the endpoint
      line. `GET /api/v1/models` returns 200 with `reachable: false`, never a
      502 — a 502 would force exactly the toast the design rejects.
    """

    def __init__(self, base_url: str, status: EndpointStatus) -> None:
        super().__init__(f"llm endpoint {base_url}: {status.value}")
        self.base_url = base_url
        self.status = status
