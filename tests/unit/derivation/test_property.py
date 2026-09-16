"""`evaluate` never raises on arbitrary record shapes (plan-phase-4.md §7, S3).

The scoring pass walks a whole corpus. A projection that crashes the evaluator
takes the run's scores with it, and the data it crashes on will be the record
nobody looked at.

`DerivationError` is the deliberate exception and is excluded: it is a
**configuration** fault (a code outside the declared ordering, a table that is
not `objekt` or `person`), raised on purpose so a misconfigured feature is
loud rather than quietly zero.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from ra2.domain.derivation import DerivationError, RecordProjection, evaluate
from ra2.domain.feature import (
    AnyObjectMatches,
    AnyPersonMatches,
    CountObjects,
    CountPersons,
    DerivationSpec,
    DistinctCount,
    Filter,
    MaxOrdinal,
    MinOrdinal,
    Operator,
)

cells = st.dictionaries(
    st.text(min_size=0, max_size=12),
    st.text(min_size=0, max_size=12),
    max_size=5,
)
projections = st.builds(
    RecordProjection,
    objekt_rows=st.lists(cells, max_size=4),
    person_rows=st.lists(cells, max_size=4),
)
filters = st.builds(
    Filter,
    column=st.text(min_size=0, max_size=12),
    operator=st.sampled_from(Operator),
    value=st.one_of(
        st.none(),
        st.text(max_size=8),
        st.tuples(st.text(max_size=8), st.text(max_size=8)),
    ),
)
derivations: st.SearchStrategy[DerivationSpec] = st.one_of(
    st.builds(CountObjects, filter=st.one_of(st.none(), filters)),
    st.builds(CountPersons, filter=st.one_of(st.none(), filters)),
    st.builds(AnyObjectMatches, filter=filters),
    st.builds(AnyPersonMatches, filter=filters),
    st.builds(
        MaxOrdinal,
        table=st.sampled_from(["objekt", "person"]),
        column=st.text(max_size=12),
        ordered_codes=st.tuples(st.text(max_size=8)),
    ),
    st.builds(
        MinOrdinal,
        table=st.sampled_from(["objekt", "person"]),
        column=st.text(max_size=12),
        ordered_codes=st.tuples(st.text(max_size=8)),
    ),
    st.builds(
        DistinctCount,
        table=st.sampled_from(["objekt", "person"]),
        column=st.text(max_size=12),
    ),
)


@given(derivation=derivations, projection=projections)
@settings(max_examples=500)
def test_evaluate_never_raises_except_deliberately(
    derivation: DerivationSpec, projection: RecordProjection
) -> None:
    try:
        result = evaluate(derivation, projection)
    except DerivationError:
        return  # The one exception this module raises on purpose.
    assert result is None or isinstance(result, str)


@given(projection=projections, row_filter=st.one_of(st.none(), filters))
@settings(max_examples=300)
def test_a_count_is_never_negative_and_never_exceeds_the_rows(
    projection: RecordProjection, row_filter: Filter | None
) -> None:
    """A filtered count is a subset count. Anything else means the filter is
    matching rows that are not there."""
    result = evaluate(CountObjects(row_filter), projection)
    assert result is not None
    assert 0 <= int(result) <= len(projection.objekt_rows)


@given(projection=projections, row_filter=filters)
@settings(max_examples=300)
def test_any_matches_agrees_with_its_own_count(
    projection: RecordProjection, row_filter: Filter
) -> None:
    """`any_object_matches` is `count_objects > 0` under the same filter. Two
    catalogue entries that disagreed would score the same record two ways."""
    count = evaluate(CountObjects(row_filter), projection)
    any_match = evaluate(AnyObjectMatches(row_filter), projection)
    assert count is not None
    assert any_match == ("true" if int(count) > 0 else "false")
