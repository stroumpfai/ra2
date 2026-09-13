# FROZEN — see CONTRACTS.md
"""The one LLM seam (mvp-spec.md §3).

    **Invariant:** one `LLMClient` protocol, and nothing else in the codebase
    imports `openai` or `ollama`.

Phases 1 and 2 had **no callers**. The protocol and `RA2_LLM_BASE_URL` existed
from the first commit so the invariant was in place before there was anything
to violate it (plan-phase-1.md §1). Phase 3 is where the caller arrives:
`ra2.infra.ollama_client` implements both protocols below and is the one module
in the repo permitted to import `openai` (sw-design.md §15.5).

`LLMClient` itself is **unchanged** — `extract(text, schema, model, *,
temperature, seed)` is exactly adequate: `text` takes the resolved prompt, and
the timeout belongs to client construction, not to a per-call argument.
Confirming that was part of M17's job (plan-phase-3.md §5.1).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

__all__ = [
    "EndpointStatus",
    "Extraction",
    "LLMClient",
    "LlmEndpointError",
    "ModelCatalog",
    "ModelInfo",
]


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
    #: Retries **performed**, not attempts made: `0` means the first call
    #: answered. Bounded by `RA2_LLM_MAX_RETRIES` and never silent — this is
    #: the number `extraction.retry_count` stores and the progress card's
    #: "retries N (bounded, counted)" line renders (mvp-spec.md §10.4,
    #: sw-design.md §15.4). Added by amendment: M17 gave the count a column, a
    #: read model and an API field, and left it off the one type that crosses
    #: the seam where the retries actually happen (amendment:
    #: feat/p3-llm-adapter).
    retry_count: int = 0


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


# ===========================================================================
# The model catalogue — phase 3 (M17, plan-phase-3.md §3.1)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """One model the endpoint has. Exactly what Ollama reports, and no more.

    It does **not** report the host's VRAM, which is why `fits_vram` is not a
    field here: that judgement needs `infra/gpu.py`'s probe and is made one
    layer up, in `evaluation_service` (sw-design.md §15.6).
    """

    tag: str
    digest: str
    size_bytes: int


class EndpointStatus(StrEnum):
    """Whether the configured endpoint is there.

    **Unreachable is a state, not an error** (sw-design.md §15.5): the service
    hands the view an empty model list and a reason, the view renders it beside
    the endpoint line and disables Launch. Never a toast, never a 502 — a 502
    would force exactly the toast the design rejects.
    """

    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    #: Refused before a socket was opened: the configured `base_url` is not
    #: loopback (N1, sw-design.md §15.5). There is deliberately no opt-out.
    REFUSED_NOT_LOOPBACK = "refused_not_loopback"


@runtime_checkable
class ModelCatalog(Protocol):
    """What the endpoint has, and whether it is there at all.

    Declared at M17 so H4 (the adapter) and I2 (`evaluation_service`) build in
    different waves against one shape, the same trick `CensusMaterialiser` and
    `EnumCodeTableProvider` played before it.
    """

    async def models(self) -> tuple[ModelInfo, ...]:
        """Every model the endpoint offers. **Empty when unreachable** — never
        an exception into the service layer."""
        ...

    async def reachable(self) -> EndpointStatus:
        """Ask the endpoint, now. Re-checked on view load and when the
        settings dialog's "refresh" is pressed — never on a timer."""
        ...


class LlmEndpointError(Exception):
    """The configured endpoint cannot be used.

    Lives here rather than in `services/errors.py` (where M17 first put it)
    because `ra2/infra/` may import `domain` only, and the module that raises
    it is `ra2/infra/ollama_client.py`. The exception belongs with the
    protocol it guards — the same shape `domain.codes.CodeImportError` has
    (amendment: feat/p3-llm-adapter). `services/errors.py` re-exports it so
    both adapters keep one import site.

    Two causes, one type:

    - `REFUSED_NOT_LOOPBACK` — the configured `base_url`'s host is not
      loopback. Raised by `OllamaLLMClient` **at construction**, naming N1.
      There is deliberately **no opt-out setting**: an opt-out is how "no data
      leaves the host" becomes "no data leaves the host by default"
      (mvp-spec.md §19.10, sw-design.md §15.5). It is not caught anywhere —
      an app configured this way does not start, which is the point.
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
