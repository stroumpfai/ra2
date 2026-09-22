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
`LlmEndpointError` naming N1. The rule itself now lives in `domain.llm`
(`classify_endpoint`/`require_loopback`) because the settings dialog has to
apply the *same* rule to the endpoint you type, and `ra2/ui/` may not import
`ra2/infra/`; this module re-exports it so every caller here keeps one import
site. mvp-spec.md §19.10 permits egress to "the
configured LLM endpoint" and N1 forbids data leaving the host; a configurable
URL with no guard satisfies neither, and a typo or a copied `.env` would ship
accident narratives to a LAN address. **There is deliberately no opt-out
setting** — an opt-out is how "no data leaves the host" becomes "no data
leaves the host by default".

**The guard is only half of it.** `require_loopback` reasons about the URL;
which socket that URL is dialled over is decided later, by the transport, out
of the process environment. So this module builds the transport too, with
`trust_env=False` and `follow_redirects=False` — see `_build_client`. Without
the first, a machine-wide `HTTP_PROXY` sends a request for `127.0.0.1` to the
proxy host with the guard satisfied and the narrative attached.

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

**H4's two amendments were applied at integration**
(`contracts/amendments/feat-p3-llm-adapter.md`), so the shims they stood in
for are gone:

1. `LlmEndpointError` moved **down to `ra2/domain/llm.py`**, beside
   `EndpointStatus` and the protocol it guards, and is imported from there.
   M17 had put it in `services/errors.py` and documented it as raised here —
   which `ra2/infra/` may not import. It is re-exported from
   `services/errors.py`, so both adapters keep one import site.
2. `domain.llm.Extraction` gained `retry_count`, the field §15.4 always said
   the count is "carried back on" — it had a column, a read model and an API
   field already, and was missing only from the type crossing this seam.

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

**`OllamaEndpointProber` probes a URL nobody has committed to yet.** The two
classes above are bound to one `base_url` for their lifetime, which is right
for them and useless for a settings dialog: the thing an analyst wants tested
is the value they just typed, before it goes anywhere near `.env`. So the
prober takes the URL per call, applies `classify_endpoint` **before** building
a client, and returns a `ProbeResult` for every outcome including the refusals
— a test button that raised would force exactly the toast the design rejects.
It reports a *named cause* rather than one bit, because "unreachable" cannot
tell you whether Ollama is down or the port is wrong, and that distinction is
the whole reason the button exists.

**The catalogue reads Ollama's native `/api/tags`, not `/v1/models`.**
`ModelInfo` carries `digest` and `size_bytes` and `fits_vram` is computed from
the latter (§15.6); OpenAI-compatible `/v1/models` reports neither. The call
goes through the *same* `AsyncOpenAI` instance with an absolute URL, so
there is still exactly one provider client per adapter — which is the whole of
Do-NOT #1.
"""

import time
from typing import Any, Protocol, cast

import httpx2

# **One** `import openai` statement, in the one module permitted to have it —
# and one statement rather than several `from openai import …` lines because
# `tests/test_p3_contract.py::test_openai_is_imported_in_exactly_one_module`
# counts import *statements*, not modules. Everything the adapter needs is
# reached through this name, so the seam is visible at every use site.
import openai

from ra2.domain.llm import (
    ALLOWED_SCHEMES,
    LOOPBACK_HOSTS,
    PROBE_TIMEOUT_S,
    EndpointStatus,
    Extraction,
    LlmEndpointError,
    ModelInfo,
    ProbeCode,
    ProbeResult,
    classify_endpoint,
    require_loopback,
)

__all__ = [
    "ALLOWED_SCHEMES",
    "LOOPBACK_HOSTS",
    "PROBE_TIMEOUT_S",
    "RETRYABLE_STATUS_CODES",
    "LlmEndpointError",
    "OllamaEndpointProber",
    "OllamaLLMClient",
    "OllamaModelCatalog",
    "native_api_url",
    "require_loopback",
]

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


def _reject_environment_reading_client(http_client: httpx2.AsyncClient) -> None:
    """The injected client must be as environment-blind as the built one.

    `http_client` is a seam, not a test-mode branch (Do-NOT #12), and a seam
    that could be handed a looser client than production builds would make
    the guarantee below true only of the path nobody exercises. Checking it
    here means the rule reads "no client this adapter dials through consults
    the environment or follows a redirect", with no "unless somebody passed
    one in" clause — which is the same reason the loopback guard has no
    opt-out.
    """
    if http_client.trust_env:
        raise ValueError(
            "the injected http_client must be built with trust_env=False: "
            "a proxy environment variable would route a loopback URL off this "
            "host (N1, sw-design.md §15.5)"
        )
    if http_client.follow_redirects:
        raise ValueError(
            "the injected http_client must be built with follow_redirects=False: "
            "a 307 from the endpoint would carry the narrative off this host "
            "(N1, sw-design.md §15.5)"
        )


def _build_client(
    *, base_url: str, timeout_s: int, http_client: httpx2.AsyncClient | None
) -> openai.AsyncOpenAI:
    """The one provider client. `max_retries=0` on purpose — see the module
    docstring.

    `http_client` is a seam, not a test-mode branch (Do-NOT #12): it is the
    same shape as `create_app()`'s injectable adapters, and production passes
    nothing. It is how the adapter tests drive a `httpx2.MockTransport` stub
    of the endpoint without a socket, a GPU or anything on port 11434.

    **The transport is built here rather than left to the SDK, and that is the
    second half of the loopback rule.** `require_loopback` reasons about the
    *URL*; the decision of which socket a URL is dialled over is made later,
    by the transport, out of the process environment — so a machine with
    `HTTP_PROXY` or `ALL_PROXY` set and no `NO_PROXY` for localhost sends a
    request for `http://127.0.0.1:11434/v1` to the proxy host, guard passed and
    narrative attached. That is not hypothetical: it is the default on most
    managed estates, and `openai`'s own client is built with `trust_env=True`.
    So:

    - `trust_env=False` — no `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `.netrc`
      or `SSLKEYLOGFILE` is read. The environment cannot move the socket.
    - `follow_redirects=False` — a `307`/`308` preserves the method and the
      body, so whatever answers on `127.0.0.1:11434` could otherwise hand the
      narrative to an off-host URL and `httpx2` would carry it there. A
      redirect from a local model server is a misconfiguration in every case
      that is not an attack, and neither is worth following.

    `openai.DefaultAsyncHttpx2Client` rather than a bare `httpx2.AsyncClient`
    so the SDK's own connection limits and timeouts still apply: the only
    thing this changes is where the transport is allowed to look.
    """
    if http_client is not None:
        _reject_environment_reading_client(http_client)
    return openai.AsyncOpenAI(
        base_url=base_url,
        api_key=_UNUSED_API_KEY,
        timeout=float(timeout_s),
        max_retries=0,
        http_client=http_client
        or openai.DefaultAsyncHttpx2Client(trust_env=False, follow_redirects=False),
    )


def _is_retryable(error: Exception) -> bool:
    """A transport failure or a busy/temporary status. Never a 4xx, and
    **never a timeout**.

    `APITimeoutError` subclasses `APIConnectionError`, so it is tested first
    or it is never tested at all — the ordering `OllamaEndpointProber` already
    depends on, for the same reason.

    A timeout is not retried because the call it would repeat is
    deterministic: `temperature` and `seed` are fixed, the prompt is
    unchanged, so a generation that did not finish inside the bound will not
    finish inside it the second time either. This is `run_service`'s own
    argument for never retrying a parse failure, and it holds here for the
    same reason. Retrying spends `max_retries` more intervals to reach the
    conclusion already in hand, which on a slow model is the difference
    between one bound and three.
    """
    if isinstance(error, openai.APITimeoutError):
        return False
    if isinstance(error, openai.APIConnectionError):
        return True
    if isinstance(error, openai.APIStatusError):
        return error.status_code in RETRYABLE_STATUS_CODES
    return False


def _status_for(error: Exception) -> EndpointStatus:
    """Which endpoint state a failure that has run out of attempts means.

    `TIMED_OUT` says the endpoint accepted the call and did not finish it;
    `UNREACHABLE` says nothing useful answered at all. Two different repairs —
    one is "the model is slower than `RA2_LLM_TIMEOUT_S`", the other is "start
    Ollama" — and a single value for both sends the analyst to the wrong one.
    Ordered like `_is_retryable`, and for the same subclassing reason.
    """
    if isinstance(error, openai.APITimeoutError):
        return EndpointStatus.TIMED_OUT
    return EndpointStatus.UNREACHABLE


def _narrow_effort(effort: str) -> openai.types.shared_params.ReasoningEffort:
    """A validated `str` as the SDK's literal, in the one file that may name it.

    No check here on purpose: `Settings` refuses an unmappable
    `RA2_LLM_REASONING_EFFORT` at construction and `EvaluationService` refuses
    one on the draft, both against `domain.llm.REASONING_EFFORTS`. A third
    check in the adapter would be a second place for the vocabulary to drift —
    what this narrows is a value two layers have already agreed is legal.
    """
    return cast("openai.types.shared_params.ReasoningEffort", effort)


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
        reasoning_effort: str = "none",
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        # First statement in the constructor, before the SDK client exists:
        # nothing in this object can open a socket until the URL has passed.
        require_loopback(base_url)
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._max_retries = max(0, max_retries)
        # **The process default**, used by any call that does not name its
        # own: `RA2_LLM_REASONING_EFFORT`, and what a run queued before the
        # effort became a per-evaluation input still asks with. Since that
        # change `extract` takes the value per call, because an evaluation
        # pins it and two runs in one process can differ (amendment:
        # feat/evaluation-view-improvements).
        #
        # Taken as `str` and narrowed **here**, not at the call site: the SDK's
        # literal is `openai`'s vocabulary, and Do-NOT #1 puts that vocabulary
        # inside this file. `Settings` has already refused anything Ollama
        # cannot map (`REASONING_EFFORTS`), so this narrows a validated value
        # rather than asserting a new one.
        self._reasoning_effort = _narrow_effort(reasoning_effort)
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
        reasoning_effort: str | None = None,
    ) -> Extraction[T]:
        """One call per (record, model), covering all configured features.

        `text` is the already-resolved prompt; `schema` is the Pydantic model
        `domain.extraction.build_output_schema` built for this feature set,
        sent as a JSON Schema for constrained decoding.

        Latency and the **real** token counts are populated from the
        response. A response that does not parse is still returned, with
        `parse_ok=False` and `raw_output_text` verbatim — the caller records
        it and the run continues.

        Raises `LlmEndpointError` when the endpoint will not answer within the
        bound — `TIMED_OUT` if it accepted the call and did not finish it,
        `UNREACHABLE` otherwise. That is the one outcome that must *not*
        become a row: a record whose attempts were exhausted leaves the hole
        in the middle of a run that the resume query exists to find
        (sw-design.md §15.3).

        A timeout exhausts its attempts **immediately**: see `_is_retryable`
        for why repeating a fixed-seed call that already overran is spending
        the bound to re-learn what is known.
        """
        response_format = _response_format(schema)
        # The run's own effort when it has one, the constructed default
        # otherwise. Narrowed here for the same reason the constructor
        # narrows: the SDK's literal does not leave this file.
        effort = (
            self._reasoning_effort if reasoning_effort is None else _narrow_effort(reasoning_effort)
        )
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
                    # Sent on every call, including when it is the model's own
                    # default: a run's provenance says which effort it used, and
                    # a parameter that is sometimes omitted makes that a claim
                    # about the model's build rather than about this call.
                    reasoning_effort=effort,
                )
            except (openai.APIConnectionError, openai.APIStatusError) as exc:
                if retries >= self._max_retries or not _is_retryable(exc):
                    # `retries + 1`: the bound counts *retries*, so the calls
                    # actually made are one more. A non-retryable failure gives
                    # up on the first, and reporting `max_retries + 1` for it
                    # would overstate what it cost.
                    raise LlmEndpointError(
                        self._base_url, _status_for(exc), attempts=retries + 1
                    ) from exc
                retries += 1
                continue
            break

        latency_ms = int((time.perf_counter() - started) * 1000)
        raw_output_text = _first_content(completion)
        prompt_tokens, completion_tokens = _token_counts(completion)
        parsed, parse_error = _parse(schema, raw_output_text)
        return Extraction[T](
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


class OllamaEndpointProber:
    """`domain.llm.EndpointProber` — "is this URL an Ollama, and if not, why?"

    Separate from `OllamaModelCatalog` because the question is different. The
    catalogue asks about the endpoint the app was *configured* with and
    answers in one bit, which is all the Models card renders. This answers
    about an endpoint the user has merely **typed** into the settings dialog,
    and answers with a named cause — `CONNECTION_REFUSED` and `HTTP_ERROR`
    send an analyst to two completely different fixes, and collapsing them to
    "unreachable" is what made the endpoint painful to set up in the first
    place.

    **Never raises.** Every outcome, refusals included, is a `ProbeResult`.

    Holds no `base_url` and no settings, so `create_app()` can default it with
    nothing to hand it: the URL and the timeout both arrive per call.
    """

    def __init__(self, *, http_client: httpx2.AsyncClient | None = None) -> None:
        # The same injection seam the other two classes carry, for the same
        # reason: it is how the tests drive a `httpx2.MockTransport` stub
        # without a socket, and production passes nothing (Do-NOT #12).
        self._http_client = http_client

    async def probe(self, base_url: str, *, timeout_s: int) -> ProbeResult:
        """Ask `base_url` for its model list, with a short bound.

        The guard runs **first**, and a refusal returns before any client
        exists — for a URL pointing off this host, the absence of a packet is
        the feature (N1). Everything after that is a real round trip, mapped
        to the code that names what went wrong.
        """
        refusal = classify_endpoint(base_url)
        if refusal is not None:
            return ProbeResult(code=refusal)

        client = _build_client(
            base_url=base_url,
            timeout_s=min(timeout_s, PROBE_TIMEOUT_S),
            http_client=self._http_client,
        )
        started = time.perf_counter()
        try:
            payload = await client.get(
                native_api_url(base_url, _NATIVE_TAGS_PATH), cast_to=_OllamaTags
            )
        except openai.APITimeoutError as exc:
            # Checked before `APIConnectionError`, which it subclasses: a host
            # that accepted the connection and went quiet is a different fix
            # from one that was never there.
            return ProbeResult(code=ProbeCode.TIMEOUT, detail=_cause(exc))
        except openai.APIConnectionError as exc:
            return ProbeResult(code=ProbeCode.CONNECTION_REFUSED, detail=_cause(exc))
        except openai.APIStatusError as exc:
            return ProbeResult(
                code=ProbeCode.HTTP_ERROR,
                detail=_cause(exc),
                http_status=exc.status_code,
                latency_ms=_elapsed_ms(started),
            )
        except (ValueError, TypeError) as exc:
            # Something answered and it was not `/api/tags`. A web server on
            # the right port, or `/v1` pointed at something else entirely.
            return ProbeResult(
                code=ProbeCode.BAD_PAYLOAD,
                detail=_cause(exc),
                latency_ms=_elapsed_ms(started),
            )

        # The SDK's response parser is **deliberately lenient** — that is what
        # keeps the catalogue tolerant of fields Ollama adds later — so it will
        # happily hand back an `_OllamaTags` whose `models` is a string that
        # some unrelated web server put there. A probe cannot lean on it: the
        # difference between "Ollama answered" and "something answered" is the
        # entire question being asked, and a lenient parse reports the second
        # as the first. So the shape is checked here, explicitly.
        if not isinstance(payload.models, list):
            return ProbeResult(
                code=ProbeCode.BAD_PAYLOAD,
                detail=f"no model list in the response (models: {type(payload.models).__name__})",
                latency_ms=_elapsed_ms(started),
            )
        return ProbeResult(
            code=ProbeCode.OK,
            latency_ms=_elapsed_ms(started),
            model_count=len(payload.models),
        )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


#: How far down a `__cause__` chain `_cause` will walk. Three is enough for
#: the deepest real chain (`APIConnectionError` -> `httpx2.ConnectError` ->
#: `OSError`) with room to spare, and a bound means a self-referential chain
#: cannot spin.
_MAX_CAUSE_DEPTH = 5


def _cause(error: Exception) -> str:
    """The OS's or the provider's **verbatim** words, for the probe's second line.

    Walks to the **deepest** cause, not the first. The chain for a refused
    connection is `APIConnectionError` ("Connection error.") ->
    `httpx2.ConnectError` ("All connection attempts failed") ->
    `ConnectionRefusedError` ("[Errno 111] Connection refused"), and only the
    last of those names what actually happened. Each wrapper is more generic
    than the thing it wraps, so the bottom of the chain is the line worth
    showing.

    Never rendered as the analyst's explanation — that comes from the code
    alone, through `PROBE_WORDS` — only underneath it.
    """
    deepest: BaseException = error
    seen = {id(error)}
    for _ in range(_MAX_CAUSE_DEPTH):
        cause = deepest.__cause__ or deepest.__context__
        if cause is None or id(cause) in seen or not str(cause).strip():
            break
        seen.add(id(cause))
        deepest = cause
    return str(deepest).strip() or type(error).__name__


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
