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
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel

from ra2.domain.llm import EndpointStatus, Extraction, LLMClient, ModelCatalog, ModelInfo
from ra2.infra.config import Settings
from ra2.infra.ollama_client import (
    LOOPBACK_HOSTS,
    LlmEndpointError,
    OllamaLLMClient,
    OllamaModelCatalog,
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
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle))


def refusing_transport() -> httpx2.AsyncClient:
    """A transport that fails the test if it is ever asked for anything.

    The guard has to refuse **before a socket is opened**; this is what proves
    "before", rather than merely "instead of an answer".
    """

    def handle(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"the guard let a request through to {request.url}")

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


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
