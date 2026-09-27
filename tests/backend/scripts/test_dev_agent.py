"""`scripts/dev_agent.py` — an agent's isolated instance (`SD42`).

It set `RA2_PORT` in the child environment and then passed `--port` on argv
as well, because nothing in `ra2/` read the variable — the fourth instance
`docs/risk-assesment.md` G3 named. `ra2 serve` reads it now, so the script
passes the bind **only** through the environment, where the loopback refusal
sees it.

Both subprocesses are recorded rather than run: the migration and the server
are covered where they live, and what this script owns is what it hands them.
`scripts/` is not a package, so the module is loaded by path — the same way a
script is actually run.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.backend

#: `tests/backend/scripts/` -> the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def dev_agent() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ra2_dev_agent", REPO_ROOT / "scripts" / "dev_agent.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dev_agent_passes_the_bind_in_the_environment_and_not_on_argv(
    dev_agent: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []

    def _record(argv: list[str], *, env: dict[str, str], check: bool) -> Any:
        calls.append({"argv": argv, "env": env})
        return subprocess.CompletedProcess(argv, returncode=0)

    monkeypatch.setattr(dev_agent, "subprocess", SimpleNamespace(run=_record))
    monkeypatch.setattr(
        dev_agent, "tempfile", SimpleNamespace(mkdtemp=lambda prefix: str(tmp_path))
    )
    # The developer's own environment must not be what decides the host.
    monkeypatch.setenv("RA2_HOST", "0.0.0.0")

    assert dev_agent.main() == 0

    migrate, serve = calls
    assert migrate["argv"][1:] == ["-m", "alembic", "upgrade", "head"]
    assert serve["argv"] == [sys.executable, "-m", "ra2.cli", "serve"]
    assert not {"--host", "--port"} & set(serve["argv"])

    env = serve["env"]
    assert env["RA2_HOST"] == "127.0.0.1"
    assert int(env["RA2_PORT"]) > 0
    assert env["RA2_DATA_DIR"] == str(tmp_path)
    # The migration ran against the same isolated data dir the server uses.
    assert migrate["env"] is env
