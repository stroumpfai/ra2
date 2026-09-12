"""The two validation tiers (mvp-spec.md §7/§8.1/§8.2).

Tier 1 is corpus-independent and always checked. Tier 2 — "does this enum
column actually have codes" — needs a corpus to ask, and runs only when the
caller passes `validate_against`.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.codelist_coverage import CoverageStatus
from ra2.domain.feature import (
    EXPLORATORY_FEATURE_CAP,
    Grain,
    Kind,
    MatchingRule,
    MatchingRuleKind,
    MaxOrdinal,
    ValueType,
)
from ra2.services.feature_service import (
    FEATURE_ERROR_EXPLORATORY_CAP,
    FEATURE_ERROR_NO_CODELIST,
    FEATURE_ERROR_NON_SCALAR_GRAIN,
)

pytestmark = pytest.mark.backend

#: An exploratory feature: description only, no counterpart, no ground truth
#: to match against (design, Case D).
EXPLORATORY = {
    "kind": Kind.EXPLORATORY,
    "grain": Grain.ACCIDENT,
    "source_column": None,
    "value_type": ValueType.FREE_TEXT,
    "matching_rule": MatchingRule(kind=MatchingRuleKind.NONE),
}


@pytest.mark.parametrize("grain", [Grain.OBJECT, Grain.PERSON])
@pytest.mark.parametrize("with_corpus", [False, True])
async def test_a_labelled_feature_at_a_non_scalar_grain_blocks(
    draft_with, codelist_provider, column_coverage, validation_corpus, grain, with_corpus
):
    """The design's "Damage per vehicle · non-scalar ERROR". This tier never
    depends on `validate_against`, so it fires either way."""
    codelist_provider.answers["SchadenAusw"] = column_coverage(CoverageStatus.OK)

    view = await draft_with(
        {"key": "damage_per_vehicle", "grain": grain, "source_column": "SchadenAusw"},
        validate_against=validation_corpus if with_corpus else None,
    )

    assert view.features[0].validation_errors == (
        FEATURE_ERROR_NON_SCALAR_GRAIN.format(key="damage_per_vehicle", grain=grain.value),
    )


@pytest.mark.parametrize("grain", [Grain.ACCIDENT, Grain.DERIVED])
async def test_a_labelled_feature_at_a_scalar_grain_is_clean(draft_with, grain):
    view = await draft_with({"grain": grain, "value_type": ValueType.INTEGER})

    assert view.features[0].validation_errors == ()


async def test_an_exploratory_feature_is_never_blocked_by_grain(draft_with):
    """§8.1: exploratory features have no structured counterpart, so "scored
    at a non-scalar grain" cannot apply to one."""
    view = await draft_with({**EXPLORATORY, "grain": Grain.OBJECT})

    assert view.features[0].validation_errors == ()


async def test_the_exploratory_cap_blocks_the_twenty_first(feature_service, draft_with):
    """§8.1 caps exploratory features at 20 per set. The cap is a property of
    the draft, so it is reported on the rows past it — what the design's
    per-row error state renders."""
    view = await draft_with(
        *[{**EXPLORATORY, "key": f"probe_{n:02d}"} for n in range(EXPLORATORY_FEATURE_CAP + 1)]
    )

    assert len(view.features) == EXPLORATORY_FEATURE_CAP + 1
    assert all(f.validation_errors == () for f in view.features[:EXPLORATORY_FEATURE_CAP])
    assert view.features[EXPLORATORY_FEATURE_CAP].validation_errors == (
        FEATURE_ERROR_EXPLORATORY_CAP.format(key="probe_20", cap=EXPLORATORY_FEATURE_CAP),
    )


async def test_labelled_features_do_not_count_against_the_cap(draft_with):
    view = await draft_with(
        *[{"key": f"labelled_{n:02d}", "value_type": ValueType.INTEGER} for n in range(25)],
        *[{**EXPLORATORY, "key": f"probe_{n:02d}"} for n in range(EXPLORATORY_FEATURE_CAP)],
    )

    assert all(f.validation_errors == () for f in view.features)


async def test_an_unmapped_enum_column_is_silent_without_a_validation_corpus(
    draft_with, codelist_provider
):
    """A feature set carries no `corpus_id` (C3): it must stay authorable —
    and freezable — without ever naming one, so the tier is not run at all,
    rather than treated as passing or failing."""
    view = await draft_with({"key": "right_of_way", "source_column": "VortrittAusw"})

    assert view.features[0].validation_errors == ()
    assert codelist_provider.calls == []


async def test_an_unmapped_enum_column_blocks_against_a_corpus(
    draft_with, codelist_provider, validation_corpus
):
    """The design's "Right of way `VortrittAusw · no codes` accident ERROR".
    `None` from the provider means no mapping at all."""
    view = await draft_with(
        {"key": "right_of_way", "source_column": "VortrittAusw"},
        validate_against=validation_corpus,
    )

    assert view.features[0].validation_errors == (
        FEATURE_ERROR_NO_CODELIST.format(key="right_of_way", column="VortrittAusw"),
    )
    assert codelist_provider.columns_asked == ["VortrittAusw"]


@pytest.mark.parametrize(
    ("status", "blocks"),
    [
        (CoverageStatus.MISSING, True),
        (CoverageStatus.PARTIAL, False),
        (CoverageStatus.OK, False),
    ],
)
async def test_only_missing_coverage_blocks(
    draft_with, codelist_provider, column_coverage, validation_corpus, status, blocks
):
    """`PARTIAL` is the design's `--warn-soft` note — "the feature still runs;
    those records score against an unnamed code" — not a blocking error."""
    codelist_provider.answers["WitterungAusw"] = column_coverage(status)

    view = await draft_with({"key": "weather"}, validate_against=validation_corpus)

    assert bool(view.features[0].validation_errors) is blocks


async def test_a_non_enum_feature_is_never_asked_about_codes(
    draft_with, codelist_provider, validation_corpus
):
    await draft_with(
        {
            "key": "speed_limit",
            "source_column": "HoechstGeschwKmHFeld",
            "value_type": ValueType.INTEGER,
        },
        validate_against=validation_corpus,
    )

    assert codelist_provider.calls == []


async def test_a_derived_enum_without_a_source_column_is_not_asked_about_codes(
    draft_with, codelist_provider, validation_corpus
):
    """`max_ordinal` yields a code, but its column lives inside the
    derivation, which nothing executes in phase 2 (plan-phase-2.md Q1).
    Inventing a "no codes" error here would block a legitimate feature."""
    view = await draft_with(
        {
            "key": "worst_injury",
            "grain": Grain.DERIVED,
            "source_column": None,
            "derivation": MaxOrdinal(
                table="person", column="VerletzungsgradAusw", ordered_codes=("1", "2", "3")
            ),
        },
        validate_against=validation_corpus,
    )

    assert view.features[0].validation_errors == ()
    assert codelist_provider.calls == []


async def test_the_provider_is_handed_the_services_own_session(
    draft_with, codelist_provider, validation_corpus
):
    """The seam's contract, the same one `CensusMaterialiser` has: the callee
    is given the caller's session and transaction, and opens neither."""
    await draft_with({"key": "weather"}, validate_against=validation_corpus)

    session, corpus_id, source_column = codelist_provider.calls[0]
    assert isinstance(session, AsyncSession)
    assert (corpus_id, source_column) == (validation_corpus, "WitterungAusw")
    # The feature was flushed but not yet committed when the provider ran, so
    # seeing it proves the provider was handed the caller's own transaction
    # rather than a session of its own.
    assert codelist_provider.features_visible == [1]


async def test_get_reports_the_corpus_independent_tier_only(
    feature_service, draft_with, codelist_provider
):
    """`get()` takes no corpus, so it shows the tier that needs none."""
    view = await draft_with(
        {"key": "damage", "grain": Grain.OBJECT, "source_column": "SchadenAusw"},
        {"key": "right_of_way", "source_column": "VortrittAusw"},
    )

    read_back = await feature_service.get(view.feature_config_id)

    assert len(read_back.features[0].validation_errors) == 1
    assert read_back.features[1].validation_errors == ()
    assert codelist_provider.calls == []
