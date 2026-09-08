"""The `Clock` seam (sw-design.md §3)."""

from datetime import UTC, datetime, timedelta

import pytest

from ra2.infra.clock import FrozenClock, SystemClock

pytestmark = pytest.mark.backend


def test_system_clock_is_timezone_aware_utc_and_moves() -> None:
    clock = SystemClock()
    first = clock.now()
    second = clock.now()

    assert first.tzinfo is not None
    assert first.utcoffset() == timedelta(0)
    assert second >= first


def test_frozen_clock_defaults_to_a_fixed_instant() -> None:
    clock = FrozenClock()
    first = clock.now()
    second = clock.now()

    assert first == second
    assert first.tzinfo is not None


def test_frozen_clock_advance_moves_forward_only() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FrozenClock(start)

    clock.advance(seconds=30)
    assert clock.now() == start + timedelta(seconds=30)

    with pytest.raises(ValueError, match="backward"):
        clock.advance(seconds=-1)


def test_two_frozen_clocks_with_the_same_instant_are_byte_identical() -> None:
    """The exit criterion: same construction, same output, every call."""
    fixed = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)

    clock_a = FrozenClock(fixed)
    clock_b = FrozenClock(fixed)

    readings_a = [clock_a.now().isoformat() for _ in range(5)]
    readings_b = [clock_b.now().isoformat() for _ in range(5)]

    assert readings_a == readings_b
