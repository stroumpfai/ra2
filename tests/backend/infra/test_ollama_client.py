"""The LLM adapter — the one place `openai` exists (sw-design.md §15.5).

**Never a live Ollama.** The whole suite must pass on a machine with no GPU
and nothing listening on 11434 (plan-phase-3.md §11), so the endpoint is a
`httpx2.MockTransport` handed to the SDK as its `http_client`. `openai` 3.x is
built on **`httpx2`**, not `httpx`, which is why `respx` is not the tool here
(P3-D10). No socket is opened by anything in this file.

The loopback guard gets five host forms of its own because, from this branch
on, one guard in one constructor is the whole of N1 (plan-phase-3.md R4).
"""

import ast
import json
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from pydantic import BaseModel

from ra2.domain.llm import (
    EndpointProber,
    EndpointStatus,
    Extraction,
    LLMClient,
    ModelCatalog,
    ModelInfo,
    ProbeCode,
)
from ra2.infra.config import Settings

# The private one, on purpose: the prober builds its client per call, so the
# only way to inspect the transport it *would* dial with is to ask for it.
from ra2.infra.ollama_client import (
    LOOPBACK_HOSTS,
    PROBE_TIMEOUT_S,
    LlmEndpointError,
    OllamaEndpointProber,
    OllamaLLMClient,
    OllamaModelCatalog,
    _build_client,
    native_api_url,
    require_loopback,
)

pytestmark = pytest.mark.backend

REPO_ROOT = Path(__file__).resolve().parents[3]

LOOPBACK_URL = "http://127.0.0.1:11434/v1"

#: Two of the design's fixture models, as Ollama's native `/api/tags` reports
#: them: a name, a digest and a size. `/v1/models` reports none of the last
#: two, which is why the catalogue reads this endpoint (see the adapter's
#: module docstring).
TAGS_BODY = {
    "models": [
        {
            "name": "llama3.1:8b-instruct-q8_0",
            "model": "llama3.1:8b-instruct-q8_0",
            "digest": "8fa1c3d0",
            "size": 8_500_000_000,
        },
        {
            "name": "llama3.3:70b-instruct-q4_K_M",
            "model": "llama3.3:70b-instruct-q4_K_M",
            "digest": "7e55aa12",
            "size": 42_500_000_000,
        },
    ]
}


class Output(BaseModel):
    """Stands in for what `domain.extraction.build_output_schema` builds."""

    value: str
    present: bool
    evidence: str | None = None


def completion_body(
    content: str, *, prompt_tokens: int = 1180, completion_tokens: int = 94
) -> dict[str, Any]:
    """One OpenAI-compatible chat completion, the shape Ollama's `/v1` returns."""
    return {
        "id": "chatcmpl-stub",
        "object": "chat.completion",
        "created": 1_756_800_000,
        "model": "llama3.1:8b-instruct-q8_0",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


VALID_OUTPUT = json.dumps({"value": "A02", "present": True, "evidence": "es regnete"})

#: One outcome the stub can produce: a `(status, body)` pair, or an exception
#: the transport raises — a refused connection, a timeout.
Outcome = tuple[int, dict[str, Any]] | BaseException


class StubOllama:
    """A local stand-in for the endpoint. **No socket, no live Ollama.**

    `chat` outcomes are consumed in order and the last one repeats, so
    `[(503, …), (503, …), (200, …)]` is "fails twice then answers" and
    `[(503, …)]` is "always fails".
    """

    def __init__(
        self,
        *,
        chat: Sequence[Outcome] | None = None,
        tags: Outcome | None = None,
    ) -> None:
        self._chat: deque[Outcome] = deque(chat or [(200, completion_body(VALID_OUTPUT))])
        self._tags: Outcome = tags if tags is not None else (200, TAGS_BODY)
        self.chat_requests: list[dict[str, Any]] = []
        self.tags_urls: list[str] = []

    def _next_chat(self) -> Outcome:
        outcome = self._chat[0]
        if len(self._chat) > 1:
            self._chat.popleft()
        return outcome

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/api/tags"):
            self.tags_urls.append(str(request.url))
            outcome = self._tags
        else:
            self.chat_requests.append(json.loads(request.read().decode("utf-8")))
            outcome = self._next_chat()
        if isinstance(outcome, BaseException):
            raise outcome
        status, body = outcome
        return httpx2.Response(status, json=body)

    def http_client(self) -> httpx2.AsyncClient:
        return env_blind_client(httpx2.MockTransport(self.handle))


def env_blind_client(transport: httpx2.MockTransport) -> httpx2.AsyncClient:
    """A stub client built the way `_build_client` builds the real one.

    `trust_env=False` and `follow_redirects=False` are not decoration here:
    the adapter **refuses** an injected client that has either of them, so a
    fixture that left the defaults on would fail at construction. That is the
    point of checking the seam — the stub cannot be looser than production,
    which is what keeps the guarantee true of the path the tests exercise.
    """
    return httpx2.AsyncClient(transport=transport, trust_env=False, follow_redirects=False)


def refusing_transport() -> httpx2.AsyncClient:
    """A transport that fails the test if it is ever asked for anything.

    The guard has to refuse **before a socket is opened**; this is what proves
    "before", rather than merely "instead of an answer".
    """

    def handle(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"the guard let a request through to {request.url}")

    return env_blind_client(httpx2.MockTransport(handle))


@pytest.fixture
def stub() -> StubOllama:
    return StubOllama()


# ===========================================================================
# The loopback guard — N1, and there is deliberately no opt-out
# ===========================================================================

#: The three spellings of "this host", and nothing else. `LOOPBACK_HOSTS` is
#: the whole of what N1 permits.
ACCEPTED_HOSTS = [
    pytest.param("http://localhost:11434/v1", id="localhost"),
    pytest.param("http://127.0.0.1:11434/v1", id="127.0.0.1"),
    pytest.param("http://[::1]:11434/v1", id="::1"),
]

#: A LAN address and a public host name. Both are what a typo or a copied
#: `.env` produces, and both would put accident narratives on a wire.
REFUSED_HOSTS = [
    pytest.param("http://192.168.1.9:11434/v1", id="lan-address"),
    pytest.param("https://api.openai.com/v1", id="public-host-name"),
]


@pytest.mark.parametrize("endpoint", ACCEPTED_HOSTS)
def test_the_loopback_guard_accepts_this_host(endpoint: str) -> None:
    require_loopback(endpoint)
    client = OllamaLLMClient(base_url=endpoint, http_client=refusing_transport())
    assert client.base_url == endpoint


@pytest.mark.parametrize("endpoint", REFUSED_HOSTS)
def test_the_loopback_guard_refuses_anything_else(endpoint: str) -> None:
    with pytest.raises(LlmEndpointError) as excinfo:
        OllamaLLMClient(base_url=endpoint, http_client=refusing_transport())

    assert excinfo.value.status is EndpointStatus.REFUSED_NOT_LOOPBACK
    assert excinfo.value.base_url == endpoint


@pytest.mark.parametrize("endpoint", ACCEPTED_HOSTS)
def test_the_catalogue_holds_the_same_guard_and_accepts_this_host(endpoint: str) -> None:
    catalog = OllamaModelCatalog(base_url=endpoint, http_client=refusing_transport())
    assert catalog.base_url == endpoint


@pytest.mark.parametrize("endpoint", REFUSED_HOSTS)
def test_the_catalogue_holds_the_same_guard_and_refuses_anything_else(endpoint: str) -> None:
    """The catalogue opens a socket too. A guard on only one of the two
    classes would be a hole in the one thing standing between this codebase
    and N1."""
    with pytest.raises(LlmEndpointError) as excinfo:
        OllamaModelCatalog(base_url=endpoint, http_client=refusing_transport())

    assert excinfo.value.status is EndpointStatus.REFUSED_NOT_LOOPBACK


@pytest.mark.parametrize(
    "endpoint",
    [
        pytest.param("http://127.0.0.1.evil.example/v1", id="loopback-as-a-prefix"),
        pytest.param("http://localhost.attacker.test/v1", id="localhost-as-a-prefix"),
        pytest.param("http://10.0.0.4:11434/v1", id="private-range"),
        pytest.param("http://ollama.internal:11434/v1", id="internal-name"),
        pytest.param("127.0.0.1:11434/v1", id="no-scheme"),
        pytest.param("file:///etc/passwd", id="not-http"),
        pytest.param("", id="empty"),
        pytest.param("http://127.0.0.1:notaport/v1", id="malformed-port"),
    ],
)
def test_the_guard_refuses_everything_that_is_not_plainly_loopback(endpoint: str) -> None:
    """The host is compared **literally**, never resolved. A name that
    resolves to loopback today resolves wherever its owner points it
    tomorrow."""
    with pytest.raises(LlmEndpointError) as excinfo:
        require_loopback(endpoint)

    assert excinfo.value.status is EndpointStatus.REFUSED_NOT_LOOPBACK


def test_the_guard_runs_before_the_provider_client_exists() -> None:
    """`__init__` raises before any attribute is set, so a refused client
    cannot be half-constructed and used anyway."""
    with pytest.raises(LlmEndpointError):
        OllamaLLMClient(base_url="http://192.168.1.9:11434/v1")


def test_the_settings_default_passes_its_own_guard() -> None:
    """`RA2_LLM_BASE_URL`'s default has to be one the guard accepts, or the
    app does not start on a clean install."""
    require_loopback(Settings(_env_file=None).llm_base_url)


def test_loopback_hosts_is_the_whole_of_what_is_permitted() -> None:
    assert set(LOOPBACK_HOSTS) == {"127.0.0.1", "::1", "[::1]", "localhost"}


def test_there_is_deliberately_no_opt_out_anywhere() -> None:
    """sw-design.md §15.5: "an opt-out is how 'no data leaves the host'
    becomes 'no data leaves the host by default'". Asserted on the *shape* of
    the constructors and of `Settings`, so adding one is a red test rather
    than a review comment someone has to notice."""
    import inspect

    smells = ("allow", "insecure", "unsafe", "remote", "skip", "disable", "bypass", "override")
    for factory in (OllamaLLMClient.__init__, OllamaModelCatalog.__init__):
        for name in inspect.signature(factory).parameters:
            assert not any(smell in name.lower() for smell in smells), (
                f"{factory.__qualname__} takes '{name}' — the guard has no opt-out"
            )
    for name in Settings.model_fields:
        assert "loopback" not in name.lower(), f"Settings.{name} looks like an opt-out"


def test_the_error_carries_the_endpoint_and_names_the_status() -> None:
    with pytest.raises(LlmEndpointError) as excinfo:
        require_loopback("http://192.168.1.9:11434/v1")

    assert "192.168.1.9" in str(excinfo.value)
    assert EndpointStatus.REFUSED_NOT_LOOPBACK.value in str(excinfo.value)


# ===========================================================================
# The environment cannot move the socket — the other half of the loopback rule
# ===========================================================================
#
# `require_loopback` inspects the **URL**. Which socket that URL is dialled
# over is decided later, by the transport, out of the process environment —
# and `openai`'s own client is built with `trust_env=True`, so on a machine
# with a machine-wide `HTTP_PROXY` and no `NO_PROXY` for localhost, a request
# for `http://127.0.0.1:11434/v1` went to the proxy host with the guard
# satisfied and the narrative attached. These assert on the transport actually
# chosen for the loopback URL, not merely on the flag, because the transport is
# what the defect was.

#: Every spelling of "send it somewhere else" that `httpx2` reads from the
#: environment. `NO_PROXY` is set to something that does *not* cover localhost
#: on purpose: the realistic managed-estate configuration is one where an
#: exemption list exists and is wrong, not one where none exists.
PROXY_ENVIRONMENT = {
    "HTTP_PROXY": "http://proxy.corp.example:3128",
    "HTTPS_PROXY": "http://proxy.corp.example:3128",
    "ALL_PROXY": "http://proxy.corp.example:3128",
    "NO_PROXY": "example.com",
}


@pytest.fixture
def proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A workstation behind a corporate proxy, in both spellings `httpx2`
    accepts."""
    for name, value in PROXY_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
        monkeypatch.setenv(name.lower(), value)


def dials_through_a_proxy(http_client: httpx2.AsyncClient) -> bool:
    """Whether a request for the loopback endpoint would leave through a proxy.

    `_transport_for_url` is the same lookup a real request performs, so this
    reads the decision itself rather than the flag that informs it. Both the
    pool's class and its proxy attributes are consulted: `httpcore2` answers a
    proxied URL with an `AsyncHTTPProxy` holding `_proxy_url`, and checking
    only one of the two would pass vacuously the day the other is renamed —
    which is exactly how this defect stayed invisible.
    """
    transport = http_client._transport_for_url(httpx2.URL(f"{LOOPBACK_URL}/chat/completions"))
    pool = getattr(transport, "_pool", transport)
    if "proxy" in type(pool).__name__.lower():
        return True
    return any(getattr(pool, name, None) for name in ("_proxy", "_proxy_url", "_proxy_headers"))


def transport_of(adapter: Any) -> httpx2.AsyncClient:
    """The `httpx2` client the SDK ended up holding for this adapter.

    Two underscores deep on purpose: the question is not what the adapter was
    configured with but what will actually carry the narrative.
    """
    return cast("httpx2.AsyncClient", adapter._client._client)


#: The two adapters built the way `create_app()` builds them — **no
#: `http_client` injected**, which is the one path the rest of this file never
#: exercises and the only one that had the defect.
PRODUCTION_ADAPTERS = [
    pytest.param(lambda: OllamaLLMClient(base_url=LOOPBACK_URL), id="llm-client"),
    pytest.param(lambda: OllamaModelCatalog(base_url=LOOPBACK_URL), id="model-catalogue"),
]


def test_the_proxy_check_can_tell_the_difference(proxy_environment: None) -> None:
    """Guards the guard.

    Every assertion below is a negative one, and a negative assertion that
    cannot fail is worse than no assertion at all. This is the positive
    control: under the same environment, a client that *does* read it dials
    the loopback endpoint through the proxy.
    """
    assert dials_through_a_proxy(httpx2.AsyncClient(trust_env=True)) is True


@pytest.mark.parametrize("build", PRODUCTION_ADAPTERS)
def test_a_proxy_environment_cannot_redirect_the_loopback_socket(
    proxy_environment: None, build: Any
) -> None:
    """The A1 regression itself."""
    assert dials_through_a_proxy(transport_of(build())) is False


def test_a_proxy_environment_cannot_redirect_the_probers_socket(
    proxy_environment: None,
) -> None:
    """The prober builds its client per call, so it needs its own check: it
    dials whatever an analyst typed into the settings dialog, which is the
    first request a freshly configured machine makes."""
    assert dials_through_a_proxy(probe_transport_of(OllamaEndpointProber())) is False


@pytest.mark.parametrize("build", PRODUCTION_ADAPTERS)
def test_the_production_client_reads_nothing_from_the_environment(
    proxy_environment: None, build: Any
) -> None:
    """`trust_env` covers `.netrc` and `SSLKEYLOGFILE` as well as the proxy
    variables. None of them has any business influencing a loopback call."""
    http_client = transport_of(build())

    assert http_client.trust_env is False
    assert http_client._mounts == {}


@pytest.mark.parametrize("build", PRODUCTION_ADAPTERS)
def test_the_production_client_does_not_follow_a_redirect(build: Any) -> None:
    """A `307`/`308` preserves the method and the body, so whatever answers on
    `127.0.0.1:11434` could otherwise hand the narrative to an off-host URL and
    `httpx2` would carry it there — past the guard, which only ever saw the
    first URL."""
    assert transport_of(build()).follow_redirects is False


def test_the_prober_is_built_the_same_way(proxy_environment: None) -> None:
    http_client = probe_transport_of(OllamaEndpointProber())

    assert http_client.trust_env is False
    assert http_client.follow_redirects is False


@pytest.mark.parametrize(
    ("trust_env", "follow_redirects", "smell"),
    [
        pytest.param(True, False, "trust_env", id="trust_env"),
        pytest.param(False, True, "follow_redirects", id="follow_redirects"),
    ],
)
def test_an_injected_client_that_reads_the_environment_is_refused(
    *, trust_env: bool, follow_redirects: bool, smell: str
) -> None:
    """The seam cannot be looser than the path it stands in for.

    `http_client` exists so the tests can drive a `MockTransport` (Do-NOT
    #12); a seam that accepted a client production would never build would
    make the guarantee true only of the code nobody runs. This is also what
    makes `env_blind_client` above load-bearing rather than tidy.
    """

    def handle(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"nothing should reach {request.url}")

    loose = httpx2.AsyncClient(
        transport=httpx2.MockTransport(handle),
        trust_env=trust_env,
        follow_redirects=follow_redirects,
    )

    with pytest.raises(ValueError, match=smell):
        OllamaLLMClient(base_url=LOOPBACK_URL, http_client=loose)


def probe_transport_of(prober: OllamaEndpointProber) -> httpx2.AsyncClient:
    """The transport the prober would dial the loopback URL with.

    The prober holds no `base_url` and no client — it builds one per call,
    after `classify_endpoint` — so there is nothing to inspect until one is
    asked for. This asks for exactly the client `probe()` would construct.
    """
    return _build_client(
        base_url=LOOPBACK_URL,
        timeout_s=PROBE_TIMEOUT_S,
        http_client=prober._http_client,
    )._client


# ===========================================================================
# The protocols are satisfied
# ===========================================================================


def test_the_adapters_satisfy_the_frozen_protocols() -> None:
    client = OllamaLLMClient(base_url=LOOPBACK_URL, http_client=refusing_transport())
    catalog = OllamaModelCatalog(base_url=LOOPBACK_URL, http_client=refusing_transport())

    assert isinstance(client, LLMClient)
    assert isinstance(catalog, ModelCatalog)


# ===========================================================================
# extract — the prompt, the schema, the counts
# ===========================================================================


async def test_extract_sends_the_prompt_and_the_schema_for_constrained_decoding(
    stub: StubOllama,
) -> None:
    client = OllamaLLMClient(base_url=LOOPBACK_URL, http_client=stub.http_client())

    await client.extract(
        "resolved prompt", Output, "llama3.1:8b-instruct-q8_0", temperature=0.0, seed=42
    )

    (sent,) = stub.chat_requests
    assert sent["model"] == "llama3.1:8b-instruct-q8_0"
    assert sent["messages"] == [{"role": "user", "content": "resolved prompt"}]
    assert sent["temperature"] == 0.0
    assert sent["seed"] == 42
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["schema"] == Output.model_json_schema()


async def test_extract_asks_the_same_question_twice(stub: StubOllama) -> None:
    """Key order is stable across calls — two runs must ask the same question
    (sw-design.md §15.3)."""
    client = OllamaLLMClient(base_url=LOOPBACK_URL, http_client=stub.http_client())

    await client.extract("a", Output, "m", temperature=0.0, seed=1)
    await client.extract("b", Output, "m", temperature=0.0, seed=1)

    first, second = stub.chat_requests
    assert json.dumps(first["response_format"]) == json.dumps(second["response_format"])


async def test_extract_returns_the_parsed_value_and_the_real_token_counts() -> None:
    """The **real** counts come back from the endpoint; `estimate_tokens` is
    the preview's estimate and this is the number that has to be right."""
    stub = StubOllama(
        chat=[(200, completion_body(VALID_OUTPUT, prompt_tokens=1180, completion_tokens=94))]
    )
    client = OllamaLLMClient(base_url=LOOPBACK_URL, http_client=stub.http_client())

    result = await client.extract("prompt", Output, "m", temperature=0.0, seed=1)

    assert result.parse_ok is True
    assert result.parse_error is None
    assert result.value == Output(value="A02", present=True, evidence="es regnete")
    assert result.raw_output_text == VALID_OUTPUT
    assert result.prompt_tokens == 1180
    assert result.completion_tokens == 94
    assert result.latency_ms is not None and result.latency_ms >= 0


async def test_extract_records_a_parse_failure_verbatim_and_keeps_going() -> None:
    """A parse failure is a datum, not an exception (mvp-spec.md §10.4): the
    raw text is stored verbatim and the caller records a row."""
    prose = 'Sure! Here is the JSON: {"value": '
    stub = StubOllama(chat=[(200, completion_body(prose))])
    client = OllamaLLMClient(base_url=LOOPBACK_URL, http_client=stub.http_client())

    result = await client.extract("prompt", Output, "m", temperature=0.0, seed=1)

    assert result.parse_ok is False
    assert result.parse_error
    assert result.value is None
    assert result.raw_output_text == prose


async def test_a_parse_failure_is_never_retried() -> None:
    """Temperature and seed are fixed, so a retry returns the same bytes. A
    retry-until-quiet loop is exactly what §10.4 forbids."""
    stub = StubOllama(chat=[(200, completion_body("not json"))])
    client = OllamaLLMClient(base_url=LOOPBACK_URL, max_retries=3, http_client=stub.http_client())

    result = await client.extract("prompt", Output, "m", temperature=0.0, seed=1)

    assert len(stub.chat_requests) == 1
    assert isinstance(result, Extraction)
    assert result.retry_count == 0


async def test_an_empty_choice_list_is_an_empty_output_not_a_crash() -> None:
    body = completion_body(VALID_OUTPUT)
    body["choices"] = []
    stub = StubOllama(chat=[(200, body)])
    client = OllamaLLMClient(base_url=LOOPBACK_URL, http_client=stub.http_client())

    result = await client.extract("prompt", Output, "m", temperature=0.0, seed=1)

    assert result.raw_output_text == ""
    assert result.parse_ok is False


# ===========================================================================
# Retries — bounded, counted, and visible on the Extraction
# ===========================================================================


async def test_the_retry_count_reaches_the_extraction() -> None:
    """sw-design.md §15.4: "the count carried back on the `Extraction`"."""
    stub = StubOllama(
        chat=[
            (503, {"error": "model is loading"}),
            (503, {"error": "model is loading"}),
            (200, completion_body(VALID_OUTPUT)),
        ]
    )
    client = OllamaLLMClient(base_url=LOOPBACK_URL, max_retries=2, http_client=stub.http_client())

    result = await client.extract("prompt", Output, "m", temperature=0.0, seed=1)

    assert len(stub.chat_requests) == 3
    assert result.parse_ok is True
    assert isinstance(result, Extraction)
    assert isinstance(result, Extraction)
    assert result.retry_count == 2


async def test_a_call_that_needs_no_retry_reports_zero() -> None:
    stub = StubOllama()
    client = OllamaLLMClient(base_url=LOOPBACK_URL, max_retries=2, http_client=stub.http_client())

    result = await client.extract("prompt", Output, "m", temperature=0.0, seed=1)

    assert isinstance(result, Extraction)
    assert result.retry_count == 0


@pytest.mark.parametrize("max_retries", [0, 1, 2, 5])
async def test_the_retry_bound_is_respected(max_retries: int) -> None:
    """`RA2_LLM_MAX_RETRIES` counts **retries**, so the endpoint is called at
    most `max_retries + 1` times — never a retry-until-quiet loop."""
    stub = StubOllama(chat=[(503, {"error": "busy"})])
    client = OllamaLLMClient(
        base_url=LOOPBACK_URL, max_retries=max_retries, http_client=stub.http_client()
    )

    with pytest.raises(LlmEndpointError) as excinfo:
        await client.extract("prompt", Output, "m", temperature=0.0, seed=1)

    assert len(stub.chat_requests) == max_retries + 1
    assert excinfo.value.status is EndpointStatus.UNREACHABLE


async def test_the_sdk_adds_no_retries_of_its_own() -> None:
    """The SDK retries by default. Layered under ours the two would multiply,
    and the SDK's are invisible — §10.4 asks for bounded, counted **and
    visible**."""
    stub = StubOllama(chat=[(503, {"error": "busy"})])
    client = OllamaLLMClient(base_url=LOOPBACK_URL, max_retries=0, http_client=stub.http_client())

    with pytest.raises(LlmEndpointError):
        await client.extract("prompt", Output, "m", temperature=0.0, seed=1)

    assert len(stub.chat_requests) == 1
    assert client.max_retries == 0


async def test_a_refused_connection_is_retried_then_raised() -> None:
    """Nothing on 11434 is the everyday case, and it must not surface as an
    `openai` exception in the service layer."""
    stub = StubOllama(
        chat=[httpx2.ConnectError("connection refused", request=httpx2.Request("POST", "/"))]
    )
    client = OllamaLLMClient(base_url=LOOPBACK_URL, max_retries=1, http_client=stub.http_client())

    with pytest.raises(LlmEndpointError) as excinfo:
        await client.extract("prompt", Output, "m", temperature=0.0, seed=1)

    assert len(stub.chat_requests) == 2
    assert excinfo.value.base_url == LOOPBACK_URL
    assert excinfo.value.status is EndpointStatus.UNREACHABLE


async def test_a_timeout_is_raised_on_the_first_attempt_and_never_retried() -> None:
    """`temperature` and `seed` are fixed, so a generation that overran the
    bound overruns it again. Retrying spends `max_retries` more whole
    intervals to reach the conclusion already in hand.

    This was measured, not reasoned into: at the old 120 s default a 9.7 B
    thinking model took 126-136 s for two features over one sentence, so every
    call timed out — three times per record, three records deep, before a run
    gave up twenty minutes later.
    """
    stub = StubOllama(chat=[httpx2.ReadTimeout("timed out", request=httpx2.Request("POST", "/"))])
    client = OllamaLLMClient(base_url=LOOPBACK_URL, max_retries=3, http_client=stub.http_client())

    with pytest.raises(LlmEndpointError) as excinfo:
        await client.extract("prompt", Output, "m", temperature=0.0, seed=1)

    assert len(stub.chat_requests) == 1
    assert excinfo.value.status is EndpointStatus.TIMED_OUT


async def test_a_timeout_and_a_refusal_are_different_answers() -> None:
    """One means the model is slower than `RA2_LLM_TIMEOUT_S`; the other means
    start Ollama. Collapsing them is what sent an analyst to look at the port
    and the firewall while the endpoint was answering fine.

    `OllamaEndpointProber` has told the two apart since P3-D19
    (`ProbeCode.TIMEOUT`); the generation path had no value to say it with.
    The positive control is in the same assertion: the refusal must still be
    retried to its bound, so this cannot pass by making everything terminal.
    """
    timing_out = StubOllama(
        chat=[httpx2.ReadTimeout("timed out", request=httpx2.Request("POST", "/"))]
    )
    refusing = StubOllama(
        chat=[httpx2.ConnectError("connection refused", request=httpx2.Request("POST", "/"))]
    )

    statuses = []
    for stub in (timing_out, refusing):
        client = OllamaLLMClient(
            base_url=LOOPBACK_URL, max_retries=2, http_client=stub.http_client()
        )
        with pytest.raises(LlmEndpointError) as excinfo:
            await client.extract("prompt", Output, "m", temperature=0.0, seed=1)
        statuses.append(excinfo.value.status)

    assert statuses == [EndpointStatus.TIMED_OUT, EndpointStatus.UNREACHABLE]
    assert len(timing_out.chat_requests) == 1
    assert len(refusing.chat_requests) == 3


async def test_a_4xx_is_not_retried() -> None:
    """A wrong model name does not become right on the second attempt, and
    retrying it burns the bound a genuinely busy endpoint needs."""
    stub = StubOllama(chat=[(404, {"error": "model 'nope' not found"})])
    client = OllamaLLMClient(base_url=LOOPBACK_URL, max_retries=3, http_client=stub.http_client())

    with pytest.raises(LlmEndpointError):
        await client.extract("prompt", Output, "nope", temperature=0.0, seed=1)

    assert len(stub.chat_requests) == 1


async def test_an_exhausted_run_raises_rather_than_returning_a_row() -> None:
    """That is the difference the worker acts on: a parse failure writes a
    row, an endpoint failure leaves the hole the resume query finds
    (sw-design.md §15.3)."""
    stub = StubOllama(chat=[(500, {"error": "boom"})])
    client = OllamaLLMClient(base_url=LOOPBACK_URL, max_retries=0, http_client=stub.http_client())

    with pytest.raises(LlmEndpointError):
        await client.extract("prompt", Output, "m", temperature=0.0, seed=1)


# ===========================================================================
# The catalogue — unreachable is a state, not an error
# ===========================================================================


async def test_models_reports_tag_digest_and_size(stub: StubOllama) -> None:
    catalog = OllamaModelCatalog(base_url=LOOPBACK_URL, http_client=stub.http_client())

    models = await catalog.models()

    assert models == (
        ModelInfo(tag="llama3.1:8b-instruct-q8_0", digest="8fa1c3d0", size_bytes=8_500_000_000),
        ModelInfo(tag="llama3.3:70b-instruct-q4_K_M", digest="7e55aa12", size_bytes=42_500_000_000),
    )


async def test_the_catalogue_reads_the_native_tags_endpoint(stub: StubOllama) -> None:
    """`/v1/models` reports neither a digest nor a size, and `fits_vram` is
    computed from the size (sw-design.md §15.6)."""
    catalog = OllamaModelCatalog(base_url=LOOPBACK_URL, http_client=stub.http_client())

    await catalog.models()

    assert stub.tags_urls == ["http://127.0.0.1:11434/api/tags"]


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/api/tags"),
        ("http://127.0.0.1:11434/v1/", "http://127.0.0.1:11434/api/tags"),
        ("http://localhost:11434", "http://localhost:11434/api/tags"),
    ],
)
def test_native_api_url_derives_the_root(endpoint: str, expected: str) -> None:
    assert native_api_url(endpoint, "/api/tags") == expected


async def test_reachable_says_reachable_when_the_endpoint_answers(stub: StubOllama) -> None:
    catalog = OllamaModelCatalog(base_url=LOOPBACK_URL, http_client=stub.http_client())

    assert await catalog.reachable() is EndpointStatus.REACHABLE


async def test_an_unreachable_endpoint_is_a_state_not_an_exception() -> None:
    """sw-design.md §15.5: the service hands the view an empty model list and
    a reason. Never a toast, never a 502."""
    stub = StubOllama(tags=httpx2.ConnectError("refused", request=httpx2.Request("GET", "/")))
    catalog = OllamaModelCatalog(base_url=LOOPBACK_URL, http_client=stub.http_client())

    assert await catalog.reachable() is EndpointStatus.UNREACHABLE
    assert await catalog.models() == ()


async def test_a_500_from_the_endpoint_is_unreachable_too() -> None:
    stub = StubOllama(tags=(500, {"error": "boom"}))
    catalog = OllamaModelCatalog(base_url=LOOPBACK_URL, http_client=stub.http_client())

    assert await catalog.reachable() is EndpointStatus.UNREACHABLE
    assert await catalog.models() == ()


async def test_reachable_never_answers_refused_not_loopback() -> None:
    """That status is settled in `__init__`: an instance that exists has
    already passed the guard."""
    stub = StubOllama()
    catalog = OllamaModelCatalog(base_url=LOOPBACK_URL, http_client=stub.http_client())

    assert await catalog.reachable() is not EndpointStatus.REFUSED_NOT_LOOPBACK


async def test_an_entry_with_no_name_is_dropped() -> None:
    stub = StubOllama(
        tags=(200, {"models": [{"digest": "abc", "size": 1}, TAGS_BODY["models"][0]]})
    )
    catalog = OllamaModelCatalog(base_url=LOOPBACK_URL, http_client=stub.http_client())

    models = await catalog.models()

    assert [model.tag for model in models] == ["llama3.1:8b-instruct-q8_0"]


async def test_an_endpoint_with_no_models_is_reachable_and_empty() -> None:
    stub = StubOllama(tags=(200, {"models": []}))
    catalog = OllamaModelCatalog(base_url=LOOPBACK_URL, http_client=stub.http_client())

    assert await catalog.reachable() is EndpointStatus.REACHABLE
    assert await catalog.models() == ()


# ===========================================================================
# Do-NOT #1, as a test rather than only as a lint rule
# ===========================================================================


def test_openai_is_named_only_by_this_one_module() -> None:
    """`import-linter`'s `one-llm-seam` contract is the gate; this documents
    *which* module holds the exemption, and covers the dynamic spellings
    (`importlib.import_module`, `__import__`) that an AST import scan alone
    would miss."""
    offenders = sorted(_modules_naming(("openai", "ollama")))
    assert offenders == ["ra2/infra/ollama_client.py"]


def _modules_naming(packages: tuple[str, ...]) -> set[str]:
    """Every file under `ra2/` that imports one of `packages`, statically or
    dynamically. Docstrings are excluded: several modules *state* the rule."""
    found: set[str] = set()
    for path in sorted(REPO_ROOT.joinpath("ra2").rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            ast.get_docstring(node, clean=False)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        }
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Call):
                names = [
                    argument.value
                    for argument in node.args
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                ]
            for name in names:
                head = name.split(".")[0]
                if head in packages and name not in docstrings:
                    found.add(relative)
    return found


# ===========================================================================
# OllamaEndpointProber — the settings dialog's "Test connection"
# ===========================================================================
#
# One test per `ProbeCode`, because the whole value of the button is that it
# tells these outcomes apart. `reachable()` collapses all of them to one bit,
# which is right for the Models card and useless for someone trying to work
# out why Ollama will not answer.
#
# Assertions are on the **code**, never on a sentence: the wording lives in one
# rendering table in `ra2/ui/components/ollama_settings.py` and must be
# rewritable without touching this file (CLAUDE.md: findings, not prose).


async def test_probe_reports_ok_with_the_model_count(stub: StubOllama) -> None:
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert result.code is ProbeCode.OK
    assert result.ok is True
    assert result.model_count == len(TAGS_BODY["models"])
    assert result.latency_ms is not None
    assert result.http_status is None


async def test_probe_reads_the_native_tags_url(stub: StubOllama) -> None:
    """The probe asks the same endpoint the catalogue does, so "the test
    passed" means the thing the app will actually call answered."""
    prober = OllamaEndpointProber(http_client=stub.http_client())

    await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert stub.tags_urls == ["http://127.0.0.1:11434/api/tags"]


async def test_probe_handles_a_base_url_without_the_v1_suffix(stub: StubOllama) -> None:
    """Someone who configured the native root by hand gets a working test
    rather than a 404 — `native_api_url` treats it as the root already."""
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe("http://127.0.0.1:11434", timeout_s=120)

    assert result.code is ProbeCode.OK
    assert stub.tags_urls == ["http://127.0.0.1:11434/api/tags"]


async def test_probe_reports_connection_refused_when_nothing_is_listening() -> None:
    stub = StubOllama(tags=httpx2.ConnectError("[Errno 111] Connection refused"))
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert result.code is ProbeCode.CONNECTION_REFUSED
    # The **verbatim** cause, for the dialog's second line. The SDK's own
    # message is the generic "Connection error."; the errno is the half that
    # tells an analyst anything, so `_cause` prefers `__cause__`.
    assert result.detail is not None
    assert "Connection refused" in result.detail


async def test_probe_detail_walks_to_the_deepest_cause() -> None:
    """The bottom of the `__cause__` chain, not the top.

    A real refusal arrives as `APIConnectionError` ("Connection error.") ->
    `httpx2.ConnectError` ("All connection attempts failed") ->
    `ConnectionRefusedError` ("[Errno 111] ... ('127.0.0.1', 11434)"). Each
    wrapper is more generic than what it wraps, and only the last one names the
    port — which is the whole reason the detail line exists.
    """
    refused = ConnectionRefusedError("[Errno 111] Connect call failed ('127.0.0.1', 11434)")
    wrapped = httpx2.ConnectError("All connection attempts failed")
    wrapped.__cause__ = refused
    stub = StubOllama(tags=wrapped)
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert result.code is ProbeCode.CONNECTION_REFUSED
    assert result.detail == "[Errno 111] Connect call failed ('127.0.0.1', 11434)"


async def test_probe_detail_survives_a_self_referential_cause_chain() -> None:
    """A chain that loops must not spin the walk."""
    looping = httpx2.ConnectError("round and round")
    looping.__cause__ = looping
    stub = StubOllama(tags=looping)
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert result.detail == "round and round"


async def test_probe_tells_a_timeout_apart_from_a_refusal() -> None:
    """`APITimeoutError` subclasses `APIConnectionError`, so order matters in
    the adapter. A host that accepted the connection and went quiet is a
    different fix from one that was never there, and collapsing the two would
    put the analyst on the wrong trail."""
    stub = StubOllama(tags=httpx2.ConnectTimeout("timed out"))
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert result.code is ProbeCode.TIMEOUT


async def test_probe_reports_the_http_status_it_was_given() -> None:
    """A 404 usually means `/v1` is pointed at something that is not Ollama.
    The status reaches the view, because "404" is the word that resolves it."""
    stub = StubOllama(tags=(404, {"error": "not found"}))
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert result.code is ProbeCode.HTTP_ERROR
    assert result.http_status == 404


async def test_probe_reports_a_500_as_an_http_error_not_a_refusal() -> None:
    """A 5xx is retryable for `extract`, but a connection **test** reports what
    it saw once rather than hiding a broken endpoint behind retries."""
    stub = StubOllama(tags=(500, {"error": "boom"}))
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert result.code is ProbeCode.HTTP_ERROR
    assert result.http_status == 500


async def test_probe_reports_bad_payload_when_something_else_answers() -> None:
    """A 200 from a web server that is not an Ollama. The port is right, the
    thing behind it is not — which no status code would have said."""
    stub = StubOllama(tags=(200, {"totally": "not ollama", "models": "a string"}))
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert result.code is ProbeCode.BAD_PAYLOAD


async def test_probe_reports_bad_payload_when_there_is_no_model_list() -> None:
    """A JSON 200 with no `models` key at all.

    The SDK's parser is deliberately lenient — that is what keeps the
    catalogue tolerant of fields Ollama adds later — so it returns an
    `_OllamaTags` with `models=None` rather than raising, and the probe would
    report a healthy endpoint with zero models. A real Ollama with nothing
    pulled sends `{"models": []}`; the key being **absent** means this is not
    an Ollama.
    """
    stub = StubOllama(tags=(200, {"status": "ok"}))
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert result.code is ProbeCode.BAD_PAYLOAD


async def test_probe_reports_ok_for_an_ollama_with_no_models_pulled() -> None:
    """The other side of the previous test: an empty list is a **healthy**
    endpoint that simply has nothing pulled yet, and must not be confused with
    a server that is not Ollama."""
    stub = StubOllama(tags=(200, {"models": []}))
    prober = OllamaEndpointProber(http_client=stub.http_client())

    result = await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert result.code is ProbeCode.OK
    assert result.model_count == 0


@pytest.mark.parametrize(
    ("url", "code"),
    [
        pytest.param("http://192.168.1.5:11434/v1", ProbeCode.REFUSED_NOT_LOOPBACK, id="lan"),
        pytest.param("http://ollama.example.com/v1", ProbeCode.REFUSED_NOT_LOOPBACK, id="public"),
        pytest.param("ftp://127.0.0.1", ProbeCode.MALFORMED_URL, id="scheme"),
        pytest.param("127.0.0.1:11434", ProbeCode.MALFORMED_URL, id="no-scheme"),
    ],
)
async def test_probe_refuses_without_opening_a_socket(url: str, code: ProbeCode) -> None:
    """**The N1 gate for this feature.** A refused endpoint must produce no
    packet at all, not merely no answer — `refusing_transport` fails the test
    if anything reaches it.

    And it is a `ProbeResult`, not an exception: the dialog has to be able to
    say "that host is not local" without taking the app down, which is the one
    way this differs from the constructor guard.
    """
    prober = OllamaEndpointProber(http_client=refusing_transport())

    result = await prober.probe(url, timeout_s=120)

    assert result.code is code
    assert result.ok is False
    assert result.latency_ms is None


async def test_probe_caps_the_timeout_below_the_configured_one(stub: StubOllama) -> None:
    """`RA2_LLM_TIMEOUT_S` is 120 by default — right for a model that is
    thinking, wrong for a dialog waiting to learn whether anything is there.
    The probe takes the lower of the two so a hung endpoint cannot freeze the
    dialog for two minutes.
    """
    client = stub.http_client()
    prober = OllamaEndpointProber(http_client=client)

    await prober.probe(LOOPBACK_URL, timeout_s=120)

    assert PROBE_TIMEOUT_S < 120


async def test_probe_satisfies_the_endpoint_prober_protocol() -> None:
    assert isinstance(OllamaEndpointProber(), EndpointProber)
