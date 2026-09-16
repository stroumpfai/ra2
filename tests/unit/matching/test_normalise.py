"""`domain.matching` — mvp-spec.md §8.4's normalisation table, one test per
value type, each carrying its hazard.

Phase 2 stored the `MatchingRule` shape and never compared two values with it.
This is where the comparison lives.
"""

import pytest

from ra2.domain.feature import MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.matching import is_empty, matches, normalise

EXACT = MatchingRule(kind=MatchingRuleKind.EXACT)


def norm(value: str | None, value_type: ValueType, rule: MatchingRule = EXACT) -> str | None:
    return normalise(value, value_type=value_type, rule=rule)


# --- is_empty: the §8.6 predicate ------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   ", "\t", "\n"])
def test_is_empty_accepts_no_value_at_all(value):
    assert is_empty(value) is True


@pytest.mark.parametrize("value", ["0", "false", "-", "n/a", " x "])
def test_is_empty_rejects_values_that_merely_look_like_nothing(value):
    """**The distinction that decides denominators.**

    `"0"` is a measurement. So is `"false"`. `"n/a"` is a string the officer
    typed. None of them is "no value was provided" (§8.6), and treating any of
    them as empty would silently remove records from a feature's `n`.
    """
    assert is_empty(value) is False


# --- enum ------------------------------------------------------------------


def test_enum_codes_are_compared_as_they_stand():
    """§8.4: "none — codes compared". A code is an identifier."""
    assert norm("01", ValueType.ENUM) == "01"


def test_enum_does_not_strip_leading_zeros():
    """`01` and `1` are different codes if the codelist says so, and merging
    them is not this function's call to make."""
    assert norm("01", ValueType.ENUM) != norm("1", ValueType.ENUM)


def test_enum_does_not_case_fold():
    """Case-folding a code would merge two codes the codelist separates."""
    assert norm("A1", ValueType.ENUM) != norm("a1", ValueType.ENUM)


# --- integer ---------------------------------------------------------------


@pytest.mark.parametrize("value", ["1250", " 1250 ", "1'250", "1 250", "1 250"])
def test_integer_strips_every_separator_the_delivery_uses(value):
    """The apostrophe is the Swiss thousands separator, and it is exactly what
    a naive `int(value)` chokes on."""
    assert norm(value, ValueType.INTEGER) == "1250"


def test_integer_normalises_leading_zeros():
    assert norm("0050", ValueType.INTEGER) == "50"


def test_an_unparseable_integer_keeps_its_text_rather_than_becoming_none():
    """**Never `None` for a value that failed to parse** — only for an empty
    one. A `None` here means "not a labelled case", so mapping `"abc"` in an
    integer column to `None` would quietly delete the record from the
    denominator instead of scoring it wrong.
    """
    assert norm("abc", ValueType.INTEGER) == "abc"


def test_two_sides_that_are_both_unparseable_and_identical_do_match():
    """The record is authoritative and says `"abc"`; a model that read `"abc"`
    read it correctly."""
    assert matches("abc", "abc", value_type=ValueType.INTEGER, rule=EXACT) is True


# --- decimal ---------------------------------------------------------------


def test_decimal_trailing_zeros_do_not_change_the_number():
    assert norm("1.50", ValueType.DECIMAL) == norm("1.5", ValueType.DECIMAL)


def test_decimal_accepts_a_comma_as_the_separator():
    """Swiss and French input write `1,5`."""
    assert norm("1,5", ValueType.DECIMAL) == norm("1.5", ValueType.DECIMAL)


def test_decimal_rounds_to_the_rules_precision():
    rule = MatchingRule(kind=MatchingRuleKind.EXACT, decimal_precision=2)
    assert norm("2.675", ValueType.DECIMAL, rule) == "2.68"


def test_decimal_rounding_uses_decimal_not_float():
    """`round(2.675, 2)` is `2.67` in binary floating point. The number anyone
    means is 2.68, which is why this path is `Decimal`."""
    rule = MatchingRule(kind=MatchingRuleKind.EXACT, decimal_precision=2)
    assert norm("2.675", ValueType.DECIMAL, rule) != str(round(2.675, 2))


def test_decimal_at_the_rounding_boundary_matches_across_representations():
    rule = MatchingRule(kind=MatchingRuleKind.EXACT, decimal_precision=1)
    assert matches("1.44", "1.4", value_type=ValueType.DECIMAL, rule=rule) is True
    assert matches("1.46", "1.4", value_type=ValueType.DECIMAL, rule=rule) is False


# --- date ------------------------------------------------------------------


def test_date_converts_the_delivery_format_to_iso():
    assert norm("20260902", ValueType.DATE) == "2026-09-02"


def test_an_already_iso_date_passes_through():
    assert norm("2026-09-02", ValueType.DATE) == "2026-09-02"


def test_the_two_date_representations_match_each_other():
    assert matches("20260902", "2026-09-02", value_type=ValueType.DATE, rule=EXACT) is True


def test_an_impossible_date_keeps_its_text_rather_than_raising():
    """A scoring pass walks a whole corpus; the 30th of February must score
    wrong, not stop the run."""
    assert norm("20260230", ValueType.DATE) == "20260230"


# --- time ------------------------------------------------------------------


def test_time_becomes_minutes_since_midnight():
    assert norm("07:35", ValueType.TIME) == "455"


def test_the_two_time_representations_match_each_other():
    assert matches("07:35", "0735", value_type=ValueType.TIME, rule=EXACT) is True


def test_time_tolerance_is_applied_when_the_rule_asks_for_it():
    """§8.4's one exception to equality, and it is a property of the rule
    rather than a second matching mode."""
    rule = MatchingRule(kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=5)
    assert matches("07:35", "07:38", value_type=ValueType.TIME, rule=rule) is True


def test_time_tolerance_is_exclusive_beyond_its_bound():
    rule = MatchingRule(kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=5)
    assert matches("07:35", "07:41", value_type=ValueType.TIME, rule=rule) is False


def test_time_at_exactly_the_tolerance_bound_matches():
    rule = MatchingRule(kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=5)
    assert matches("07:35", "07:40", value_type=ValueType.TIME, rule=rule) is True


def test_an_exact_time_rule_ignores_any_stray_tolerance():
    """A tolerance on an `EXACT` rule is not a quiet upgrade to fuzzy."""
    rule = MatchingRule(kind=MatchingRuleKind.EXACT, tolerance_minutes=30)
    assert matches("07:35", "07:38", value_type=ValueType.TIME, rule=rule) is False


# --- boolean ---------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Ja", "oui", "yes"])
def test_boolean_truthy_mapping(value):
    assert norm(value, ValueType.BOOLEAN) == "true"


@pytest.mark.parametrize("value", ["0", "false", "Nein", "non", "no"])
def test_boolean_falsy_mapping(value):
    assert norm(value, ValueType.BOOLEAN) == "false"


def test_a_derived_boolean_meets_a_models_answer_on_the_same_ground():
    """`domain.derivation` renders `"true"`/`"false"`; a model may write
    `"Ja"`. They have to compare equal."""
    assert matches("true", "Ja", value_type=ValueType.BOOLEAN, rule=EXACT) is True


# --- free text -------------------------------------------------------------


def test_free_text_collapses_whitespace_and_case_folds():
    assert norm("SCHNEE   FALL", ValueType.FREE_TEXT) == "schnee fall"


def test_free_text_strips_edge_punctuation_only():
    """An inner hyphen is part of the word; a trailing full stop is not."""
    assert norm("  Schnee-fall.  ", ValueType.FREE_TEXT) == "schnee-fall"


def test_free_text_applies_nfkc():
    """Composed and decomposed forms of the same string are the same string."""
    assert norm("Straße", ValueType.FREE_TEXT) == norm("Straße", ValueType.FREE_TEXT)
    assert norm("éte", ValueType.FREE_TEXT) == norm("éte", ValueType.FREE_TEXT)


def test_free_text_does_not_fold_accents():
    """**Deliberately off** (`D6`, §8.4). Accent folding is flagged as "worth
    evaluating, because it interacts with §4.4 damage" — and evaluating it
    means having the numbers this phase is the first to produce. Turning it on
    now would decide the question by assuming the answer.

    This is also the French hazard seen from the matching side: the upstream
    cp1252 conversion damages accented characters, so folding them would make
    a French corpus look better matched than it is.
    """
    assert norm("Glätteis", ValueType.FREE_TEXT) != norm("Glatteis", ValueType.FREE_TEXT)
    assert matches("vergé", "verge", value_type=ValueType.FREE_TEXT, rule=EXACT) is False


def test_free_text_does_no_fuzzy_matching():
    """`D6`: "normalised exact, no fuzzy". One character apart is wrong."""
    assert matches("schneefall", "schneefal", value_type=ValueType.FREE_TEXT, rule=EXACT) is False


def test_free_text_that_is_only_punctuation_does_not_become_none():
    """Stripping edge punctuation can empty a value that was not empty on the
    way in. It must not turn into `None` — that would move the record out of
    the denominator on a normalisation step (§8.6)."""
    assert norm("...", ValueType.FREE_TEXT) is not None


# --- empties ---------------------------------------------------------------


@pytest.mark.parametrize("value_type", list(ValueType))
def test_every_value_type_normalises_an_empty_value_to_none(value_type):
    assert norm("", value_type) is None
    assert norm(None, value_type) is None


@pytest.mark.parametrize("value_type", list(ValueType))
def test_matching_against_an_empty_side_is_never_a_hit(value_type):
    assert matches("", "x", value_type=value_type, rule=EXACT) is False
    assert matches("x", None, value_type=value_type, rule=EXACT) is False
