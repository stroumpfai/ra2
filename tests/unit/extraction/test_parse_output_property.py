"""The property plan-phase-3.md §7 (H2) names: `parse_output` never raises on
arbitrary bytes.

`raw` is typed `str` — decoding the endpoint's response bytes into text
happens upstream, at the LLM adapter (sw-design.md §15.5), never inside this
pure module (Do-NOT list #4 governs *file* decoding; the adapter boundary is
a separate concern this module has no opinion on). What "arbitrary bytes"
means at `parse_output`'s own boundary is therefore arbitrary *text*: any
Unicode string at all, well-formed JSON or not, matching the feature
configuration or not. Hypothesis is asked for exactly that, plus a handful of
generators biased toward almost-valid JSON, which is where a hand-rolled
parser is most likely to have missed a case.
"""

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ra2.domain.extraction import ParsedExtraction, ParseFailure, parse_output
from ra2.domain.feature import Grain, Kind, MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.prompt import FeatureBlockEntry

pytestmark = pytest.mark.unit

_FEATURES = (
    FeatureBlockEntry(
        key="UnfallartCode",
        kind=Kind.LABELLED,
        grain=Grain.ACCIDENT,
        value_type=ValueType.ENUM,
        description="The kind of accident.",
        matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
    ),
    FeatureBlockEntry(
        key="AnzObjFeld",
        kind=Kind.LABELLED,
        grain=Grain.ACCIDENT,
        value_type=ValueType.INTEGER,
        description="Object count.",
        matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
    ),
)

_ENUM_CODELISTS = {"UnfallartCode": frozenset({"01", "02"})}


def _assert_never_raises(raw: str) -> None:
    result = parse_output(raw, _FEATURES, enum_codelists=_ENUM_CODELISTS)
    assert isinstance(result, ParsedExtraction | ParseFailure)


# ---------------------------------------------------------------------------
# Fully arbitrary text
# ---------------------------------------------------------------------------


@given(raw=st.text(max_size=2000))
@settings(max_examples=500)
def test_never_raises_on_arbitrary_unicode_text(raw: str) -> None:
    _assert_never_raises(raw)


@given(raw=st.binary(max_size=2000).map(lambda b: b.decode("latin-1")))
@settings(max_examples=300)
def test_never_raises_on_arbitrary_byte_sequences(raw: str) -> None:
    """`latin-1` decodes any byte sequence without error, which is exactly
    the point here: this is "arbitrary bytes", reinterpreted as the `str`
    `parse_output` actually takes, not a claim about the real decoding the
    LLM adapter performs upstream."""
    _assert_never_raises(raw)


# ---------------------------------------------------------------------------
# Biased toward almost-valid JSON — the inputs closest to what a real,
# slightly-misbehaving endpoint would actually produce.
# ---------------------------------------------------------------------------

_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**6), max_value=10**6),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=20),
)

_feature_answers = st.fixed_dictionaries(
    {
        "value": _json_scalars,
        "present": st.booleans(),
        "evidence": st.one_of(st.none(), st.text(max_size=20)),
    }
)

_envelopes = st.fixed_dictionaries(
    {
        "features": st.dictionaries(
            st.sampled_from(["UnfallartCode", "AnzObjFeld", "UnexpectedKey"]),
            _feature_answers,
            max_size=3,
        ),
        "entities": st.lists(
            st.fixed_dictionaries(
                {
                    "kind": st.sampled_from(["vehicle", "person"]),
                    "ref": st.text(max_size=5),
                    "attributes": st.dictionaries(st.text(max_size=5), st.text(max_size=5)),
                }
            ),
            max_size=3,
        ),
    }
)


@given(envelope=_envelopes)
@settings(max_examples=300)
def test_never_raises_on_well_shaped_but_arbitrary_envelopes(envelope: dict[str, object]) -> None:
    _assert_never_raises(json.dumps(envelope))


@given(envelope=_envelopes, cut_point=st.floats(min_value=0.0, max_value=1.0))
@settings(max_examples=300)
def test_never_raises_on_truncated_json(envelope: dict[str, object], cut_point: float) -> None:
    """A valid envelope, cut off at an arbitrary point — the shape of a
    response the endpoint stopped emitting mid-stream."""
    text = json.dumps(envelope)
    truncated = text[: int(len(text) * cut_point)]
    _assert_never_raises(truncated)


@given(prefix=st.text(max_size=50), suffix=st.text(max_size=50), envelope=_envelopes)
@settings(max_examples=300)
def test_never_raises_on_prose_wrapped_json(
    prefix: str, suffix: str, envelope: dict[str, object]
) -> None:
    """A valid envelope with arbitrary prose stitched around it."""
    _assert_never_raises(f"{prefix}{json.dumps(envelope)}{suffix}")


def test_never_raises_with_no_configured_features_and_arbitrary_text() -> None:
    """The degenerate feature list, paired with the same battery of hostile
    input, is worth pinning as an example test (not just inside the property
    above) because an empty `features` sequence is where an off-by-one in a
    loop bound is most likely to surface."""
    for raw in ("", "{}", "not json", "[]", "null"):
        result = parse_output(raw, ())
        assert isinstance(result, ParsedExtraction | ParseFailure)
