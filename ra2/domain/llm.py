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
from urllib.parse import urlsplit

__all__ = [
    "ALLOWED_SCHEMES",
    "LOOPBACK_HOSTS",
    "PROBE_TIMEOUT_S",
    "EndpointProber",
    "EndpointStatus",
    "Extraction",
    "LLMClient",
    "LlmEndpointError",
    "ModelCatalog",
    "ModelInfo",
    "ProbeCode",
    "ProbeResult",
    "classify_endpoint",
    "is_loopback_url",
    "require_loopback",
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
      (mvp-spec.md §19.10, sw-design.md §15.5). Nothing catches it on the
      **configured** endpoint — an app configured this way does not start,
      which is the point. `EndpointProber` reaches the same verdict through
      `classify_endpoint` for an endpoint the user has merely *typed*, and
      returns it as a `ProbeResult` rather than raising: a settings dialog
      has to be able to say "that host is not local" without taking the app
      down with it.
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


# ===========================================================================
# Probing an endpoint the user typed, and saying why it did not answer
# ===========================================================================


#: A connection test is not a generation call. `RA2_LLM_TIMEOUT_S` defaults to
#: 120 — right for a model that is thinking, wrong for a dialog waiting to
#: learn whether anything is listening, which would sit spinning for two
#: minutes against a host that accepts the connection and then goes quiet. A
#: probe takes the **lower** of the configured timeout and this, and
#: `ProbeCode.TIMEOUT`'s sentence names the bound it actually used so it does
#: not read as contradicting the timeout field above it in the dialog.
#:
#: Part of the `EndpointProber` contract rather than the adapter's own
#: business, because `evaluation_service` reports the bound it settled on and
#: `ra2/services/` has no business importing the module that imports `openai`.
PROBE_TIMEOUT_S = 5


class ProbeCode(StrEnum):
    """Why a connection test did or did not succeed.

    A **stable identifier**, exactly as `FindingCode` and `ParseIssueCode`
    are: tests assert on the code and never on message text, and the wording
    lives in one rendering table in `ui/` (CLAUDE.md, mvp-spec.md §15).

    `EndpointStatus` is the *configured* endpoint's one-bit state, rendered
    beside the Models card. This is the richer answer to "I pressed Test on
    the value I just typed" — "unreachable" cannot tell an analyst whether
    Ollama is down or the port is wrong, and that distinction is the whole
    point of the button.
    """

    OK = "ok"
    #: Refused before a socket was opened: the host is not loopback (N1).
    REFUSED_NOT_LOOPBACK = "refused_not_loopback"
    #: Refused before a socket was opened: not a URL that parses at all.
    MALFORMED_URL = "malformed_url"
    #: The host answered the TCP connect with a refusal, or is not there.
    CONNECTION_REFUSED = "connection_refused"
    #: The connection was accepted, but nothing came back in time.
    TIMEOUT = "timeout"
    #: An HTTP response arrived carrying a status that is not a success.
    HTTP_ERROR = "http_error"
    #: Something answered with a body that is not Ollama's `/api/tags`.
    BAD_PAYLOAD = "bad_payload"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One connection test's outcome.

    `detail` carries the provider's or the OS's **verbatim** words — an
    `errno`, a status line, a validator's complaint. The sentence an analyst
    reads is built from `code` alone; `detail` is the second line that
    resolves the cases the sentence cannot. Keeping them apart is what lets
    the wording change without a test changing (CLAUDE.md: findings, not
    prose).
    """

    code: ProbeCode
    #: The raw cause, for the debugging line. `None` when there was none.
    detail: str | None = None
    #: Round trip for the probe itself. `None` unless the endpoint answered.
    latency_ms: int | None = None
    #: How many models the endpoint offers. `None` unless `code` is `OK`.
    model_count: int | None = None
    #: The status that produced `HTTP_ERROR`. `None` for every other code.
    http_status: int | None = None

    @property
    def ok(self) -> bool:
        return self.code is ProbeCode.OK


@runtime_checkable
class EndpointProber(Protocol):
    """Ask an **arbitrary** endpoint whether it is there, and why not.

    Deliberately *not* a method on `ModelCatalog`: that protocol is bound to
    one `base_url` at construction, so it could never answer for the value
    typed into the settings dialog — which is the only value a connection test
    is useful for. It is also `runtime_checkable` and implemented
    structurally, so widening it would break every substitute at once.

    The implementation **must** apply `classify_endpoint` before opening a
    socket: a non-loopback URL is a result to render, never a packet to send.
    """

    async def probe(self, base_url: str, *, timeout_s: int) -> ProbeResult:
        """Never raises. Every failure is a `ProbeResult` with a code —
        "unreachable is a state, not an error" (sw-design.md §15.5), and a
        test button that could raise would force exactly the toast the design
        rejects."""
        ...


# ===========================================================================
# The loopback rule — one statement of it, three faces
# ===========================================================================
#
# This lived in `ra2/infra/ollama_client.py` until the settings dialog needed
# it. `.importlinter`'s `ui-reaches-only-services-and-domain` contract forbids
# `ra2.ui` -> `ra2.infra`, so a modal that refuses a non-loopback endpoint as
# you type it could not share the rule the app enforces at startup — and two
# copies of the one thing standing between this codebase and N1 would drift.
# It is pure `urllib.parse`, so it is legal here; `infra` re-exports it, the
# same shape `services/errors.py` re-exports `LlmEndpointError`.

#: The only hosts the guard accepts. Written out rather than resolved through
#: DNS: a name that resolves to loopback *today* is not a guarantee, and this
#: list is the whole of what N1 permits.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "[::1]", "localhost"})

#: The only URL schemes the guard accepts. Anything else (`file:`, `ftp:`, a
#: bare `host:port` that `urlsplit` reads as a scheme) is refused rather than
#: interpreted.
ALLOWED_SCHEMES = frozenset({"http", "https"})


def classify_endpoint(base_url: str) -> ProbeCode | None:
    """Why `base_url` may not be dialled, or `None` when it may be.

    The **one** statement of the rule. `require_loopback` raises on it, the
    settings dialog disables Save on it, and `EndpointProber` returns it as a
    result — three faces, one decision.

    The host is compared against `LOOPBACK_HOSTS` **literally**: no DNS, no
    `socket.getaddrinfo`, no "does it resolve to 127.0.0.1". A name that
    resolves to loopback on this machine today resolves wherever its owner
    points it tomorrow, and the guarantee this rule carries has to be readable
    from the configuration alone.

    `urlsplit(...).hostname` lower-cases and strips the brackets from an IPv6
    literal, so `http://[::1]:11434/v1` is compared as `::1`. It returns
    `None` for a string with no authority, which is `MALFORMED_URL`: an
    endpoint this function cannot parse is not one it can vouch for.

    The two codes are a **diagnosis**, not two policies — `require_loopback`
    refuses both identically, which is why moving the rule down here changed
    no behaviour at the startup guard.
    """
    try:
        parts = urlsplit(base_url)
        host = parts.hostname
        # `.hostname` does not validate the port; `.port` does. A `base_url`
        # this function cannot fully parse is one it cannot vouch for.
        _ = parts.port
    except ValueError:  # a malformed port, an unparseable IPv6 literal
        return ProbeCode.MALFORMED_URL
    if parts.scheme.lower() not in ALLOWED_SCHEMES or host is None:
        return ProbeCode.MALFORMED_URL
    if host.lower() not in LOOPBACK_HOSTS:
        return ProbeCode.REFUSED_NOT_LOOPBACK
    return None


def is_loopback_url(base_url: str) -> bool:
    """`classify_endpoint`'s non-raising face — what the settings dialog needs
    to disable Save without a round trip to the service."""
    return classify_endpoint(base_url) is None


def require_loopback(base_url: str) -> None:
    """Refuse a `base_url` that is not on this host. **N1, and no opt-out.**

    Raises `LlmEndpointError(base_url, EndpointStatus.REFUSED_NOT_LOOPBACK)`
    for **either** refusal `classify_endpoint` can name: an unparseable URL is
    refused exactly as firmly as a LAN address, because neither is an endpoint
    this code can promise stays on the host.

    Called first in `OllamaLLMClient.__init__` and `OllamaModelCatalog.
    __init__`, before the SDK client exists — a misconfigured
    `RA2_LLM_BASE_URL` fails `create_app()` at start, not at the first
    narrative.
    """
    if classify_endpoint(base_url) is not None:
        raise LlmEndpointError(base_url, EndpointStatus.REFUSED_NOT_LOOPBACK)
