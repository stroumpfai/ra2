"""The `IdFactory` seam (sw-design.md §3)."""

import uuid

import pytest

from ra2.infra.idgen import SeededFactory, Uuid7Factory

pytestmark = pytest.mark.backend


def test_uuid7_factory_produces_distinct_time_ordered_ids() -> None:
    factory = Uuid7Factory()
    ids = [factory.new_id() for _ in range(20)]

    assert len(set(ids)) == len(ids)
    for value in ids:
        assert uuid.UUID(value).version == 7
    # UUIDv7 sorts lexicographically by creation time.
    assert ids == sorted(ids)


def test_seeded_factory_ids_are_valid_uuids() -> None:
    factory = SeededFactory(seed=1)
    for _ in range(5):
        value = factory.new_id()
        assert uuid.UUID(value).version == 4


def test_seeded_factory_is_deterministic_across_independent_runs() -> None:
    """The exit criterion: same seed, byte-identical sequence, two runs."""
    run_a = SeededFactory(seed=42)
    run_b = SeededFactory(seed=42)

    sequence_a = [run_a.new_id() for _ in range(10)]
    sequence_b = [run_b.new_id() for _ in range(10)]

    assert sequence_a == sequence_b


def test_seeded_factory_differs_across_seeds() -> None:
    """Sanity check: a seed is not a no-op."""
    sequence_1 = [SeededFactory(seed=1).new_id() for _ in range(5)]
    sequence_2 = [SeededFactory(seed=2).new_id() for _ in range(5)]

    assert sequence_1 != sequence_2
