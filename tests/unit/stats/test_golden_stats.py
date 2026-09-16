"""The arithmetic gate (plan-phase-4.md §11, R2).

`tests/fixtures/scoring/golden_stats.json` is produced by
`generate_golden_stats.py`, which solves the Wilson **quadratic** in `Decimal`
at 40 digits. `ra2.domain.stats.wilson` uses the centre-and-margin closed form
in floats. Different algebra, different arithmetic — so agreement here is two
implementations agreeing, not one repeating itself.

Every prior phase asserted structure: a row exists, a flag is set, a file is
byte-identical. This phase asserts **arithmetic**, and a wrong bound throws
nothing, fails nothing else, and renders as a plausible number. This file is
the only layer that would catch it.

**A diff to the golden file belongs in the PR. Never regenerate it silently.**
"""

import json
from pathlib import Path

import pytest

from ra2.domain.stats import WILSON_Z_95, TiedCell, macro, mark_ties, suppressed, wilson

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures/scoring/golden_stats.json").read_text(
        encoding="utf-8"
    )
)

CELLS = GOLDEN["cells"]
MODELS = ("gemma3:12b", "mistral-small:24b", "qwen3:14b")


def _scored_cells() -> list[tuple[str, str, int, dict[str, object]]]:
    return [
        (feature, model, entry["n"], values)
        for feature, entry in CELLS.items()
        if not entry["suppressed"]
        for model, values in entry["models"].items()
    ]


def test_the_generator_and_the_implementation_agree_on_z():
    assert float(GOLDEN["z_95"]) == pytest.approx(WILSON_Z_95, abs=1e-12)


@pytest.mark.parametrize(
    ("feature", "model", "n", "values"),
    [pytest.param(*row, id=f"{row[0]}-{row[1]}") for row in _scored_cells()],
)
def test_wilson_matches_the_independent_quadratic_derivation(
    feature: str, model: str, n: int, values: dict[str, object]
) -> None:
    """Nine decimal places, on all 21 scored cells."""
    interval = wilson(int(values["successes"]), n)  # type: ignore[call-overload]
    assert interval.low == pytest.approx(float(values["ci_low"]), abs=1e-9)  # type: ignore[arg-type]
    assert interval.high == pytest.approx(float(values["ci_high"]), abs=1e-9)  # type: ignore[arg-type]
    assert interval.n == n


@pytest.mark.parametrize("model", MODELS)
def test_macro_reproduces_the_design_readmes_published_average(model: str) -> None:
    """`design/results/README.md` §3 publishes the arithmetic itself —
    "mistral 5.808/7 = 0.830 · qwen3 5.749/7 = 0.821 · gemma3 5.416/7 = 0.774".

    An independent check on both the fixture and the implementation: the
    generator sums the design's own F1s, and `macro` has to land on the same
    number the design printed.
    """
    expected = GOLDEN["macros"][model]
    values = [
        float(entry["models"][model]["f1"]) for entry in CELLS.values() if not entry["suppressed"]
    ]
    assert len(values) == expected["count"] == 7
    assert macro(values) == pytest.approx(float(expected["macro_f1"]), abs=1e-9)


@pytest.mark.parametrize("model", MODELS)
def test_the_published_three_decimal_rounding_still_holds(model: str) -> None:
    """The numbers a reader sees on the ranking tab: 0.830, 0.821, 0.774."""
    published = {"mistral-small:24b": 0.830, "qwen3:14b": 0.821, "gemma3:12b": 0.774}
    values = [
        float(entry["models"][model]["f1"]) for entry in CELLS.values() if not entry["suppressed"]
    ]
    assert round(macro(values), 3) == published[model]


def test_the_suppressed_feature_is_below_the_floor_and_carries_no_estimates():
    """`right_of_way`: 17 labelled cases against a floor of 20.

    It has **no** model entries at all in the fixture, because a suppressed
    cell has no point estimate — the absence is the fixture's way of saying
    what `SuppressedCell` says in the read model (§16.4).
    """
    entry = CELLS["right_of_way"]
    assert entry["n"] == 17
    assert entry["suppressed"] is True
    assert entry["models"] == {}
    assert suppressed(entry["n"], GOLDEN["min_cell_count"]) is True


def test_every_other_feature_is_above_the_floor():
    for feature, entry in CELLS.items():
        if feature == "right_of_way":
            continue
        assert suppressed(entry["n"], GOLDEN["min_cell_count"]) is False


@pytest.mark.parametrize("feature", [f for f, e in CELLS.items() if not e["suppressed"]])
def test_every_scored_feature_marks_somebody(feature: str) -> None:
    """No feature renders a row where nobody leads anything."""
    entry = CELLS[feature]
    cells = [
        TiedCell(
            point=float(entry["models"][model]["f1"]),
            interval=wilson(entry["models"][model]["successes"], entry["n"]),
        )
        for model in MODELS
    ]
    marks = mark_ties(cells)
    assert len(marks) == len(MODELS)
    assert set(marks) != {"none"}


def test_the_design_fixtures_leave_only_three_features_actually_separated():
    """**P4-D2, made concrete.**

    On `design/results/README.md`'s own numbers, only `road_condition`,
    `speed_limit` and `vehicles_involved` have a model whose interval clears
    every rival's. On the other four the leaders overlap, so §11.5 renders a
    tie and nobody is `BEST`.

    The README's Ranking section claims "the *best* column sums to 7 — exactly
    one highest value per feature", which is its *fixture counts* speaking
    rather than its own stated rule. The stated rule and mvp-spec.md §11.5
    agree with each other and win (CONTRACTS.md P4-D2); this test pins the
    consequence so a later change back to argmax is a failure, not a drift.
    """
    with_a_clear_best = set()
    for feature, entry in CELLS.items():
        if entry["suppressed"]:
            continue
        cells = [
            TiedCell(
                point=float(entry["models"][model]["f1"]),
                interval=wilson(entry["models"][model]["successes"], entry["n"]),
            )
            for model in MODELS
        ]
        if "best" in mark_ties(cells):
            with_a_clear_best.add(feature)
    assert with_a_clear_best == {"road_condition", "speed_limit", "vehicles_involved"}
