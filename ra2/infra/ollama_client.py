# STUB — bodies owned by H4 (feat/p3-llm-adapter). Not frozen.
"""The one place `openai` exists (sw-design.md §15.5, Do-NOT #1).

`OllamaLLMClient` implements `domain.llm.LLMClient`; `OllamaModelCatalog`
implements `domain.llm.ModelCatalog`. This is the **only module in the repo
permitted to import `openai`**, which `.importlinter`'s `one-llm-seam`
contract enforces against every other package.

**The `openai` SDK alone; PydanticAI is dropped** (SD14, §15 F3). The one call
this product makes is "one prompt, one JSON Schema, one response".
PydanticAI's value is an agent loop nobody here wants, and it would be a
*second* place a provider client gets constructed — exactly what Do-NOT #1
exists to prevent. Pydantic model -> JSON Schema -> the endpoint's constrained
decoding, through `/v1`.

**The loopback guard.** The client refuses, **at construction**, a `base_url`
whose host is not loopback (`127.0.0.1`, `::1`, `localhost`), raising
`LlmEndpointError` naming N1. mvp-spec.md §19.10 permits egress to "the
configured LLM endpoint" and N1 forbids data leaving the host; a configurable
URL with no guard satisfies neither, and a typo or a copied `.env` would ship
accident narratives to a LAN address. **There is deliberately no opt-out
setting** — an opt-out is how "no data leaves the host" becomes "no data
leaves the host by default".

**Unreachable is a state, not an error.** `reachable()` returns a status; the
service hands the view an empty model list and a reason; the view renders it
beside the endpoint line and disables Launch. Never a toast, never a 502.

**Testing note for H4** (plan-phase-3.md §7): the suite must pass on a machine
with no GPU and nothing on port 11434, so the endpoint is stubbed locally. Note
that `openai` 3.x is built on **`httpx2`**, not `httpx` — pass an
`httpx2.AsyncClient` over `httpx2.MockTransport` (or `ASGITransport` onto a
tiny stub app) as the SDK's `http_client`. `respx` targets `httpx` 0.x and is
not the tool here; nothing new needs adding to `pyproject.toml`, which is
frozen after this wave.
"""

from ra2.domain.llm import EndpointStatus, Extraction, ModelInfo

__all__ = ["LOOPBACK_HOSTS", "OllamaLLMClient", "OllamaModelCatalog"]

#: The only hosts the guard accepts. Written out rather than resolved through
#: DNS: a name that resolves to loopback *today* is not a guarantee, and this
#: list is the whole of what N1 permits.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "[::1]", "localhost"})


class OllamaLLMClient:
    """`domain.llm.LLMClient` over Ollama's OpenAI-compatible `/v1`.

    The timeout belongs here, to construction, not to a per-call argument —
    which is why `LLMClient.extract` never took one. `max_retries` is
    **bounded and counted**: the count is carried back on the returned
    `Extraction` and rendered in the progress card's metrics line, never
    swallowed (mvp-spec.md §10.4).

    H4 adds the loopback check to `__init__`. It must raise
    `LlmEndpointError(base_url, EndpointStatus.REFUSED_NOT_LOOPBACK)` before
    any socket is opened — and before `create_app()` finishes, which is the
    point: a misconfigured host fails at start, not at the first narrative.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: int = 120,
        max_retries: int = 2,
    ) -> None:
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._max_retries = max_retries

    @property
    def base_url(self) -> str:
        return self._base_url

    async def extract[T](
        self,
        text: str,
        schema: type[T],
        model: str,
        *,
        temperature: float,
        seed: int,
    ) -> Extraction[T]:
        """One call per (record, model), covering all configured features.

        `text` is the already-resolved prompt; `schema` is the Pydantic model
        `domain.extraction.build_output_schema` built for this feature set,
        sent as a JSON Schema for constrained decoding.

        Latency and the **real** token counts are populated from the
        response. A response that does not parse is still returned, with
        `parse_ok=False` and `raw_output_text` verbatim — the caller records
        it and the run continues.
        """
        raise NotImplementedError


class OllamaModelCatalog:
    """`domain.llm.ModelCatalog` — tag, digest, size, and reachability.

    Separate from the client because the Evaluation view asks for the
    catalogue before any run exists, and a catalogue call must never be able
    to look like an extraction call in a log.
    """

    def __init__(self, *, base_url: str, timeout_s: int = 120) -> None:
        self._base_url = base_url
        self._timeout_s = timeout_s

    async def models(self) -> tuple[ModelInfo, ...]:
        """Every model the endpoint offers. **Empty when unreachable** —
        never an exception into the service layer."""
        raise NotImplementedError

    async def reachable(self) -> EndpointStatus:
        """Ask the endpoint, now. Never on a timer (plan-phase-3.md C3)."""
        raise NotImplementedError
