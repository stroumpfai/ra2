"""`OllamaConnection` — the live client and catalogue, rebindable (SD43).

Three properties, each one a way the rebind could go wrong:

1. **Every call reaches the current pair.** After a rebind the next extract
   and the next catalogue read go to the adapters built on the new values —
   asserted with recording stand-ins for the two adapter classes, so no socket
   is opened.
2. **A refused URL swaps nothing.** Both adapters are built before either is
   swapped, and each refuses a non-loopback URL in its constructor, so a
   failed rebind leaves the connection exactly as it was. With the real
   adapter classes: the guard under test is theirs.
3. **What is not an analyst's setting survives.** Retries and the reasoning
   effort default are carried over; SD43 moves exactly two values.
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar

import pytest

import ra2.infra.connection as connection_module
from ra2.domain.llm import EndpointStatus, LlmEndpointError
from ra2.infra.connection import OllamaConnection

pytestmark = pytest.mark.backend

SEED = "http://127.0.0.1:11434/v1"
SAVED = "http://127.0.0.1:11999/v1"
#: What the recording client hands back, so the test can tell it arrived.
EXTRACTED: object = object()


@dataclass
class _Built:
    """What one adapter was constructed with, and what was asked of it."""

    kwargs: dict[str, Any]
    calls: list[str] = field(default_factory=list)


class _RecordingClient:
    built: ClassVar[list[_Built]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.record = _Built(kwargs)
        type(self).built.append(self.record)

    async def extract(self, *args: Any, **kwargs: Any) -> Any:
        self.record.calls.append("extract")
        return EXTRACTED


class _RecordingCatalog:
    built: ClassVar[list[_Built]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.record = _Built(kwargs)
        type(self).built.append(self.record)

    async def reachable(self) -> EndpointStatus:
        self.record.calls.append("reachable")
        return EndpointStatus.REACHABLE


@pytest.fixture
def recording(monkeypatch: pytest.MonkeyPatch) -> tuple[list[_Built], list[_Built]]:
    _RecordingClient.built = []
    _RecordingCatalog.built = []
    monkeypatch.setattr(connection_module, "OllamaLLMClient", _RecordingClient)
    monkeypatch.setattr(connection_module, "OllamaModelCatalog", _RecordingCatalog)
    return _RecordingClient.built, _RecordingCatalog.built


def _connection() -> OllamaConnection:
    return OllamaConnection(base_url=SEED, timeout_s=600, max_retries=2, reasoning_effort="none")


async def test_after_a_rebind_every_call_reaches_the_new_pair(
    recording: tuple[list[_Built], list[_Built]],
) -> None:
    clients, catalogs = recording
    connection = _connection()

    connection.rebind(SAVED, 45)
    extracted = await connection.extract(
        "narrative", dict, "qwen3:8b", temperature=0.0, seed=42, reasoning_effort="none"
    )
    status = await connection.reachable()

    assert extracted is EXTRACTED
    assert status is EndpointStatus.REACHABLE
    first_client, second_client = clients
    first_catalog, second_catalog = catalogs
    assert (second_client.kwargs["base_url"], second_client.kwargs["timeout_s"]) == (SAVED, 45)
    assert (second_catalog.kwargs["base_url"], second_catalog.kwargs["timeout_s"]) == (SAVED, 45)
    assert second_client.calls == ["extract"]
    assert second_catalog.calls == ["reachable"]
    assert first_client.calls == first_catalog.calls == []
    assert (connection.base_url, connection.timeout_s) == (SAVED, 45)


async def test_a_rebind_keeps_what_is_not_an_analysts_setting(
    recording: tuple[list[_Built], list[_Built]],
) -> None:
    clients, _ = recording
    connection = _connection()

    connection.rebind(SAVED, 45)

    first, second = clients
    for key in ("max_retries", "reasoning_effort"):
        assert second.kwargs[key] == first.kwargs[key]


@pytest.mark.parametrize(
    "refused", ["http://0.0.0.0:11434/v1", "http://192.168.1.10:11434/v1", "not a url"]
)
def test_a_refused_url_swaps_nothing(refused: str) -> None:
    """The real adapters: the guard is their constructors', and it runs before
    this object touches its own state. No opt-out reachable."""
    connection = _connection()

    with pytest.raises(LlmEndpointError):
        connection.rebind(refused, 45)

    assert (connection.base_url, connection.timeout_s) == (SEED, 600)
