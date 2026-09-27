"""`ra2 serve` — the one reader of `RA2_HOST` and `RA2_PORT` (`SD42`).

Until this existed, both settings were documented as "bind to loopback by
default (N1)" and read by nothing: the `justfile`'s `--host`/`--port` bound,
and **nothing anywhere refused `--host 0.0.0.0`** (`docs/risk-assesment.md`
A4). The properties worth a test are the three that would hurt:

1. **What `Settings` says is what binds** — the documented default and the
   actual bind are one fact.
2. **A non-loopback host is refused before a socket opens**, in every form a
   person might plausibly write, with no opt-out reachable.
3. **`--reload` watches `ra2/` alone**, which is what `dev-reload` did.

`uvicorn.run` is replaced for the duration of each test. That is a
substitution at the library boundary, not a branch in `ra2/` (§12.12): the
launcher cannot tell, and would bind for real without it.
"""

from pathlib import Path
from typing import Any

import pytest
import uvicorn

from ra2.cli import main

pytestmark = pytest.mark.backend


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
    """Every `uvicorn.run` the launcher makes, recorded instead of served.

    The working directory moves to an empty temp dir so a developer's own
    `.env` cannot reach `Settings()`, and the two variables under test start
    unset so each test says exactly what it depends on.
    """
    calls: list[dict[str, Any]] = []

    def _record(app: str, **kwargs: Any) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr(uvicorn, "run", _record)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RA2_HOST", raising=False)
    monkeypatch.delenv("RA2_PORT", raising=False)
    return calls


def test_serve_binds_the_configured_host_and_port(
    uvicorn_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RA2_HOST", "127.0.0.1")
    monkeypatch.setenv("RA2_PORT", "9001")

    assert main(["serve"]) == 0

    assert uvicorn_calls == [
        {
            "app": "ra2.main:create_app",
            "factory": True,
            "host": "127.0.0.1",
            "port": 9001,
            "reload": False,
            "reload_dirs": None,
        }
    ]


def test_serve_with_nothing_set_binds_what_section_10_documents(
    uvicorn_calls: list[dict[str, Any]],
) -> None:
    """`127.0.0.1:8080` — the defaults `just dev` always bound, now coming from
    the one place sw-design.md §10 says they do."""
    assert main(["serve"]) == 0

    (call,) = uvicorn_calls
    assert (call["host"], call["port"]) == ("127.0.0.1", 8080)


def test_serve_reload_watches_ra2_alone(uvicorn_calls: list[dict[str, Any]]) -> None:
    assert main(["serve", "--reload"]) == 0

    (call,) = uvicorn_calls
    assert call["reload"] is True
    assert call["reload_dirs"] == ["ra2"]


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "LOCALHOST", "::1"])
def test_serve_accepts_every_loopback_form(
    uvicorn_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    monkeypatch.setenv("RA2_HOST", host)

    assert main(["serve"]) == 0

    (call,) = uvicorn_calls
    assert call["host"] == host


@pytest.mark.parametrize(
    "host",
    [
        # Every interface, IPv4 and IPv6 — the one-word way to publish the app.
        "0.0.0.0",
        "::",
        # A LAN address: "a colleague wants to see a result" (A4).
        "192.168.1.10",
        # A name. Compared literally, never resolved (`classify_endpoint`'s
        # rule): this one resolves to 127.0.0.1 through public DNS today and to
        # wherever its owner points it tomorrow.
        "127.0.0.1.nip.io",
        # Loopback-looking, and still not the literal set.
        "127.0.0.2",
    ],
)
def test_serve_refuses_a_non_loopback_host_before_binding(
    uvicorn_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    host: str,
) -> None:
    monkeypatch.setenv("RA2_HOST", host)

    assert main(["serve"]) != 0

    assert uvicorn_calls == [], "a refused host must never reach uvicorn"
    assert repr(host) in capsys.readouterr().err
