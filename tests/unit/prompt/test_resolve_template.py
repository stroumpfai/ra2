"""`ra2.domain.prompt.resolve_template` (sw-design.md §15.1).

Pure, single-pass substitution: a narrative containing `{{` is text, not a
slot, and must never be re-expanded.
"""

import pytest

from ra2.domain.prompt import SlotName, resolve_template

pytestmark = pytest.mark.unit


def test_expands_every_recognised_slot():
    resolved = resolve_template(
        "A {{feature_block}} B {{narrative}} C {{language}} D",
        blocks={
            SlotName.FEATURE_BLOCK: "FB",
            SlotName.NARRATIVE: "NARR",
            SlotName.LANGUAGE: "de",
        },
    )
    assert resolved.text == "A FB B NARR C de D"


def test_slots_used_reports_only_slots_actually_present_in_catalogue_order():
    resolved = resolve_template(
        "{{narrative}} then {{feature_block}}",
        blocks={SlotName.FEATURE_BLOCK: "FB", SlotName.NARRATIVE: "NARR", SlotName.LANGUAGE: "de"},
    )
    # Catalogue order is FEATURE_BLOCK, NARRATIVE, LANGUAGE (SLOTS' own order),
    # regardless of the order the tokens appear in the source.
    assert resolved.slots_used == (SlotName.FEATURE_BLOCK, SlotName.NARRATIVE)


def test_a_slot_with_no_entry_in_blocks_resolves_to_empty_string():
    resolved = resolve_template("[{{language}}]", blocks={})
    assert resolved.text == "[]"


def test_an_unrecognised_token_is_left_exactly_as_written():
    resolved = resolve_template("{{corpus}} {{narrative}}", blocks={SlotName.NARRATIVE: "NARR"})
    assert resolved.text == "{{corpus}} NARR"


def test_token_estimate_matches_estimate_tokens_of_the_resolved_text():
    from ra2.domain.prompt import estimate_tokens

    resolved = resolve_template("{{narrative}}", blocks={SlotName.NARRATIVE: "hello world"})
    assert resolved.token_estimate == estimate_tokens(resolved.text)


def test_p07_narrative_containing_a_literal_double_brace_is_never_re_expanded(ph):
    """The single-pass proof. The narrative fixture literally contains the
    text `{{narrative}}` — if substitution recursed into already-substituted
    text, this would either loop or silently swap the record's own quoted
    text for something else. It must appear in the output byte-for-byte."""
    source = ph.source("p07_narrative_literal_braces")
    narrative = ph.narrative("p07_narrative_literal_braces")
    assert "{{narrative}}" in narrative  # the fixture actually carries the hazard

    resolved = resolve_template(
        source, blocks={SlotName.FEATURE_BLOCK: "FB", SlotName.NARRATIVE: narrative}
    )

    assert resolved.text == source.replace("{{feature_block}}", "FB").replace(
        "{{narrative}}", narrative
    )
    # The literal braces from the record text survive untouched.
    assert '"{{narrative}}"' in resolved.text
    # And resolving again over the *result* would find a second, un-intended
    # slot to expand — proof this function did not do that itself.
    assert resolved.text.count("{{narrative}}") == 1
