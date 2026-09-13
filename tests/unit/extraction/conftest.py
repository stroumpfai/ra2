"""Fixtures for `ra2.domain.extraction` unit tests (H2).

One fixture object per concern, in the same spirit as `tests/unit/codes/`'s
`cl` and `tests/unit/parsing/`'s `hz`: helpers are exposed as fixtures rather
than as importable module-level functions, because more than one
`conftest.py` sits on the collection path and cross-file imports of a sibling
`conftest.py` are not reliable.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import BaseModel

from ra2.domain.codes import CodeValue
from ra2.domain.feature import Grain, Kind, MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.prompt import FeatureBlockEntry

#: Golden JSON Schema snapshots, one per feature-kind combination
#: (plan-phase-3.md §7, H2's exit criteria). Committed alongside the test that
#: reads them, so a schema drift shows up as a file diff a reviewer reads.
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

#: The type `feature_factory` returns: build one `FeatureBlockEntry` with
#: sensible defaults, overriding only what a test cares about.
FeatureFactory = Callable[..., FeatureBlockEntry]


def _build_feature(
    key: str,
    *,
    kind: Kind = Kind.LABELLED,
    grain: Grain = Grain.ACCIDENT,
    value_type: ValueType = ValueType.FREE_TEXT,
    description: str = "A feature, for a test.",
    matching_rule: MatchingRule | None = None,
    enum_codelist: tuple[CodeValue, ...] | None = None,
) -> FeatureBlockEntry:
    return FeatureBlockEntry(
        key=key,
        kind=kind,
        grain=grain,
        value_type=value_type,
        description=description,
        matching_rule=matching_rule or MatchingRule(kind=MatchingRuleKind.EXACT),
        enum_codelist=enum_codelist,
    )


@pytest.fixture
def feature_factory() -> FeatureFactory:
    """Build one `FeatureBlockEntry`, the input shape both functions under
    test take (`domain/prompt.py`'s `FeatureBlockEntry`, reduced to exactly
    what the prompt and the schema are allowed to see)."""
    return _build_feature


class SchemaGolden:
    """Compares a built schema's JSON Schema against a committed golden file.

    A strict, read-only comparison — never a write-if-missing helper. A
    silent regeneration would defeat the point (plan-phase-3.md §7, H2): the
    snapshot diff has to be something a reviewer reads in the same change
    that caused it.
    """

    dir = GOLDEN_DIR

    def dump(self, model: type[BaseModel]) -> str:
        """The exact bytes a golden file holds for one schema.

        `sort_keys=False`: the whole point of the snapshot is to catch a
        change in property *order*, so alphabetising away would defeat it.
        """
        return (
            json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False, sort_keys=False)
            + "\n"
        )

    def assert_matches(self, model: type[BaseModel], name: str) -> None:
        path = self.dir / f"{name}.json"
        assert path.is_file(), (
            f"missing golden fixture {path} — commit one deliberately, never generate it "
            "from the first failing run"
        )
        expected = path.read_text(encoding="utf-8")
        actual = self.dump(model)
        # Comparing line lists rather than the raw strings gives pytest's
        # sequence-diff output instead of one giant opaque string diff.
        assert actual.splitlines() == expected.splitlines(), (
            f"'{name}' schema drifted from its committed golden file "
            f"({path}) — if the drift is intentional, update the golden file "
            "in this same change so a reviewer sees the diff"
        )


@pytest.fixture
def golden() -> SchemaGolden:
    return SchemaGolden()
