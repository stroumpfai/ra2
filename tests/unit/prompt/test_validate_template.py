"""`ra2.domain.prompt.validate_template` (sw-design.md §15.1, mvp-spec.md §10.2).

Pure, no I/O: takes a template source string and returns every problem found,
never just the first (Do-NOT list #6's "no silent repair" applied to a
prompt). Each hazard's fixture is loaded from the committed, synthetic files
under `tests/fixtures/prompts/hazards/` (p01-p07); asserted on
`PromptValidationCode`, never on message text (CLAUDE.md, "Findings, not
prose").
"""

import pytest

from ra2.domain.prompt import PromptValidationCode, validate_template

pytestmark = pytest.mark.unit


def test_p01_valid_template_with_all_three_slots_has_no_errors(ph):
    errors = validate_template(ph.source("p01_valid_all_slots"))
    assert errors == ()


def test_p02_missing_narrative_is_one_missing_required_slot_error(ph):
    errors = validate_template(ph.source("p02_missing_narrative"))
    assert len(errors) == 1
    assert errors[0].code is PromptValidationCode.MISSING_REQUIRED_SLOT
    assert errors[0].slot == "narrative"


def test_p03_unknown_slot_is_flagged_by_name_and_offset(ph):
    source = ph.source("p03_unknown_slot")
    errors = validate_template(source)
    assert len(errors) == 1
    assert errors[0].code is PromptValidationCode.UNKNOWN_SLOT
    assert errors[0].slot == "corpus"
    # The offset actually points at the "{{corpus}}" token.
    assert errors[0].offset is not None
    assert source[errors[0].offset :].startswith("{{corpus}}")


def test_p04_feature_block_twice_is_legal_a_duplicated_slot_is_not_an_error(ph):
    errors = validate_template(ph.source("p04_duplicate_feature_block"))
    assert errors == ()


def test_p05_half_brace_is_malformed_not_silently_treated_as_text(ph):
    """`{{narrative}` (a single closing brace) must never be silently ignored
    as plain text — it is a validation error, and specifically not the same
    error as an absent slot (that would send the analyst to add a slot that
    is, in fact, already there — just broken)."""
    errors = validate_template(ph.source("p05_half_brace"))
    assert len(errors) == 1
    assert errors[0].code is PromptValidationCode.MALFORMED_SLOT
    assert errors[0].slot == "narrative"


def test_blank_source_is_a_single_empty_source_error():
    errors = validate_template("")
    assert len(errors) == 1
    assert errors[0].code is PromptValidationCode.EMPTY_SOURCE


def test_whitespace_only_source_is_also_empty_source():
    errors = validate_template("   \n\t  \n")
    assert len(errors) == 1
    assert errors[0].code is PromptValidationCode.EMPTY_SOURCE


def test_missing_both_required_slots_reports_one_error_each():
    errors = validate_template("Just some prose, no slots at all.")
    codes = {e.code for e in errors}
    slots = {e.slot for e in errors}
    assert codes == {PromptValidationCode.MISSING_REQUIRED_SLOT}
    assert slots == {"feature_block", "narrative"}
    assert len(errors) == 2


def test_validate_template_never_raises_on_arbitrary_input():
    """Pure and total: nonsense input still returns a tuple, never raises."""
    for source in ("{{", "}}", "{{{{narrative}}}}", "{{feature_block}} {{ }}", "\x00\x01"):
        result = validate_template(source)
        assert isinstance(result, tuple)
