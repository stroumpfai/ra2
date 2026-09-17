"""M35 (phase 5 Wave 0) exit criteria, as tests (plan-phase-5.md §5.2).

Owned by the lead, the same reasoning as `test_m0_contract.py` through
`test_p4_contract.py`: a Wave 1+ agent should never need to touch this file,
and a failure here means a frozen contract was edited without an amendment.

Two of these carry more weight than the rest, and they are the two
`plan-phase-5.md` §5.3 sends the lead through line by line:

- **`test_review_has_no_edge_to_scoring`** — mvp-spec.md §12's "the tag never
  feeds back into a metric" is easy to state, convenient to violate with one
  import, and invisible once violated, because a number that moved because of
  a tag is not visibly wrong (sw-design.md §17.3, R3).
- **`test_the_tag_vocabulary_is_closed_over_an_open_column`** and its
  neighbours — a closed enum over an open column is a deliberate asymmetry
  (`SD24`), and it is wrong in both directions if only half of it lands.
"""

import ast
import importlib
import tomllib
from pathlib import Path

import pytest
from sqlalchemy import String

from ra2.domain.ids import FeatureId, MismatchId, RecordId
from ra2.domain.mismatch import (
    MISMATCH_SORT_KEYS,
    OTHER_TAG,
    MismatchTag,
    TagState,
)
from ra2.persistence.models import Mismatch
from ra2.services.readmodels import MismatchRowView

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_MD = REPO_ROOT / "CONTRACTS.md"

FROZEN_HEADER = "# FROZEN"

#: New and frozen at this wave (plan-phase-5.md §5.1). One file: this phase
#: adds one domain module and nothing else that is new *and* frozen.
NEW_FROZEN_MODULES = [
    "ra2/domain/mismatch.py",
]

#: Amended, already covered by the earlier contract tests' header checks —
#: re-asserted here so a Wave 0 diff that drops a header is caught locally.
AMENDED_FROZEN_MODULES = [
    "ra2/services/protocols.py",
    "ra2/services/container.py",
    "ra2/services/errors.py",
    "ra2/services/readmodels.py",
    "ra2/services/export_service.py",
    "ra2/api/schemas.py",
    "ra2/api/deps.py",
    "ra2/api/v1/router.py",
    "ra2/main.py",
]

#: New, not frozen — a body is expected from Wave 2+ (plan-phase-5.md §6).
NEW_STUB_MODULES = [
    "ra2/services/mismatch_service.py",
    "ra2/api/v1/mismatches.py",
    "ra2/ui/views/mismatches_view.py",
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


def test_claude_md_names_all_five_migration_authors():
    """One migration author per phase, and the list has to grow with the
    phases (plan-phase-5.md §2.4) — even though phase 5 expects to need no
    revision at all (C7)."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for author in ("A3 for phase 1", "D3 for phase 2", "H3 for phase 3", "S4 for phase 4"):
        assert author in text
    assert "W1 for phase 5" in text


def test_the_migration_chain_is_unchanged():
    """C7: `mismatch` exists with its unique key and its `(run_id, feature_id)`
    index since phase 4, so this phase expects **no revision**.

    If W1 finds the filtered list wants one more index, this test is the thing
    that has to be updated deliberately — which is the point. A new head that
    nobody noticed is how parallel migration authorship goes wrong (CLAUDE.md).
    """
    versions = sorted(
        p.name for p in (REPO_ROOT / "ra2/persistence/migrations/versions").glob("*.py")
    )
    assert len(versions) == 5, f"phase 5 adds no revision; found {versions}"
    assert any("phase_4_scoring_and_results" in name for name in versions)


# ---------------------------------------------------------------------------
# §15 F10 — no new dependency, no new lint contract, no new fixture.
# The second phase in a row to add none, and a decision with no gate behind it
# is a preference (plan-phase-4.md's F10, reapplied).
# ---------------------------------------------------------------------------


def test_pyproject_gained_no_dependency_this_phase():
    """The runtime dependency list is pinned here, in full.

    Phase 5 adds one domain module, one service, one router and one view over
    tables that already exist — there is nothing for a library to do. Asserting
    the whole list rather than the absence of three names makes an addition
    fail loudly instead of needing to be guessed at.
    """
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dependencies"] == [
        "fastapi>=0.115",
        "nicegui>=2.0",
        "uvicorn[standard]>=0.30",
        "sqlalchemy[asyncio]>=2.0",
        "aiosqlite>=0.20",
        "alembic>=1.13",
        "pydantic>=2.9",
        "pydantic-settings>=2.5",
        "lingua-language-detector>=2.0",
        "uuid-utils>=0.9",
        "openai>=3.0",
        "nvidia-ml-py>=13.0",
    ]


def test_importlinter_gained_no_contract_this_phase():
    """The layer rule already forbids everything this phase could get wrong.

    `domain/mismatch.py` cannot reach a session, a score or a statistic,
    because `domain` may import stdlib and `pydantic` and nothing else in
    `ra2/`. What `import-linter` *cannot* express is "this service may not
    import that service" — both are one layer — so §17.3's absent edge is
    asserted on the AST below instead (plan-phase-5.md §2.4).
    """
    text = (REPO_ROOT / ".importlinter").read_text(encoding="utf-8")
    assert text.count("[importlinter:contract:") == 7


def test_this_phase_added_no_service_error():
    """plan-phase-5.md §5.1: `errors.py` is **expected to add nothing**.

    Phases 2, 3 and 4 each added errors; a phase that adds none is a phase
    that introduced no new failure. An unknown mismatch is a `NotFoundError`
    like every other unknown id, an unknown tag never reaches the service
    because the wire is closed (`SD24`), and a tag that changes nothing
    downstream cannot conflict with anything.
    """
    from ra2.services import errors

    assert set(errors.__all__) == {
        "BlockingFindingsError",
        "CodelistImportError",
        "CorpusLockedError",
        "DeliveryCitedError",
        "DeliveryNotAnalysedError",
        "EvaluationLockedError",
        "FeatureConfigFrozenError",
        "FeatureValidationError",
        "LlmEndpointError",
        "NotFoundError",
        "PromptTemplateCitedError",
        "PromptTemplateInvalidError",
        "RunActiveError",
        "RunNotScoreableError",
        "RunNotScoredError",
        "ServiceError",
        "TaggedWorkPresentError",
    }


# ---------------------------------------------------------------------------
# §17.3 — the absent edge. The one this phase exists to keep absent.
# ---------------------------------------------------------------------------


def _imported_modules(relative_path: str) -> set[str]:
    tree = ast.parse((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_review_has_no_edge_to_scoring():
    """mvp-spec.md §12: "The tag never feeds back into a metric. Nothing is
    rescored." Expressed as an **absent import**, asserted on the AST.

    `import-linter` cannot express this — `mismatch_service` and
    `scoring_service` are the same layer — so the gate is a test, the same way
    the one-LLM-seam rule has an AST test on top of its contract (§15.5).

    This is R3's failure mode: the violation would be convenient, and the
    result would still look plausible. A tally that moved a number is not
    visibly wrong.
    """
    review = _imported_modules("ra2/services/mismatch_service.py")
    forbidden = {"ra2.services.scoring_service", "ra2.services.ranking_service"}
    assert not (review & forbidden), (
        f"mismatch_service must not import a scoring module; found {review & forbidden}"
    )
    #: The domain half: the tally cannot reach a score, an outcome or a
    #: statistic, so there is nothing for it to feed back into.
    domain = _imported_modules("ra2/domain/mismatch.py")
    assert not {n for n in domain if n.startswith("ra2.")}, (
        f"domain/mismatch.py imports nothing from ra2/; found {domain}"
    )


def test_the_tally_protocol_returns_counts_and_nothing_else():
    """§17.3, item 2: the absence *is* the contract.

    `MismatchTally` has exactly one method. A second one — "rescore these", "is
    this feature reliable" — is how the edge would arrive looking helpful.
    """
    from ra2.services.protocols import MismatchTally

    methods = {
        name
        for name in dir(MismatchTally)
        if not name.startswith("_") and callable(getattr(MismatchTally, name, None))
    }
    assert methods == {"tally"}


# ---------------------------------------------------------------------------
# SD24 — a closed enum over an open column, and the bucket that holds it up.
# ---------------------------------------------------------------------------


def test_the_tag_vocabulary_is_closed_over_an_open_column():
    """`SD24`, §17.5. Both halves, because the asymmetry is wrong in both
    directions if only one of them lands.

    The enum is what makes the list, the tally, the CSV and the wire agree on
    three identifiers. The `String(32)` column is what keeps `models.py`'s
    promise that "a fourth tag must be a value, not a migration".
    """
    assert [tag.value for tag in MismatchTag] == [
        "hallucination",
        "structured_data_error",
        "unclear",
    ]
    column = Mismatch.__table__.c.analyst_tag
    assert isinstance(column.type, String)
    assert column.type.length == 32
    assert column.nullable is True


def test_the_other_bucket_is_not_a_writable_tag():
    """§17.5. `OTHER_TAG` is a bucket, not a vocabulary word.

    If it were a `MismatchTag` member, a control would eventually offer it and
    an analyst would eventually pick it — and "other" is not a judgement, it is
    the absence of one that this codebase can name.
    """
    assert OTHER_TAG == "other"
    assert OTHER_TAG not in {tag.value for tag in MismatchTag}
    with pytest.raises(ValueError, match="other"):
        MismatchTag(OTHER_TAG)


def test_an_unrecognised_stored_tag_renders_and_counts():
    """§17.5's whole point: such a row is **never dropped and never raises**.

    A tally that silently omitted it would report "of 40 reviewed" over 38 —
    the one failure mode this asymmetry exists to avoid. The narrowing lives on
    the read model, in one place, rather than in four renderers (§17.8).
    """
    row = _row(analyst_tag="fourth_thing")
    assert row.tag is None
    assert row.is_other is True
    assert row.reviewed is True
    #: The stored string survives to the screen and to the CSV verbatim.
    assert row.analyst_tag == "fourth_thing"


def test_a_known_tag_narrows_and_an_absent_one_does_not_look_like_one():
    """`tag is None` means *either* untagged or unrecognised; `is_other` is
    what tells them apart, and `reviewed` is what the column renders."""
    known = _row(analyst_tag="unclear")
    assert known.tag is MismatchTag.UNCLEAR
    assert known.is_other is False
    assert known.reviewed is True

    untagged = _row(analyst_tag=None)
    assert untagged.tag is None
    assert untagged.is_other is False
    assert untagged.reviewed is False


def test_the_list_has_four_sort_keys_and_no_fifth():
    """C3 / §17.8. **Nothing sorts by "how wrong"** — there is no such number,
    and inventing one is §16.9's clustering / cross-model-agreement / sampling
    deferral arriving as a helpful-looking feature.

    A closed tuple is what makes that a test rather than a review comment.
    """
    assert MISMATCH_SORT_KEYS == ("feature", "record", "tag", "reviewed")
    banned = {"severity", "confidence", "score", "rank", "similarity", "cluster"}
    assert not banned & set(MISMATCH_SORT_KEYS)


def test_the_tag_filter_is_a_closed_state_plus_a_named_tag():
    """§17.5's last paragraph. The toolbar is one control with six options, so
    the filter is one field: three states, or one named tag.

    The two enums' values are disjoint, which is what lets the union
    discriminate itself in a repository without a second field to keep in
    sync.
    """
    assert [state.value for state in TagState] == ["any", "untagged", "tagged"]
    assert not {s.value for s in TagState} & {t.value for t in MismatchTag}


# ---------------------------------------------------------------------------
# §17.1 — the ownership split, from the side phase 4 could not assert.
# ---------------------------------------------------------------------------


def test_a_writer_of_derived_columns_cannot_name_a_review_column():
    """§17.1: the type is the guard, before the query is.

    `MismatchWrite` is what the scorer hands the repository, and it has no
    field for a tag — so the upsert that rewrites the derived three
    *structurally cannot* touch the review three. Phase 4 built this; phase 5
    is the half that makes the split symmetric, and the same assertion belongs
    on both sides.
    """
    import dataclasses

    from ra2.persistence.repositories.mismatch_repo import MismatchWrite

    fields = {f.name for f in dataclasses.fields(MismatchWrite)}
    assert fields == {"record_id", "record_value", "extracted_value", "evidence_span"}
    assert not fields & {"analyst_tag", "tagged_at", "note"}


def test_the_review_columns_are_still_the_only_mutable_ones():
    """`SD21`, re-asserted from phase 5's side. Three columns, all nullable,
    all preserved by a re-score."""
    for column in ("analyst_tag", "tagged_at", "note"):
        assert Mismatch.__table__.c[column].nullable is True


def test_there_is_still_no_scored_at_column():
    """`SD25`, §17.7. The staleness anchor is the run's `finished_at`; a
    re-score goes **undated**, and that gap is named rather than closed with a
    column §16.1 F5 declined.

    Asserted here as well as in `test_p4_contract.py` because this is the phase
    with the motive: an analyst watching a tally move is exactly who would ask
    for the column, and the answer is a count of tags lost, not a timestamp and
    not a lock (R5).
    """
    from ra2.persistence.models import Run

    assert "scored_at" not in Run.__table__.c
    assert "scored_at" not in Mismatch.__table__.c


# ---------------------------------------------------------------------------
# Surface — the wave adds surface and changes no behaviour.
# ---------------------------------------------------------------------------


def test_services_bundle_has_the_new_field(app_factory):
    """A fresh `create_app()` still builds, with one more field on `Services`
    satisfiable by the new stub class (plan-phase-5.md §5.2)."""
    app = app_factory(mount_ui=False)
    assert app.state.services.mismatch is not None


def test_the_nav_still_has_eight_items_and_mismatches_is_still_unbuilt():
    """§5.1: `shell.py` is **untouched** at Wave 0. `mismatches` has existed as
    a `NavItem` with `built=False` since phase 1, icon already wired; Z1 flips
    exactly that one flag in Wave 4 (§6.1)."""
    from ra2.ui.shell import NAV_ITEMS

    assert len(NAV_ITEMS) == 8
    item = next(i for i in NAV_ITEMS if i.key == "mismatches")
    assert item.group == "Review"
    assert item.path == "/mismatches"
    assert item.built is False


def test_the_tag_words_live_in_exactly_one_rendering_table():
    """C4. `MismatchTag` values are the stable identifiers; the words are
    `ui/`'s, the same arrangement `FindingCode` and `ProbeCode` have.

    mvp-spec.md §12's own example says **"record error"** where the enum says
    `structured_data_error`, and both have to be right at once — which is only
    possible if the identifier and the wording are different things.
    """
    from ra2.ui.views.mismatches_view import TAG_LABELS

    assert set(TAG_LABELS) == set(MismatchTag)
    assert TAG_LABELS[MismatchTag.STRUCTURED_DATA_ERROR] == "Record error"
    #: The identifier never appears on screen.
    assert "structured_data_error" not in set(TAG_LABELS.values())


def _row(*, analyst_tag: str | None) -> MismatchRowView:
    return MismatchRowView(
        mismatch_id=MismatchId("m1"),
        record_id=RecordId("r1"),
        anonymised=True,
        feature_id=FeatureId("f1"),
        feature_key="weather",
        record_value="rain",
        extracted_value="snow",
        evidence_span="it was snowing heavily",
        analyst_tag=analyst_tag,
        tagged_at=None,
        note=None,
    )
