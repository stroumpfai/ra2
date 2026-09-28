"""The live Ollama connection, rebindable on a settings save (sw-design.md SD43).

One object that satisfies **both** `LLMClient` and `ModelCatalog` by delegating
to the `OllamaLLMClient` and `OllamaModelCatalog` it currently holds.
`create_app()` wires it where it wired those two, and `SettingsService` calls
`rebind` when an analyst saves a new endpoint or timeout — so the next run and
the next catalogue read use the new values with **no restart**.

**Rebound on save, not rebuilt per run.** `SD36` rejected a client per run —
a second loopback guard and a second connection pool inside the record loop —
and its reasons stand. A save is rare and human, so that is where the new pair
is built.

**Both built before either is swapped.** `OllamaLLMClient` and
`OllamaModelCatalog` each call `require_loopback` first thing in their
constructors; a refused URL raises there, and this object is left bound to
exactly what it was. There is no opt-out here either.

**No run is using the old pair when it is dropped**: `SettingsService` refuses
a save while any run is queued or running (D6). A call already in flight keeps
the adapter it started with, because each delegation reads the current one
once, at the start.

The adapters are never closed, here or anywhere: the app has always held its
one pair for the life of the process, and a rebind simply lets the old one go.
"""

from ra2.domain.llm import EndpointStatus, Extraction, ModelInfo
from ra2.infra.ollama_client import OllamaLLMClient, OllamaModelCatalog

__all__ = ["OllamaConnection"]


class OllamaConnection:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: int,
        max_retries: int,
        reasoning_effort: str,
    ) -> None:
        # Fixed for the life of the process: neither is an analyst's setting
        # (SD43 moves exactly two), so a rebind carries them over unchanged.
        self._max_retries = max_retries
        self._reasoning_effort = reasoning_effort
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._client, self._catalog = self._build(base_url, timeout_s)

    @property
    def base_url(self) -> str:
        """The endpoint this connection is bound to now."""
        return self._base_url

    @property
    def timeout_s(self) -> int:
        return self._timeout_s

    def rebind(self, base_url: str, timeout_s: int) -> None:
        """Bind to a new endpoint and timeout.

        :raises LlmEndpointError: `base_url` is not loopback — raised while
            building the new pair, so nothing has been swapped.
        """
        client, catalog = self._build(base_url, timeout_s)
        self._client, self._catalog = client, catalog
        self._base_url, self._timeout_s = base_url, timeout_s

    def _build(self, base_url: str, timeout_s: int) -> tuple[OllamaLLMClient, OllamaModelCatalog]:
        client = OllamaLLMClient(
            base_url=base_url,
            timeout_s=timeout_s,
            max_retries=self._max_retries,
            reasoning_effort=self._reasoning_effort,
        )
        catalog = OllamaModelCatalog(base_url=base_url, timeout_s=timeout_s)
        return client, catalog

    # --- LLMClient -----------------------------------------------------------

    async def extract[T](
        self,
        text: str,
        schema: type[T],
        model: str,
        *,
        temperature: float,
        seed: int,
        reasoning_effort: str | None = None,
    ) -> Extraction[T]:
        return await self._client.extract(
            text,
            schema,
            model,
            temperature=temperature,
            seed=seed,
            reasoning_effort=reasoning_effort,
        )

    # --- ModelCatalog --------------------------------------------------------

    async def models(self) -> tuple[ModelInfo, ...]:
        return await self._catalog.models()

    async def reachable(self) -> EndpointStatus:
        return await self._catalog.reachable()

    async def version(self) -> str | None:
        return await self._catalog.version()

    async def loaded(self) -> tuple[str, ...]:
        return await self._catalog.loaded()

    async def release(self, tag: str) -> None:
        await self._catalog.release(tag)
