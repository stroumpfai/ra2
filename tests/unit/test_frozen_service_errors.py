"""The service errors are an API contract: each one is an HTTP status.

Both adapters translate these, so what they carry has to be stable. Owned by
the lead with the rest of the M0 contract.
"""

import pytest

from ra2.domain.findings import Finding, FindingCode, Severity
from ra2.services.errors import (
    BlockingFindingsError,
    CorpusLockedError,
    DeliveryNotAnalysedError,
    NotFoundError,
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
