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

---

## What H4 added, and why (read before changing any of it)

**Amendments are open against the frozen contract**
(`contracts/amendments/feat-p3-llm-adapter.md`). Until they land, two names
below are shims, each marked `SHIM`:

1. `LlmEndpointError` — sw-design.md §15.5 and `ra2/services/errors.py`'s own
   docstring both say this module raises `services.errors.LlmEndpointError`.
   `ra2/infra/` may import `domain` only, so `lint-imports` rejects that
   import today. The shim is a structurally identical local class with the
   same name, the same constructor and the same message.
2. `RetriedExtraction` — §15.4 requires the retry count "carried back on the
   `Extraction`", and the frozen `domain.llm.Extraction` has no field for it.
   The shim is a subclass that adds `retry_count`.

**One HTTP client per adapter, and both hold the guard.** The catalogue opens
a socket too, so it checks the same `base_url` through the same
`require_loopback()`. A guard on only one of the two classes would be a hole
in the one thing standing between this codebase and N1.

**The SDK's own retries are turned off** (`max_retries=0`). §10.4 asks for
retries that are *bounded, counted and visible*; the SDK's would be bounded
and invisible, and the two layered would multiply. The loop here owns the
count, and the count reaches the returned `Extraction`.

**A parse failure is a datum; an endpoint failure is an exception.** They are
different outcomes and the worker treats them differently (sw-design.md
§15.3): bad model output produces a row with `parse_ok=False` and the raw
text verbatim, and the run continues; an endpoint that will not answer after
its bounded retries raises, writes no row, and leaves the hole that the resume
query is specified to find. A parse failure is never retried — temperature and
seed are fixed, so the retry would return the same bytes.

**The catalogue reads Ollama's native `/api/tags`, not `/v1/models`.**
`ModelInfo` carries `digest` and `size_bytes` and `fits_vram` is computed from
the latter (§15.6); OpenAI-compatible `/v1/models` reports neither. The call
goes through the *same* `AsyncOpenAI` instance with an absolute URL, so
there is still exactly one provider client per adapter — which is the whole of
Do-NOT #1.
"""

import time
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import httpx2

# **One** `import openai` statement, in the one module permitted to have it —
# and one statement rather than several `from openai import …` lines because
# `tests/test_p3_contract.py::test_openai_is_imported_in_exactly_one_module`
# counts import *statements*, not modules. Everything the adapter needs is
# reached through this name, so the seam is visible at every use site.
import openai

from ra2.domain.llm import EndpointStatus, Extraction, ModelInfo

__all__ = [
    "LOOPBACK_HOSTS",
    "RETRYABLE_STATUS_CODES",
    "LlmEndpointError",
    "OllamaLLMClient",
    "OllamaModelCatalog",
    "RetriedExtraction",
    "native_api_url",
    "require_loopback",
]

#: The only hosts the guard accepts. Written out rather than resolved through
#: DNS: a name that resolves to loopback *today* is not a guarantee, and this
#: list is the whole of what N1 permits.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "[::1]", "localhost"})

#: The only URL schemes the guard accepts. Anything else (`file:`, `ftp:`, a
#: bare `host:port` that `urlsplit` reads as a scheme) is refused rather than
#: interpreted.
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: A transport failure or one of these statuses is worth asking again about; a
#: 4xx is not. A wrong model name does not become right on the second attempt,
#: and retrying it burns the bound that a genuinely busy endpoint needs.
RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

#: Ollama's OpenAI-compatible surface lives under `/v1`; its native API, the
#: one that reports a digest and a size, lives beside it.
_OPENAI_COMPAT_SUFFIX = "/v1"
_NATIVE_TAGS_PATH = "/api/tags"

#: The SDK refuses to construct without a key. Ollama ignores it entirely, and
#: no credential of the user's is ever put on the wire (N1/N2).
_UNUSED_API_KEY = "ollama"


class LlmEndpointError(Exception):
    """SHIM — see `contracts/amendments/feat-p3-llm-adapter.md`.

    This *should* be `ra2.services.errors.LlmEndpointError`, which
    sw-design.md §15.5 names and whose own docstring says it is "raised by
    `OllamaLLMClient` at construction". `ra2/infra/` may import `domain` only,
    so `lint-imports` rejects `ra2.infra.ollama_client -> ra2.services.errors`
    (verified, not assumed). The amendment proposes the one `ignore_imports`
    line that permits it — the mirror image of the M0-D4 deviation already
    recorded in `CONTRACTS.md`.

    Deliberately the **same name, constructor and message** as the real one, so
    applying the amendment deletes this class and adds one import, and changes
    nothing else here or in the tests.
    """

    def __init__(self, base_url: str, status: EndpointStatus) -> None:
        super().__init__(f"llm endpoint {base_url}: {status.value}")
        self.base_url = base_url
        self.status = status


@dataclass(frozen=True, slots=True)
class RetriedExtraction[T](Extraction[T]):
    """SHIM — see `contracts/amendments/feat-p3-llm-adapter.md`.

    sw-design.md §15.4: "`RA2_LLM_MAX_RETRIES`, the count carried back on the
    `Extraction` and rendered in the progress card's metrics line". The frozen
    `domain.llm.Extraction` has no field to carry it, and
    `persistence.models.extraction.retry_count`, `readmodels` and
    `api.schemas` all expect the number — so the seam between them is the one
    place it is missing. The amendment proposes `retry_count: int = 0` on
    `Extraction` itself; this subclass is what makes the run work meanwhile,
    and is a `domain.llm.Extraction` for every purpose.
    """

    #: Retries **performed**, not attempts made: `0` means the first call
    #: answered. Bounded by `RA2_LLM_MAX_RETRIES`.
    retry_count: int = 0


class _JsonSchemaModel(Protocol):
    """What `extract` needs of the `schema` argument.

    `LLMClient.extract` is declared over a bare `type[T]`, but what
    `domain.extraction.build_output_schema` hands it is always a Pydantic
    model. Stating the two methods used, rather than depending on `BaseModel`
    here, keeps the requirement at the seam where it is actually consumed.
    """

    @classmethod
    def model_json_schema(cls) -> dict[str, Any]: ...

    @classmethod
    def model_validate_json(cls, json_data: str | bytes) -> Any: ...


class _OllamaTag(openai.BaseModel):
    """One entry of Ollama's native `/api/tags`.

    An `openai.BaseModel`, not a bare `pydantic.BaseModel`: the SDK's response
    parser refuses anything else, and using its own model keeps parsing
    tolerant of fields Ollama adds later.
    """

    name: str | None = None
    model: str | None = None
    digest: str | None = None
    size: int | None = None


class _OllamaTags(openai.BaseModel):
    models: list[_OllamaTag] | None = None


def require_loopback(base_url: str) -> None:
    """Refuse a `base_url` that is not on this host. **N1, and no opt-out.**

    Raises `LlmEndpointError(base_url, EndpointStatus.REFUSED_NOT_LOOPBACK)`.

    The host is compared against `LOOPBACK_HOSTS` **literally**: no DNS, no
    `socket.getaddrinfo`, no "does it resolve to 127.0.0.1". A name that
    resolves to loopback on this machine today resolves wherever its owner
    points it tomorrow, and the guarantee this guard carries has to be
    readable from the configuration alone.

    `urlsplit(...).hostname` lower-cases and strips the brackets from an IPv6
    literal, so `http://[::1]:11434/v1` is compared as `::1`. It returns
    `None` for a string with no authority, which is refused: an endpoint this
    function cannot parse is not an endpoint it can vouch for.
    """
    try:
        parts = urlsplit(base_url)
        host = parts.hostname
        # `.hostname` does not validate the port; `.port` does. A `base_url`
        # this function cannot fully parse is one it cannot vouch for.
        _ = parts.port
    except ValueError as exc:  # a malformed port, an unparseable IPv6 literal
        raise LlmEndpointError(base_url, EndpointStatus.REFUSED_NOT_LOOPBACK) from exc
    if parts.scheme.lower() not in ALLOWED_SCHEMES or host is None:
        raise LlmEndpointError(base_url, EndpointStatus.REFUSED_NOT_LOOPBACK)
    if host.lower() not in LOOPBACK_HOSTS:
        raise LlmEndpointError(base_url, EndpointStatus.REFUSED_NOT_LOOPBACK)


def native_api_url(base_url: str, path: str) -> str:
    """The native-API sibling of an OpenAI-compatible `base_url`.

    `http://127.0.0.1:11434/v1` + `/api/tags` -> `http://127.0.0.1:11434/api/tags`.
    A `base_url` that does not end in `/v1` is treated as the root already, so
    a user who configured the native root by hand still gets a working
    catalogue rather than a 404.
    """
    root = base_url.rstrip("/")
    if root.endswith(_OPENAI_COMPAT_SUFFIX):
        root = root[: -len(_OPENAI_COMPAT_SUFFIX)]
    return f"{root.rstrip('/')}{path}"


def _build_client(
    *, base_url: str, timeout_s: int, http_client: httpx2.AsyncClient | None
) -> openai.AsyncOpenAI:
    """The one provider client. `max_retries=0` on purpose — see the module
    docstring.

    `http_client` is a seam, not a test-mode branch (Do-NOT #12): it is the
    same shape as `create_app()`'s injectable adapters, and production passes
    nothing. It is how the adapter tests drive a `httpx2.MockTransport` stub
    of the endpoint without a socket, a GPU or anything on port 11434.
    """
    return openai.AsyncOpenAI(
        base_url=base_url,
        api_key=_UNUSED_API_KEY,
        timeout=float(timeout_s),
        max_retries=0,
        http_client=http_client,
    )


def _is_retryable(error: Exception) -> bool:
    """A transport failure or a busy/temporary status. Never a 4xx."""
    if isinstance(error, openai.APIConnectionError):  # APITimeoutError subclasses this
        return True
    if isinstance(error, openai.APIStatusError):
        return error.status_code in RETRYABLE_STATUS_CODES
    return False


def _response_format(schema: type[object]) -> openai.types.shared_params.ResponseFormatJSONSchema:
    """Pydantic model -> JSON Schema -> the endpoint's constrained decoding.

    Key order comes straight from the model and is therefore as stable as
    `build_output_schema` makes it — two runs must ask the same question
    (sw-design.md §15.3).
    """
    model = cast("type[_JsonSchemaModel]", schema)
    return openai.types.shared_params.ResponseFormatJSONSchema(
        type="json_schema",
        json_schema={
            "name": getattr(schema, "__name__", "output"),
            "schema": cast("dict[str, object]", model.model_json_schema()),
            "strict": True,
        },
    )


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
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        # First statement in the constructor, before the SDK client exists:
        # nothing in this object can open a socket until the URL has passed.
        require_loopback(base_url)
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._max_retries = max(0, max_retries)
        self._client = _build_client(
            base_url=base_url, timeout_s=timeout_s, http_client=http_client
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def max_retries(self) -> int:
        """The bound, after clamping. `RA2_LLM_MAX_RETRIES` is a count of
        *retries*, so the endpoint is called at most `max_retries + 1` times."""
        return self._max_retries

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

        Raises `LlmEndpointError(base_url, EndpointStatus.UNREACHABLE)` when
        the endpoint will not answer within the bound. That is the one
        outcome that must *not* become a row: a record whose retries were
        exhausted leaves the hole in the middle of a run that the resume query
        exists to find (sw-design.md §15.3).
        """
        response_format = _response_format(schema)
        started = time.perf_counter()
        retries = 0
        while True:
            try:
                completion = await self._client.chat.completions.create(
                    model=model,
                    messages=[
                        openai.types.chat.ChatCompletionUserMessageParam(role="user", content=text)
                    ],
                    response_format=response_format,
                    temperature=temperature,
                    seed=seed,
                )
            except (openai.APIConnectionError, openai.APIStatusError) as exc:
                if retries >= self._max_retries or not _is_retryable(exc):
                    raise LlmEndpointError(self._base_url, EndpointStatus.UNREACHABLE) from exc
                retries += 1
                continue
            break

        latency_ms = int((time.perf_counter() - started) * 1000)
        raw_output_text = _first_content(completion)
        prompt_tokens, completion_tokens = _token_counts(completion)
        parsed, parse_error = _parse(schema, raw_output_text)
        return RetriedExtraction[T](
            value=parsed,
            raw_output_text=raw_output_text,
            parse_ok=parse_error is None,
            parse_error=parse_error,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            retry_count=retries,
        )


class OllamaModelCatalog:
    """`domain.llm.ModelCatalog` — tag, digest, size, and reachability.

    Separate from the client because the Evaluation view asks for the
    catalogue before any run exists, and a catalogue call must never be able
    to look like an extraction call in a log.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: int = 120,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        # The catalogue opens a socket too. Same guard, same constructor
        # position, same absence of an opt-out.
        require_loopback(base_url)
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._tags_url = native_api_url(base_url, _NATIVE_TAGS_PATH)
        self._client = _build_client(
            base_url=base_url, timeout_s=timeout_s, http_client=http_client
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    async def models(self) -> tuple[ModelInfo, ...]:
        """Every model the endpoint offers. **Empty when unreachable** —
        never an exception into the service layer."""
        payload = await self._fetch_tags()
        if payload is None:
            return ()
        return tuple(info for info in (_to_model_info(tag) for tag in payload.models or []) if info)

    async def reachable(self) -> EndpointStatus:
        """Ask the endpoint, now. Never on a timer (plan-phase-3.md C3).

        Only ever `REACHABLE` or `UNREACHABLE`: `REFUSED_NOT_LOOPBACK` is
        settled in `__init__`, so an instance that exists has already passed
        the guard.
        """
        if await self._fetch_tags() is None:
            return EndpointStatus.UNREACHABLE
        return EndpointStatus.REACHABLE

    async def _fetch_tags(self) -> _OllamaTags | None:
        """`None` for every failure — connection refused, a timeout, a 500, a
        body that is not the shape we expect. The distinction between them is
        not one the view can act on, and the view is the only caller."""
        try:
            return await self._client.get(self._tags_url, cast_to=_OllamaTags)
        except openai.APIConnectionError, openai.APIStatusError, ValueError, TypeError:
            return None


def _first_content(completion: Any) -> str:
    """The assistant message, verbatim and never `None`.

    An endpoint that answers with no choices, or with a `None` content, has
    produced an empty output — which is a parse failure to record, not a
    crash.
    """
    choices = getattr(completion, "choices", None) or []
    if not choices:
        return ""
    return cast("str", getattr(choices[0].message, "content", None) or "")


def _token_counts(completion: Any) -> tuple[int | None, int | None]:
    """The **real** counts, from the response. `domain.prompt.estimate_tokens`
    is the estimate the preview renders; this is the number that has to be
    right (sw-design.md §15.1)."""
    usage = getattr(completion, "usage", None)
    if usage is None:
        return (None, None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    return (
        int(prompt_tokens) if prompt_tokens is not None else None,
        int(completion_tokens) if completion_tokens is not None else None,
    )


def _parse[T](schema: type[T], raw_output_text: str) -> tuple[T | None, str | None]:
    """Validate the output against the schema. **Never raises, never repairs.**

    Returns `(value, None)` or `(None, reason)`. The reason is a short type
    name plus the validator's own message: it is stored in
    `extraction.parse_error` and shown to an analyst, so it has to say what
    went wrong without being a traceback.
    """
    model = cast("type[_JsonSchemaModel]", schema)
    try:
        return (cast("T", model.model_validate_json(raw_output_text)), None)
    except Exception as exc:
        return (None, f"{type(exc).__name__}: {exc}")


def _to_model_info(tag: _OllamaTag) -> ModelInfo | None:
    """One `/api/tags` entry as a `ModelInfo`, or `None` for an entry with no
    name — an unnamed model is not one a user can select."""
    name = tag.model or tag.name
    if not name:
        return None
    return ModelInfo(tag=name, digest=tag.digest or "", size_bytes=int(tag.size or 0))
