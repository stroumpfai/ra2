"""M27 (phase 4 Wave 0) exit criteria, as tests (plan-phase-4.md §5.2).

Owned by the lead, same reasoning as `test_m0_contract.py`,
`test_p2_contract.py` and `test_p3_contract.py`: a Wave 1+ agent should never
need to touch this file, and a failure here means a frozen contract was edited
without an amendment.
"""

import importlib
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table, UniqueConstraint

from ra2.domain.scoring import ALL_LANGUAGES, COUNT_METRICS, ScoreMetric
from ra2.persistence.models import Evaluation, Mismatch, Score
from ra2.services.readmodels import MetricCell, SuppressedCell

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_MD = REPO_ROOT / "CONTRACTS.md"

FROZEN_HEADER = "# FROZEN"

#: Every file this wave freezes (plan-phase-4.md §5.1), excluding the ones the
#: earlier contract tests already cover.
NEW_FROZEN_MODULES = [
    "ra2/domain/stats.py",
    "ra2/domain/ranking.py",
    "ra2/domain/matching.py",
    "ra2/domain/scoring.py",
    "ra2/domain/derivation.py",
]

#: Amended, already covered by the earlier contract tests' header checks —
#: re-asserted here so a Wave 0 diff that drops a header is caught locally.
AMENDED_FROZEN_MODULES = [
    "ra2/domain/ids.py",
    "ra2/persistence/models.py",
    "ra2/services/protocols.py",
    "ra2/services/container.py",
    "ra2/services/errors.py",
    "ra2/services/readmodels.py",
    "ra2/services/export_service.py",
    "ra2/api/deps.py",
    "ra2/api/v1/router.py",
    "ra2/main.py",
]

#: New, not frozen — a body is expected from Wave 1+ (plan-phase-4.md §6).
NEW_STUB_MODULES = [
    "ra2/services/scoring_service.py",
    "ra2/services/results_service.py",
    "ra2/services/ranking_service.py",
    "ra2/persistence/repositories/score_repo.py",
    "ra2/persistence/repositories/mismatch_repo.py",
    "ra2/persistence/repositories/ground_truth_repo.py",
    "ra2/api/v1/results.py",
    "ra2/api/v1/presence.py",
    "ra2/api/v1/ranking.py",
    "ra2/ui/views/results/__init__.py",
    "ra2/ui/views/results/extraction_tab.py",
    "ra2/ui/views/results/presence_tab.py",
    "ra2/ui/views/results/ranking_tab.py",
    "ra2/ui/components/stat_cells.py",
    "ra2/ui/components/contingency_table.py",
]


@pytest.mark.parametrize("relative_path", NEW_FROZEN_MODULES + AMENDED_FROZEN_MODULES)
def test_frozen_module_carries_the_header(relative_path):
    path = REPO_ROOT / relative_path
    assert path.exists(), f"{relative_path} is missing"
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith(FROZEN_HEADER), (
        f"{relative_path} must start with '{FROZEN_HEADER}...' — see CONTRACTS.md"
    )
    assert "CONTRACTS.md" in first_line


@pytest.mark.parametrize("relative_path", NEW_STUB_MODULES)
def test_stub_module_carries_the_header(relative_path):
    path = REPO_ROOT / relative_path
    assert path.exists(), f"{relative_path} is missing"
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("# STUB"), f"{relative_path} must start with '# STUB...'"


@pytest.mark.parametrize("relative_path", NEW_FROZEN_MODULES + NEW_STUB_MODULES)
def test_contracts_md_lists_every_new_file(relative_path):
    text = CONTRACTS_MD.read_text(encoding="utf-8")
    assert relative_path in text, f"CONTRACTS.md does not list {relative_path}"


@pytest.mark.parametrize("relative_path", NEW_FROZEN_MODULES + NEW_STUB_MODULES)
def test_every_new_module_imports(relative_path):
    module = relative_path.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
    imported = importlib.import_module(module)
    for name in getattr(imported, "__all__", ()):
        assert hasattr(imported, name), f"{module}.__all__ names a missing {name}"


def test_claude_md_names_all_four_migration_authors():
    """One migration author per phase, and the list has to grow with the
    phases (plan-phase-4.md §2.4)."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "A3 for phase 1" in text
    assert "D3 for phase 2" in text
    assert "H3 for phase 3" in text
    assert "S4 for phase 4" in text


def test_the_phase_4_revision_is_wired_into_the_chain():
    """One phase-4 revision, chained onto phase 3's — not orphaned and not a
    second head (plan-phase-4.md §5.2, CLAUDE.md's one-author rule)."""
    versions_dir = REPO_ROOT / "ra2/persistence/migrations/versions"
    revisions = [p for p in versions_dir.glob("*.py") if "phase_4_scoring_and_results" in p.name]
    assert len(revisions) == 1
    text = revisions[0].read_text(encoding="utf-8")
    assert 'down_revision: str | None = "9e90e50a151f"' in text
    #: The constraint that carries the invariant rather than tidiness: it is
    #: what makes the tag-preserving upsert expressible (§16.6, SD21).
    normalised = " ".join(text.split())
    assert '"run_id", "record_id", "feature_id", name=op.f("uq_mismatch' in normalised, (
        "UNIQUE (run_id, record_id, feature_id) is what makes the upsert expressible"
    )
    #: `NOT NULL` on an existing table needs a value for the rows already
    #: there, and the ORM declares no server default, so it must be dropped
    #: again or `alembic check` fails (plan-phase-4.md §5.2).
    assert 'server_default="20"' in text
    assert "server_default=None" in text


def test_pyproject_gained_no_dependency_this_phase():
    """§15 F10 — the first phase since M0 to add none.

    Wilson is a closed form over one constant; `scipy` would be the largest
    dependency in the project, added for one number. A decision with no gate
    behind it is a preference, so this is the gate (plan-phase-4.md §5.2).
    """
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "scipy" not in text
    assert "numpy" not in text
    assert "statsmodels" not in text


def test_importlinter_gained_no_contract_this_phase():
    """The layer rule already forbids everything this phase could get wrong.

    `domain/ranking.py` cannot reach a session, a repository or a second source
    of numbers, because `domain` may import stdlib and `pydantic` and nothing
    else in `ra2/` — which is what makes §16.5's "ranking is a derivation"
    structural rather than aspirational (plan-phase-4.md §2.4).
    """
    text = (REPO_ROOT / ".importlinter").read_text(encoding="utf-8")
    assert text.count("[importlinter:contract:") == 7


def test_score_metric_is_closed_and_carries_counts_as_well_as_rates():
    """SD18. A metric this enum does not name cannot be written, and a tab
    asking for one that does not exist is a lint error in Wave 4 rather than a
    `KeyError` in front of an analyst."""
    assert len(list(ScoreMetric)) == 16
    #: Goal 1's three rates and its three raw counts. The counts are stored,
    #: not back-derived from P and R — that is off by one exactly at small `n`.
    for name in ("PRECISION", "RECALL", "F1", "HIT", "WRONG", "MISSING"):
        assert hasattr(ScoreMetric, name)
    #: The cross-tab's six cells, as counts.
    assert {m for m in ScoreMetric if m.value.endswith(("_present", "_absent"))} <= COUNT_METRICS
    #: A count has no interval, and a renderer must not reach for one.
    assert ScoreMetric.F1 not in COUNT_METRICS
    assert ScoreMetric.PRESENCE_RATE not in COUNT_METRICS


def test_there_is_no_presence_f1_metric():
    """`D2`, mvp-spec.md §11.2: there is no independent gold label for
    presence, and deriving one from Goal 1 correctness would be circular.

    The deferral is only real if the metric is unnameable — a `presence_f1`
    that existed would be computed by someone eventually.
    """
    names = {m.value for m in ScoreMetric}
    assert "presence_f1" not in names
    assert "presence_precision" not in names
    assert "presence_recall" not in names


def test_there_is_no_hallucination_metric():
    """`D1`, mvp-spec.md §11.1: not computable without span adjudication.

    "Reports must not present a hallucination rate as if it were measured."
    It is a review tag on the mismatch list, never a `ScoreMetric`.
    """
    assert "hallucination" not in {m.value for m in ScoreMetric}
    assert "hallucination_rate" not in {m.value for m in ScoreMetric}


def test_score_language_is_not_nullable_and_has_a_sentinel():
    """SD16. mvp-spec.md §5 writes `language|NULL`, which cannot carry a
    composite primary key: SQL treats two NULLs as distinct in a unique
    constraint, so the schema that looks like it prevents duplicate rows would
    permit them — and a re-score would orphan the old ones every time."""
    assert Score.__table__.c.language.nullable is False
    assert ALL_LANGUAGES == "*"
    assert [c.name for c in Score.__table__.primary_key] == [
        "run_id",
        "feature_id",
        "language",
        "metric",
    ]


def test_there_is_no_scoring_status_column_anywhere():
    """§16.1, F5 — the same reasoning §15.3 used to refuse `records_done`.

    "Is this run scored" is `COUNT(DISTINCT feature_id)` over `score`. A
    counter is a second source of truth an interrupted pass can desynchronise,
    and the count that answers "how far did it get" is the same one that
    answers "where does it resume".
    """
    from ra2.persistence.models import Run

    assert "scored_at" not in Run.__table__.c
    assert "scored" not in Run.__table__.c
    assert "score_status" not in Run.__table__.c


def test_mismatch_keeps_the_review_columns_and_a_unique_key():
    """SD21 — the one mutable row, and the constraint that makes the
    tag-preserving upsert expressible (§16.6)."""
    for column in ("analyst_tag", "tagged_at", "note"):
        assert column in Mismatch.__table__.c
        assert Mismatch.__table__.c[column].nullable is True
    uniques = [
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in cast(Table, Mismatch.__table__).constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert ("feature_id", "record_id", "run_id") in uniques


def test_min_cell_count_is_per_evaluation():
    """Q4 / F6 — mvp-spec.md §11.4 says "configurable **per evaluation**", and
    a column is cheap because suppression is applied at read time (SD19), so
    changing the floor never requires a re-score."""
    assert "min_cell_count" in Evaluation.__table__.c
    assert Evaluation.__table__.c.min_cell_count.nullable is False


def test_a_suppressed_cell_has_no_value_field():
    """mvp-spec.md §11.4: "never as a number".

    The cheapest way to keep that true through four layers is for the number
    not to exist in the shape at all — so a suppressed cell cannot be
    formatted into a string by accident, and cannot be sorted as zero (R7).
    """
    assert not hasattr(SuppressedCell(n=17, floor=20), "value")
    assert set(SuppressedCell.__slots__) == {"n", "floor"}
    #: The floor travels with it because it is per-evaluation — a renderer
    #: that hard-coded 20 would be wrong the first time someone changed it.
    assert hasattr(MetricCell(value=0.5, ci_low=0.4, ci_high=0.6, n=40), "value")


def test_presence_rows_cannot_omit_their_goal_1_companions():
    """mvp-spec.md §11.2: "Goal 2 numbers are **never published without the
    corresponding Goal 1 numbers** — a weak extractor manufactures false
    'missing' flags."

    A required field rather than an optional one, so dropping the column is a
    type error and not an edit.
    """
    import dataclasses

    from ra2.services.readmodels import PresenceRow

    goal1 = next(f for f in dataclasses.fields(PresenceRow) if f.name == "goal1")
    assert goal1.default is dataclasses.MISSING
    assert goal1.default_factory is dataclasses.MISSING


def test_services_bundle_has_the_three_new_fields(app_factory):
    """A fresh `create_app()` still builds; `Services` has three more fields,
    all satisfiable by the new stub classes (plan-phase-4.md §5.2)."""
    app = app_factory(mount_ui=False)
    services = app.state.services
    assert services.scoring is not None
    assert services.results is not None
    assert services.ranking is not None


def test_the_nav_still_has_eight_items():
    """The first phase since M0 that adds no nav entry: `results` and
    `mismatches` have existed since phase 1 with `built=False`, and V1 flips
    exactly one flag in Wave 4 (plan-phase-4.md §6.1)."""
    from ra2.ui.shell import NAV_ITEMS

    keys = [item.key for item in NAV_ITEMS]
    assert len(keys) == 8
    results = next(i for i in NAV_ITEMS if i.key == "results")
    assert results.group == "Review"
    assert results.path == "/results"
