"""`domain.code_label.decode` — a mismatch value against the launch snapshot
(`SD71`, `plan-mismatch-context.md` §3.1)."""

import pytest

from ra2.domain.code_label import UNDECODED, DecodedValue, LabelState, by_code, decode
from ra2.domain.codes import CodeValue

pytestmark = pytest.mark.unit

#: A code table with the hazards in it: a zero-padded code beside a bare one,
#: a code labelled only in French, and one whose German label is empty.
CODES = by_code(
    (
        CodeValue(attribute_key="weather", code="1", label={"de": "trocken", "fr": "sec"}),
        CodeValue(attribute_key="weather", code="04", label={"de": "Schnee", "fr": "neige"}),
        CodeValue(attribute_key="weather", code="7", label={"fr": "brouillard"}),
        CodeValue(attribute_key="weather", code="8", label={"de": "", "fr": "vent"}),
    )
)


def test_a_code_in_the_table_decodes_in_the_prompt_language() -> None:
    assert decode("1", CODES, "de") == DecodedValue(
        raw="1", label="trocken", state=LabelState.LABELLED, language="de"
    )
    assert decode("1", CODES, "fr").label == "sec"


def test_codes_match_exactly_and_a_padded_code_is_not_its_bare_neighbour() -> None:
    """mvp-spec.md §7: no coercion to the nearest code."""
    assert decode("04", CODES, "de").label == "Schnee"
    assert decode("4", CODES, "de").state is LabelState.NOT_IN_TABLE
    assert decode("01", CODES, "de").state is LabelState.NOT_IN_TABLE


def test_a_label_in_another_language_is_not_offered_in_its_place() -> None:
    """The model was asked in German. A French label would be words it was
    never given."""
    decoded = decode("7", CODES, "de")
    assert decoded.state is LabelState.NO_LABEL
    assert decoded.label is None
    assert decoded.language == "de"


def test_an_empty_label_is_what_the_model_was_shown_not_a_missing_one() -> None:
    """`render_feature_block` prints `[no de label]` only when the language
    is absent; an empty string it prints as it is. `no_label` has to mean the
    same thing, or the screen misstates what the model saw."""
    decoded = decode("8", CODES, "de")
    assert decoded.state is LabelState.LABELLED
    assert decoded.label == ""


def test_a_code_outside_the_table_is_said_to_be_outside_it() -> None:
    decoded = decode("99", CODES, "de")
    assert decoded.state is LabelState.NOT_IN_TABLE
    assert decoded.raw == "99"


def test_a_feature_with_no_snapshot_is_not_an_enum() -> None:
    assert decode("2", None, "de").state is LabelState.NOT_ENUM
    assert decode("2", None, "de").raw == "2"


@pytest.mark.parametrize("value", [None, ""])
def test_no_value_is_empty_whatever_the_feature(value: str | None) -> None:
    assert decode(value, CODES, "de").state is LabelState.EMPTY
    assert decode(value, None, "de").state is LabelState.EMPTY
    assert decode(value, CODES, "de").raw == value


def test_the_default_is_an_empty_undecoded_value() -> None:
    assert UNDECODED.state is LabelState.EMPTY
    assert UNDECODED.raw is None and UNDECODED.label is None
