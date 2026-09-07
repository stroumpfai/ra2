# FROZEN — see CONTRACTS.md
"""The one LLM seam (mvp-spec.md §3).

    **Invariant:** one `LLMClient` protocol, and nothing else in the codebase
    imports `openai` or `ollama`.

Phase 1 has **no callers**. The protocol and `RA2_LLM_BASE_URL` exist from the
first commit so the invariant is in place before there is anything to violate
it (plan-phase-1.md §1).
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["Extraction", "LLMClient"]


@dataclass(frozen=True, slots=True)
class Extraction[T]:
    """One model's output for one (run, record). Immutable (mvp-spec.md N5).

    The **raw output string is stored verbatim** alongside the parsed value. A
    parse failure is a recorded outcome, not a retry-until-quiet: retries are
    bounded, counted and visible (mvp-spec.md §10.4).
    """

    #: The parsed payload, or `None` when `parse_ok` is False.
    value: T | None
    raw_output_text: str
    parse_ok: bool
    parse_error: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@runtime_checkable
class LLMClient(Protocol):
    """The only place `openai` or `ollama` may be imported (sw-design.md §12.1)."""

    async def extract[T](
        self,
        text: str,
        schema: type[T],
        model: str,
        *,
        temperature: float,
        seed: int,
    ) -> Extraction[T]:
        """One call per (record, model), covering all configured features (D5).

        `schema` is a Pydantic model type; it becomes a JSON Schema passed to
        the endpoint as `format:` for constrained decoding (mvp-spec.md §3).
        """
        ...
