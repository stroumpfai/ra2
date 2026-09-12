"""`ra2.domain.codelist_coverage.compute_coverage` (mvp-spec.md §7, sw-design.md §14.2).

Pure, in-memory: `cells` and `code_values` are constructed by hand, matched
against the committed c01-c05 codelist fixtures where a hazard names one
(`tests/fixtures/codelists/generate_codelist_hazards.py`), and every expected
number below is hand-computed, not derived from the function under test.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from ra2.domain.codelist_coverage import CodeUsage, CoverageStatus, compute_coverage
from ra2.domain.codes import CodeAttribute, CodeTableImportResult, CodeValue, validate_import

pytestmark = pytest.mark.unit

LANGUAGE_DE = "de"
LANGUAGE_IT = "it"

_GENERATOR = (
    Path(__file__).resolve().parents[2] / "fixtures" / "codelists" / "generate_codelist_hazards.py"
)


def _generator() -> ModuleType:
    """Import the fixture generator by path, for its `ORPHAN_VALUE` constant.

    `tests/fixtures/` is not a package and is not on `sys.path` (same reason
    `tests/unit/parsing/test_generated_fixtures.py` loads it this way)."""
    spec = importlib.util.spec_from_file_location("ra2_generate_codelist_hazards", _GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _attribute(key: str) -> CodeAttribute:
    return CodeAttribute(key=key, chapter=None, name={"de": key})


# --------------------------------------------------------------------------
# MISSING
# --------------------------------------------------------------------------


def test_no_mapping_at_all_is_missing():
    coverage = compute_coverage(
        cells=[("01", 5)],
        mapping=None,
        code_values=[CodeValue(attribute_key="a", code="01", label={"de": "x"})],
        language=LANGUAGE_DE,
    )
    assert coverage.status is CoverageStatus.MISSING


def test_c03_a_mapped_attribute_with_zero_codes_is_missing(cl):
    """c03: `light_condition` has zero `CodeValue` rows after import — mapped,
    but `MISSING`, even though `mapping` is not `None`."""
    result = validate_import(cl.raw_json("c03_attribute_with_zero_codes"))
    assert isinstance(result, CodeTableImportResult)
    mapping = result.attributes[0]
    assert mapping.key == "light_condition"
    assert result.values == ()

    coverage = compute_coverage(
        cells=[("1", 10), ("2", 3)],
        mapping=mapping,
        code_values=result.values,
        language=LANGUAGE_DE,
    )
    assert coverage.status is CoverageStatus.MISSING


def test_empty_code_values_is_missing_even_with_a_mapping_set():
    """Right at the boundary named in the docstring: `mapping` is set, but
    `code_values` is empty — still `MISSING`, not `PARTIAL`."""
    coverage = compute_coverage(
        cells=[("01", 1)],
        mapping=_attribute("weather"),
        code_values=[],
        language=LANGUAGE_DE,
    )
    assert coverage.status is CoverageStatus.MISSING


def test_missing_with_no_corpus_usage_at_all_reports_zero_counts():
    coverage = compute_coverage(cells=[], mapping=None, code_values=[], language=LANGUAGE_DE)
    assert coverage.status is CoverageStatus.MISSING
    assert coverage.total_count == 0
    assert coverage.labelled_count == 0
    assert coverage.coverage_pct == 0.0
    assert coverage.codes == ()


# --------------------------------------------------------------------------
# PARTIAL / OK boundary
# --------------------------------------------------------------------------


def test_c02_missing_one_language_label_on_one_code_is_partial_in_that_language(cl):
    """c02: `main_cause` code `02` has no `it` label — requesting `it`
    coverage is `PARTIAL`; requesting `de` (fully labelled) is `OK`."""
    result = validate_import(cl.raw_json("c02_missing_language_label"))
    assert isinstance(result, CodeTableImportResult)
    mapping = result.attributes[0]

    partial = compute_coverage(
        cells=[("01", 10), ("02", 5)],
        mapping=mapping,
        code_values=result.values,
        language=LANGUAGE_IT,
    )
    assert partial.status is CoverageStatus.PARTIAL
    assert partial.labelled_count == 1
    assert partial.total_count == 2
    assert partial.coverage_pct == pytest.approx(0.5)

    ok = compute_coverage(
        cells=[("01", 10), ("02", 5)],
        mapping=mapping,
        code_values=result.values,
        language=LANGUAGE_DE,
    )
    assert ok.status is CoverageStatus.OK
    assert ok.labelled_count == 2
    assert ok.total_count == 2
    assert ok.coverage_pct == pytest.approx(1.0)


def test_all_but_one_labelled_is_partial():
    code_values = [
        CodeValue(attribute_key="a", code="1", label={"de": "x"}),
        CodeValue(attribute_key="a", code="2", label={"de": "y"}),
        CodeValue(attribute_key="a", code="3", label={}),
    ]
    coverage = compute_coverage(
        cells=[("1", 3), ("2", 2), ("3", 1)],
        mapping=_attribute("a"),
        code_values=code_values,
        language=LANGUAGE_DE,
    )
    assert coverage.status is CoverageStatus.PARTIAL
    assert coverage.labelled_count == 2
    assert coverage.total_count == 3


def test_all_labelled_is_ok():
    code_values = [
        CodeValue(attribute_key="a", code="1", label={"de": "x"}),
        CodeValue(attribute_key="a", code="2", label={"de": "y"}),
    ]
    coverage = compute_coverage(
        cells=[("1", 3), ("2", 2)],
        mapping=_attribute("a"),
        code_values=code_values,
        language=LANGUAGE_DE,
    )
    assert coverage.status is CoverageStatus.OK
    assert coverage.labelled_count == coverage.total_count == 2
    assert coverage.coverage_pct == pytest.approx(1.0)


def test_no_corpus_usage_of_a_mapped_populated_attribute_is_vacuously_ok():
    code_values = [CodeValue(attribute_key="a", code="1", label={"de": "x"})]
    coverage = compute_coverage(
        cells=[], mapping=_attribute("a"), code_values=code_values, language=LANGUAGE_DE
    )
    assert coverage.status is CoverageStatus.OK
    assert coverage.total_count == 0
    assert coverage.coverage_pct == 0.0


# --------------------------------------------------------------------------
# The orphan / danger row: in_codelist=False
# --------------------------------------------------------------------------


def test_c05_a_corpus_value_absent_from_the_codelist_is_the_orphan_danger_row(cl):
    """c05: `ORPHAN_VALUE` ("97") matches none of `weather`'s codes, in any
    language — `in_codelist=False`, distinct from merely lacking a label."""
    ORPHAN_VALUE = _generator().ORPHAN_VALUE

    result = validate_import(cl.raw_json("c05_orphan_corpus_value"))
    assert isinstance(result, CodeTableImportResult)
    mapping = result.attributes[0]

    coverage = compute_coverage(
        cells=[("1", 40), ("2", 10), (ORPHAN_VALUE, 3)],
        mapping=mapping,
        code_values=result.values,
        language=LANGUAGE_DE,
    )

    by_code = {usage.code: usage for usage in coverage.codes}
    orphan = by_code[ORPHAN_VALUE]
    assert orphan.in_codelist is False
    assert orphan.label is None
    assert orphan.count == 3

    matched = by_code["1"]
    assert matched.in_codelist is True
    assert matched.label == "Klar"

    # The orphan code still lacks a label, so overall status is PARTIAL, not
    # its own status — it is a per-row marker, not a column-level one.
    assert coverage.status is CoverageStatus.PARTIAL


def test_a_code_matched_by_id_but_lacking_the_requested_language_is_not_an_orphan():
    """`in_codelist=True` even though `label` is `None` for this language —
    the orphan/danger flag means "no row at all", not "no label here"."""
    code_values = [CodeValue(attribute_key="a", code="1", label={"de": "x"})]
    coverage = compute_coverage(
        cells=[("1", 5)], mapping=_attribute("a"), code_values=code_values, language=LANGUAGE_IT
    )
    usage = coverage.codes[0]
    assert usage.in_codelist is True
    assert usage.label is None


# --------------------------------------------------------------------------
# Ordering, shares and the CodeUsage shape
# --------------------------------------------------------------------------


def test_codes_are_ordered_by_count_descending():
    code_values = [
        CodeValue(attribute_key="a", code=code, label={"de": code}) for code in ("x", "y", "z")
    ]
    coverage = compute_coverage(
        cells=[("x", 1), ("y", 20), ("z", 5)],
        mapping=_attribute("a"),
        code_values=code_values,
        language=LANGUAGE_DE,
    )
    assert [usage.code for usage in coverage.codes] == ["y", "z", "x"]


def test_share_is_count_over_the_columns_populated_count():
    code_values = [
        CodeValue(attribute_key="a", code="1", label={"de": "x"}),
        CodeValue(attribute_key="a", code="2", label={"de": "y"}),
    ]
    coverage = compute_coverage(
        cells=[("1", 3), ("2", 1)],
        mapping=_attribute("a"),
        code_values=code_values,
        language=LANGUAGE_DE,
    )
    by_code = {usage.code: usage for usage in coverage.codes}
    assert by_code["1"].share == pytest.approx(0.75)
    assert by_code["2"].share == pytest.approx(0.25)


def test_codes_are_codeusage_instances():
    code_values = [CodeValue(attribute_key="a", code="1", label={"de": "x"})]
    coverage = compute_coverage(
        cells=[("1", 1)], mapping=_attribute("a"), code_values=code_values, language=LANGUAGE_DE
    )
    assert all(isinstance(usage, CodeUsage) for usage in coverage.codes)


def test_returned_language_echoes_the_requested_one():
    coverage = compute_coverage(cells=[], mapping=None, code_values=[], language="fr")
    assert coverage.language == "fr"
