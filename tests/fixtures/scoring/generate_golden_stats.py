"""Regenerate `golden_stats.json` — the phase's arithmetic check.

Run with `uv run python tests/fixtures/scoring/generate_golden_stats.py`.

**This is a second implementation, not a recording of the first.** A golden file
produced by calling `ra2.domain.stats` would assert only that the code still
does what it did, which is worth very little: a wrong Wilson bound throws
nothing, fails nothing else, and renders as a plausible number in the one view
the project exists to produce (sw-design.md §16.4, plan-phase-4.md R2).

So the bounds here are derived a different way. `stats.wilson` uses the
familiar centre-and-margin form; this file solves the **quadratic** the Wilson
interval is defined by — the values of `p` where the score statistic equals
`z` — in `Decimal` at 40 digits:

    (p_hat - p)^2 = z^2 * p * (1 - p) / n
    =>  (1 + z^2/n) p^2  -  (2 p_hat + z^2/n) p  +  p_hat^2  =  0

Different algebra, different arithmetic, same interval. If the two agree to
nine decimal places on 24 cells, the closed form in `stats.py` is right.

The inputs are `design/results/README.md`'s own fixture table, so the file also
cross-checks the design's published macro averages (5.808/7, 5.749/7, 5.416/7).

**Treat a diff to `golden_stats.json` the way H2's schema snapshot is treated:
part of the PR, never a silent regeneration.**
"""

import json
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 40

#: The same constant `stats.WILSON_Z_95` carries, written independently here.
#: Two-sided 95 %: the 0.975 quantile of the standard normal.
Z = Decimal("1.959963985")

#: `design/results/README.md` §1a, verbatim: feature -> (source label, n,
#: {model: F1}). `right_of_way` is the suppression case — 17 labelled cases,
#: below the floor of 20 — and carries no F1s at all, because a suppressed
#: cell has no point estimate (§16.4).
FIXTURE: dict[str, tuple[str, int, dict[str, str]]] = {
    "weather": (
        "Witter0Ausw · enum",
        1842,
        {"qwen3:14b": "0.842", "mistral-small:24b": "0.831", "gemma3:12b": "0.744"},
    ),
    "light_conditions": (
        "LichtVerhAusw · enum",
        2004,
        {"qwen3:14b": "0.911", "mistral-small:24b": "0.903", "gemma3:12b": "0.898"},
    ),
    "road_condition": (
        "StrZu0Ausw · enum",
        1611,
        {"qwen3:14b": "0.688", "mistral-small:24b": "0.752", "gemma3:12b": "0.640"},
    ),
    "main_cause": (
        "HauptUrsaAusw · enum",
        3902,
        {"qwen3:14b": "0.594", "mistral-small:24b": "0.587", "gemma3:12b": "0.501"},
    ),
    "vehicles_involved": (
        "derived · count_objects · integer",
        4978,
        {"qwen3:14b": "0.939", "mistral-small:24b": "0.921", "gemma3:12b": "0.884"},
    ),
    "bicycle_involved": (
        "derived · any_object_matches · boolean",
        4978,
        {"qwen3:14b": "0.963", "mistral-small:24b": "0.967", "gemma3:12b": "0.959"},
    ),
    "speed_limit": (
        "HoechstGeschwKmHFeld · integer",
        4512,
        {"qwen3:14b": "0.812", "mistral-small:24b": "0.847", "gemma3:12b": "0.790"},
    ),
    "right_of_way": ("VortrittAusw · enum", 17, {}),
}

MIN_CELL_COUNT = 20


def wilson_by_quadratic(p_hat: Decimal, n: int) -> tuple[Decimal, Decimal]:
    """The two roots of the Wilson quadratic. Deliberately not the closed form."""
    z2_over_n = Z * Z / Decimal(n)
    a = Decimal(1) + z2_over_n
    b = -(Decimal(2) * p_hat + z2_over_n)
    c = p_hat * p_hat
    discriminant = b * b - Decimal(4) * a * c
    # Never negative for p_hat in [0, 1]; guard against a -1e-41 from rounding.
    root = (discriminant if discriminant > 0 else Decimal(0)).sqrt()
    low = (-b - root) / (Decimal(2) * a)
    high = (-b + root) / (Decimal(2) * a)
    return max(Decimal(0), low), min(Decimal(1), high)


def main() -> None:
    cells: dict[str, dict[str, object]] = {}
    per_model_f1: dict[str, list[Decimal]] = {}

    for feature, (source_label, n, f1_by_model) in FIXTURE.items():
        suppressed = n < MIN_CELL_COUNT
        entry: dict[str, object] = {
            "source_label": source_label,
            "n": n,
            "suppressed": suppressed,
            "models": {},
        }
        for model, f1_text in sorted(f1_by_model.items()):
            f1 = Decimal(f1_text)
            # `successes` is what `stats.wilson` is actually handed: the
            # product stores counts, and the F1 is the proportion they make.
            successes = int((f1 * n).to_integral_value())
            low, high = wilson_by_quadratic(Decimal(successes) / Decimal(n), n)
            entry["models"][model] = {  # type: ignore[index]
                "f1": f1_text,
                "successes": successes,
                "ci_low": f"{low:.9f}",
                "ci_high": f"{high:.9f}",
            }
            if not suppressed:
                per_model_f1.setdefault(model, []).append(f1)
        cells[feature] = entry

    macros = {
        model: {
            "sum": f"{sum(values):.3f}",
            "count": len(values),
            "macro_f1": f"{sum(values) / Decimal(len(values)):.9f}",
        }
        for model, values in sorted(per_model_f1.items())
    }

    payload = {
        "_comment": (
            "Generated by generate_golden_stats.py — an INDEPENDENT quadratic-root "
            "derivation in Decimal, not a recording of ra2.domain.stats. A diff here "
            "belongs in the PR; never regenerate it silently."
        ),
        "z_95": str(Z),
        "min_cell_count": MIN_CELL_COUNT,
        "cells": cells,
        "macros": macros,
    }
    out = Path(__file__).with_name("golden_stats.json")
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
