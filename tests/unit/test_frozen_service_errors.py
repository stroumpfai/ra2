"""The service errors are an API contract: each one is an HTTP status.

Both adapters translate these, so what they carry has to be stable. Owned by
the lead with the rest of the M0 contract.
"""

import pytest

from ra2.domain.findings import Finding, FindingCode, Severity
from ra2.domain.llm import EndpointStatus
from ra2.domain.prompt import PromptValidationCode, PromptValidationError
from ra2.services.errors import (  # LlmEndpointError re-exported from ra2.domain.llm (P3-D12)
    BlockingFindingsError,
    CorpusLockedError,
    DeliveryNotAnalysedError,
    EvaluationLockedError,
    LlmEndpointError,
    NotFoundError,
    PromptTemplateCitedError,
    PromptTemplateInvalidError,
    ServiceError,
)

pytestmark = pytest.mark.unit


def test_every_service_error_is_one_family():
    """So a router can catch `ServiceError` and map, rather than listing."""
    for error in (
        NotFoundError,
        BlockingFindingsError,
        CorpusLockedError,
        DeliveryNotAnalysedError,
    ):
        assert issubclass(error, ServiceError)


def test_not_found_carries_the_kind_and_the_key():
    error = NotFoundError("corpus", "c-42")
    assert error.kind == "corpus"
    assert error.key == "c-42"
    assert "c-42" in str(error)


def test_blocking_findings_carries_the_findings_immutably():
    """422 returns the findings; J2 asserts the offending key is named."""
    findings = [
        Finding(
            code=FindingCode.DUP_KEY_CROSS_SET,
            severity=Severity.BLOCKING,
            key="a" * 32,
        )
    ]
    error = BlockingFindingsError(findings)
    findings.clear()

    assert len(error.findings) == 1
    assert isinstance(error.findings, tuple)
    assert error.findings[0].key == "a" * 32


def test_corpus_locked_names_the_corpus_and_the_count():
    """409: the runs citing it would stop being reproducible."""
    error = CorpusLockedError("c-1", 2)
    assert error.corpus_id == "c-1"
    assert error.evaluation_count == 2
    assert "c-1" in str(error)


def test_delivery_not_analysed_names_the_delivery():
    error = DeliveryNotAnalysedError("d-1")
    assert error.delivery_id == "d-1"
    assert "d-1" in str(error)


# ===========================================================================
# Prompts and evaluation — phase 3 (M17). Same reasoning as above: both
# adapters translate these, so what they carry has to be stable.
# ===========================================================================


def test_the_phase_3_errors_are_one_family_too():
    """`LlmEndpointError` is deliberately absent — see the test below."""
    for error in (
        PromptTemplateInvalidError,
        PromptTemplateCitedError,
        EvaluationLockedError,
    ):
        assert issubclass(error, ServiceError)


def test_llm_endpoint_error_is_one_class_and_deliberately_not_a_service_error():
    """P3-D12, and H4's amendment item 3.

    It lives in `ra2/domain/llm.py` because `ra2/infra/` — the layer that
    raises it — may import `domain` only. `services/errors.py` re-exports it
    so both adapters keep one import site, and **all three names must be the
    same class**: a second class with the same name is exactly the trap H4's
    shim warned about, where `except LlmEndpointError` silently catches
    nothing.

    It is **not** a `ServiceError` because nothing catches it. A non-loopback
    endpoint fails `create_app()` outright, and "unreachable" is not an
    exception at all — `GET /api/v1/models` answers 200 with
    `reachable: false`, because a 502 would force the toast the design
    rejects (sw-design.md §15.5).
    """
    from ra2.domain.llm import LlmEndpointError as from_domain
    from ra2.infra.ollama_client import LlmEndpointError as from_infra

    assert LlmEndpointError is from_domain is from_infra
    assert from_domain.__module__ == "ra2.domain.llm"
    assert not issubclass(LlmEndpointError, ServiceError)
    assert issubclass(LlmEndpointError, Exception)


def test_prompt_template_invalid_carries_the_typed_payloads_immutably():
    """422 returns the validation errors themselves, not a sentence: the
    router sends `code`, and wording lives in one rendering table in `ui/`."""
    issues = [
        PromptValidationError(code=PromptValidationCode.MISSING_REQUIRED_SLOT, slot="narrative")
    ]
    error = PromptTemplateInvalidError(issues)
    issues.clear()

    assert isinstance(error.validation_errors, tuple)
    assert len(error.validation_errors) == 1
    assert error.validation_errors[0].code is PromptValidationCode.MISSING_REQUIRED_SLOT
    assert error.validation_errors[0].slot == "narrative"


def test_prompt_template_cited_names_the_version_and_the_count():
    """409: the runs citing it must keep resolving to the exact text they
    used, so a cited version is never deleted (sw-design.md §15.1)."""
    error = PromptTemplateCitedError("pt-4", 3)
    assert error.prompt_template_id == "pt-4"
    assert error.run_count == 3
    assert "pt-4" in str(error)


def test_evaluation_locked_names_the_evaluation():
    """409: editable while `launched_at IS NULL`, immutable after."""
    error = EvaluationLockedError("e-1")
    assert error.evaluation_id == "e-1"
    assert "e-1" in str(error)


def test_llm_endpoint_carries_the_url_and_the_status():
    """The non-loopback refusal is raised at client construction and names
    N1 — there is deliberately no opt-out setting (§15 F4)."""
    error = LlmEndpointError("http://192.168.1.9:11434/v1", EndpointStatus.REFUSED_NOT_LOOPBACK)
    assert error.base_url == "http://192.168.1.9:11434/v1"
    assert error.status is EndpointStatus.REFUSED_NOT_LOOPBACK
    assert "192.168.1.9" in str(error)
