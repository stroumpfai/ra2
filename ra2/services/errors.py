# FROZEN — see CONTRACTS.md
"""Service-layer errors, and the HTTP status each maps to.

The API translates these; the UI renders them. Neither invents its own
vocabulary, so a blocking freeze looks the same through both adapters.
"""

from collections.abc import Sequence

from ra2.domain.findings import Finding

__all__ = [
    "BlockingFindingsError",
    "CorpusLockedError",
    "DeliveryNotAnalysedError",
    "NotFoundError",
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
