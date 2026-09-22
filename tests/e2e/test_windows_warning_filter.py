"""The Windows-only unraisable-warning filter, checked from any platform.

`conftest.pytest_collection_modifyitems` suppresses
`PytestUnraisableExceptionWarning` for this layer **on Windows only**, and the
reasoning for both halves of that is in its own docstring. Nothing asserted it,
and nobody developing this project can run the leg it protects — so an
inverted boolean would suppress the warning on Linux (retiring a check N4 wants
kept) or on neither (returning `just e2e` on Windows to the unreadable wall it
was), and both would land green.

The flag is monkeypatched rather than the platform, because the platform is
exactly what cannot be faked here.
"""

import sys

import pytest
from tests.e2e import conftest

pytestmark = pytest.mark.e2e

_FILTER = "ignore::pytest.PytestUnraisableExceptionWarning"


class _Item:
    """Enough of `pytest.Item` to record what was added to it."""

    def __init__(self) -> None:
        self.markers: list[pytest.MarkDecorator] = []

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self.markers.append(marker)


def _collect(*, on_windows: bool, monkeypatch: pytest.MonkeyPatch) -> _Item:
    monkeypatch.setattr(conftest, "_ON_WINDOWS", on_windows)
    item = _Item()
    conftest.pytest_collection_modifyitems([item])  # type: ignore[list-item]
    return item


def test_the_filter_is_applied_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _collect(on_windows=True, monkeypatch=monkeypatch)

    assert [marker.args[0] for marker in item.markers] == [_FILTER]


def test_the_filter_is_not_applied_anywhere_else(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Linux leg is the one CI gates on. A suppression that travelled
    there would retire the check rather than scope it."""
    item = _collect(on_windows=False, monkeypatch=monkeypatch)

    assert item.markers == []


def test_the_flag_agrees_with_the_platform_the_suite_is_running_on() -> None:
    """`_ON_WINDOWS` is bound to a `bool` to keep `sys.platform` away from the
    type checker's narrowing; this is what stops that trick from drifting away
    from the thing it stands for."""
    assert (sys.platform == "win32") == conftest._ON_WINDOWS
