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

---

## What H4 added (I3 and the Wave-4 views build against this)

`tests/conftest.py` is frozen and constructs both classes with **no
arguments**, so every addition below is a keyword with a default that
reproduces the M17 behaviour exactly. Nothing here changes what
`FakeLLMClient()` or `StaticModelCatalog()` already did.

`FakeLLMClient` gains four things:

- **scripted responses** — `script=[...]` answers in call order, `responses={
  marker: body}` answers by what is *in* the prompt, which is how a test
  scripts one body per record without knowing the call order;
- **injected failures** — `failures={3: exc}` raises on the fourth call and
  `fail_from=3` raises on that call and every one after, which is how I3 kills
  a run mid-corpus and then resumes it. The default exception is the one the
  real adapter raises when the endpoint will not answer, so the worker's
  handling is exercised, not a stand-in;
- **a latency model** — `latencies=[...]` cycles per call, so a progress
  card's elapsed/ETA line has something that moves;
- **the retry count**, on `domain.llm.Extraction.retry_count` — the field
  H4's amendment added to the frozen domain type, so the double and the
  real adapter return one type with no subclass in between.

`StaticModelCatalog` gains a mutable status (`set_status`, so a test can press
"refresh" and have the endpoint come back) and two call counters, because
"never on a timer" (plan-phase-3.md C3) is a claim about *how many times*
`reachable()` is called.
"""

from collections.abc import Mapping, Sequence

from ra2.domain.llm import EndpointStatus, Extraction, ModelInfo, ProbeCode, ProbeResult
from ra2.infra.ollama_client import LlmEndpointError

__all__ = [
    "DEFAULT_ENDPOINT",
    "DEFAULT_MODELS",
    "FakeLLMClient",
    "StaticEndpointProber",
    "StaticModelCatalog",
]

#: Three of the design's six fixture models — enough to select two and leave
#: one unselected, which is what the Evaluation journey needs.
DEFAULT_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(tag="llama3.1:8b-instruct-q8_0", digest="8fa1c3d0", size_bytes=8_500_000_000),
    ModelInfo(tag="qwen2.5:14b-instruct-q6_K", digest="c17b904e", size_bytes=12_100_000_000),
    ModelInfo(tag="llama3.3:70b-instruct-q4_K_M", digest="7e55aa12", size_bytes=42_500_000_000),
)

#: `Settings.llm_base_url`'s default, repeated here so an injected failure
#: carries a plausible endpoint without the double importing `Settings`.
DEFAULT_ENDPOINT = "http://127.0.0.1:11434/v1"


class FakeLLMClient:
    """A `domain.llm.LLMClient` that returns a canned response.

    Records every call on `calls`, so a test can assert *what was sent* — the
    resolved prompt is the thing most worth pinning, since it is what a run's
    fingerprints claim to describe.

    Args:
        response: the body returned when nothing more specific applies.
        latency_ms: the reported latency when `latencies` is not given.
        script: bodies returned in call order. Once exhausted, `response` is
            used again — a run longer than the script does not fail, it just
            stops being scripted.
        responses: `marker -> body`. The **first** marker (in insertion order)
            that occurs anywhere in the resolved prompt wins. Markers are
            record keys or narrative fragments; a test scripts per record
            without having to know the order records are visited in.
        latencies: reported latencies, cycled. A one-element sequence is a
            constant; a longer one makes the progress card's numbers move.
        failures: `call index -> exception`, zero-based, raised **instead of**
            answering. This is how a run is killed mid-corpus.
        fail_from: the call index from which every call raises `failure`.
        failure: what `fail_from` raises. Defaults to the error the real
            adapter raises when the endpoint will not answer within its
            bounded retries, so the caller's real handling is exercised.
        parse_ok / parse_error: the parse outcome to report. The default keeps
            M17's behaviour — `parse_ok=True` with a `None` value, because the
            worker parses `raw_output_text` through `domain.extraction` and
            does not read `value`.
        retry_count: the count reported on every returned `Extraction`.
    """

    def __init__(
        self,
        *,
        response: str = "{}",
        latency_ms: int = 1,
        script: Sequence[str] | None = None,
        responses: Mapping[str, str] | None = None,
        latencies: Sequence[int] | None = None,
        failures: Mapping[int, BaseException] | None = None,
        fail_from: int | None = None,
        failure: BaseException | None = None,
        parse_ok: bool = True,
        parse_error: str | None = None,
        retry_count: int = 0,
    ) -> None:
        self._response = response
        self._latency_ms = latency_ms
        self._script = tuple(script or ())
        self._responses = dict(responses or {})
        self._latencies = tuple(latencies or ())
        self._failures = dict(failures or {})
        self._fail_from = fail_from
        self._failure = failure or LlmEndpointError(DEFAULT_ENDPOINT, EndpointStatus.UNREACHABLE)
        self._parse_ok = parse_ok
        self._parse_error = parse_error
        self._retry_count = retry_count
        #: `(text, model, temperature, seed)` per call, in order. The shape is
        #: M17's and stays: tests already destructure it.
        self.calls: list[tuple[str, str, float, int]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def prompts(self) -> list[str]:
        """Just the resolved prompts, in call order."""
        return [call[0] for call in self.calls]

    def response_for(self, text: str, index: int) -> str:
        """The body this call answers with. Marker match first, then the
        script, then the default — most specific wins."""
        for marker, body in self._responses.items():
            if marker in text:
                return body
        if index < len(self._script):
            return self._script[index]
        return self._response

    def _latency_for(self, index: int) -> int:
        if not self._latencies:
            return self._latency_ms
        return self._latencies[index % len(self._latencies)]

    def _failure_for(self, index: int) -> BaseException | None:
        if index in self._failures:
            return self._failures[index]
        if self._fail_from is not None and index >= self._fail_from:
            return self._failure
        return None

    async def extract[T](
        self,
        text: str,
        schema: type[T],
        model: str,
        *,
        temperature: float,
        seed: int,
    ) -> Extraction[T]:
        index = len(self.calls)
        self.calls.append((text, model, temperature, seed))
        failure = self._failure_for(index)
        if failure is not None:
            # Raised, not returned: an endpoint that will not answer must
            # leave a hole for the resume query to find, never a row
            # (sw-design.md §15.3). The real adapter draws the same line.
            raise failure
        response = self.response_for(text, index)
        return Extraction[T](
            value=None,
            raw_output_text=response,
            parse_ok=self._parse_ok,
            parse_error=self._parse_error,
            latency_ms=self._latency_for(index),
            prompt_tokens=len(text) // 4,
            completion_tokens=len(response) // 4,
            retry_count=self._retry_count,
        )


class StaticModelCatalog:
    """A `domain.llm.ModelCatalog` with a fixed answer.

    Construct with `status=EndpointStatus.UNREACHABLE` to exercise the
    disabled-Launch path: an unreachable endpoint yields an **empty list and
    a reason**, never an exception (sw-design.md §15.5).

    `set_status()` makes the answer change between calls, which is what the
    settings dialog's "refresh" needs: the endpoint was down, the user started
    Ollama, the next press finds it. `models_calls` / `reachable_calls` count
    the asks, because "re-checked on view load and when refresh is pressed —
    **never on a timer**" is a claim about how often this is called.
    """

    def __init__(
        self,
        models: Sequence[ModelInfo] = DEFAULT_MODELS,
        *,
        status: EndpointStatus = EndpointStatus.REACHABLE,
    ) -> None:
        self._models = tuple(models)
        self._status = status
        self.models_calls = 0
        self.reachable_calls = 0

    def set_status(
        self,
        status: EndpointStatus,
        *,
        models: Sequence[ModelInfo] | None = None,
    ) -> None:
        """Change what the next call sees. `models` defaults to unchanged."""
        self._status = status
        if models is not None:
            self._models = tuple(models)

    async def models(self) -> tuple[ModelInfo, ...]:
        self.models_calls += 1
        if self._status is not EndpointStatus.REACHABLE:
            return ()
        return self._models

    async def reachable(self) -> EndpointStatus:
        self.reachable_calls += 1
        return self._status


class StaticEndpointProber:
    """A `domain.llm.EndpointProber` with a fixed verdict.

    The real `OllamaEndpointProber` opens a socket, and `create_app()` defaults
    to it — harmless for the tests that never press Test, and exactly what must
    not happen in the layers that do. **No test in layers 1-4 talks to a live
    endpoint** (plan-phase-3.md §11), so anything exercising the settings
    dialog's connection test substitutes this.

    `set_result()` makes the verdict change between presses, which is the
    journey worth covering: nothing was listening, the analyst started Ollama,
    the next press finds it. `probe_calls` records every ask — `calls` keeps
    the arguments, because "the probe is bounded to 5 s, not the configured
    120" is a claim about what this was called *with*.
    """

    def __init__(self, result: ProbeResult | None = None) -> None:
        self._result = result or ProbeResult(
            code=ProbeCode.OK, latency_ms=12, model_count=len(DEFAULT_MODELS)
        )
        self.probe_calls = 0
        self.calls: list[tuple[str, int]] = []

    def set_result(self, result: ProbeResult) -> None:
        """Change what the next probe returns."""
        self._result = result

    async def probe(self, base_url: str, *, timeout_s: int) -> ProbeResult:
        self.probe_calls += 1
        self.calls.append((base_url, timeout_s))
        return self._result
