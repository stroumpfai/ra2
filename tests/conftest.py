# FROZEN — see CONTRACTS.md
"""Root fixtures only.

Everything here is shared by all five layers, so it is frozen at M0: with five
agents working in parallel this file would otherwise be a five-way conflict
(plan-m0-m5.md X4). **Per-layer fixtures go in `tests/<layer>/conftest.py`**,
owned by whoever owns that layer in that wave.

The substitutes below are injected through `create_app()`'s keyword arguments.
There is no test-mode branch in production code (sw-design.md §3, §12.12).
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI

from ra2.infra.config import Settings
from ra2.main import create_app

__all__ = [
    "FrozenClock",
    "SeededFactory",
    "app_factory",
    "frozen_clock",
    "seeded_ids",
    "settings",
    "tmp_data_dir",
]

#: A fixed instant, so golden reports and E2E screenshots are byte-stable.
FROZEN_NOW = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)


class FrozenClock:
    """A `Clock` that does not move unless a test moves it.

    A4 owns the production implementation in `ra2.infra.clock`; this one exists
    so the root fixtures do not depend on Wave 1 landing first.
    """

    def __init__(self, now: datetime = FROZEN_NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: float) -> None:
        from datetime import timedelta

        self._now += timedelta(seconds=seconds)


class SeededFactory:
    """An `IdFactory` that counts, so ids are reproducible across runs."""

    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n:08d}"


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """An isolated `RA2_DATA_DIR`. Never the developer's own `./var`."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def settings(tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings pointed at the temp data dir, with the ambient environment
    cleared so a developer's own `RA2_*` variables cannot change a result."""
    for name in (
        "RA2_DATA_DIR",
        "RA2_DB_PATH",
        "RA2_LLM_BASE_URL",
        "RA2_HOST",
        "RA2_PORT",
        "RA2_MAX_UPLOAD_MB",
        "RA2_DEV_RECORD_MAX",
        "RA2_EVAL_RECORD_MIN",
        "RA2_MIN_CELL_COUNT",
    ):
        monkeypatch.delenv(name, raising=False)
    return Settings(data_dir=tmp_data_dir, _env_file=None)


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def seeded_ids() -> SeededFactory:
    return SeededFactory()


@pytest.fixture
def app_factory(
    settings: Settings,
    frozen_clock: FrozenClock,
    seeded_ids: SeededFactory,
) -> Iterator[Callable[..., FastAPI]]:
    """Build an app with deterministic adapters.

    Pass `mount_ui=False` for backend tests that drive only `/api/v1`:
    NiceGUI's `core.app` is a process-wide singleton, so mounting it more than
    once per process raises. UI and E2E tests mount it exactly once.

    Any keyword `create_app()` accepts can be overridden per test.
    """

    def _factory(**overrides: object) -> FastAPI:
        kwargs: dict[str, object] = {
            "settings": settings,
            "clock": frozen_clock,
            "ids": seeded_ids,
            "mount_ui": False,
        }
        kwargs.update(overrides)
        return create_app(**kwargs)  # type: ignore[arg-type]

    yield _factory
