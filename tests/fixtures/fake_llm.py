"""Test doubles for the LLM seam and the model catalogue.

Owned by H4 (`feat/p3-llm-adapter`); **seeded at M17 with a minimal working
body** so `tests/conftest.py`'s root fixtures do not have to wait for Wave 1,
the same reasoning `FrozenClock` and `SeededFactory` already live under. H4
extends these — scripted responses per record, injected failures, a latency
model — it does not start from nothing.

**No live endpoint in layers 1-4** (plan-phase-3.md §11): everything inside
`just test` and `just e2e` must pass on a machine with no GPU and nothing
listening on 11434. `tests/conftest.py`'s `app_factory` therefore substitutes
these by default, and the real `OllamaLLMClient` / `OllamaModelCatalog` are
only ever constructed by H4's own adapter tests against a local stub.
"""

from collections.abc import Sequence

from ra2.domain.llm import EndpointStatus, Extraction, ModelInfo

__all__ = ["DEFAULT_MODELS", "FakeLLMClient", "StaticModelCatalog"]

#: Three of the design's six fixture models — enough to select two and leave
#: one unselected, which is what the Evaluation journey needs.
DEFAULT_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(tag="llama3.1:8b-instruct-q8_0", digest="8fa1c3d0", size_bytes=8_500_000_000),
    ModelInfo(tag="qwen2.5:14b-instruct-q6_K", digest="c17b904e", size_bytes=12_100_000_000),
    ModelInfo(tag="llama3.3:70b-instruct-q4_K_M", digest="7e55aa12", size_bytes=42_500_000_000),
)


class FakeLLMClient:
    """A `domain.llm.LLMClient` that returns a canned response.

    Records every call on `calls`, so a test can assert *what was sent* — the
    resolved prompt is the thing most worth pinning, since it is what a run's
    fingerprints claim to describe.
    """

    def __init__(self, *, response: str = "{}", latency_ms: int = 1) -> None:
        self._response = response
        self._latency_ms = latency_ms
        self.calls: list[tuple[str, str, float, int]] = []

    async def extract[T](
        self,
        text: str,
        schema: type[T],
        model: str,
        *,
        temperature: float,
        seed: int,
    ) -> Extraction[T]:
        self.calls.append((text, model, temperature, seed))
        return Extraction[T](
            value=None,
            raw_output_text=self._response,
            parse_ok=True,
            latency_ms=self._latency_ms,
            prompt_tokens=len(text) // 4,
            completion_tokens=len(self._response) // 4,
        )


class StaticModelCatalog:
    """A `domain.llm.ModelCatalog` with a fixed answer.

    Construct with `status=EndpointStatus.UNREACHABLE` to exercise the
    disabled-Launch path: an unreachable endpoint yields an **empty list and
    a reason**, never an exception (sw-design.md §15.5).
    """

    def __init__(
        self,
        models: Sequence[ModelInfo] = DEFAULT_MODELS,
        *,
        status: EndpointStatus = EndpointStatus.REACHABLE,
    ) -> None:
        self._models = tuple(models)
        self._status = status

    async def models(self) -> tuple[ModelInfo, ...]:
        if self._status is not EndpointStatus.REACHABLE:
            return ()
        return self._models

    async def reachable(self) -> EndpointStatus:
        return self._status
