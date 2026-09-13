"""Fixtures for `ra2.domain.prompt` unit tests (H1).

Mirrors `tests/unit/codes/conftest.py`'s pattern: the committed hazard
fixtures are exposed through one fixture object rather than as importable
module-level helpers, since more than one `conftest.py` sits on the path.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from ra2.domain.codes import CodeValue
from ra2.domain.feature import Grain, Kind, MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.prompt import FeatureBlockEntry

PROMPT_HAZARDS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "prompts" / "hazards"


class PromptHazards:
    """Loading the committed prompt hazard fixtures (p01-p07)."""

    dir = PROMPT_HAZARDS_DIR

    def _path(self, hazard: str, filename: str) -> Path:
        path = self.dir / hazard / filename
        assert path.is_file(), f"missing fixture {path} — run generate_prompt_hazards.py"
        return path

    def source(self, hazard: str) -> str:
        """One hazard's `template.txt`, decoded as the app would."""
        return self._path(hazard, "template.txt").read_text(encoding="utf-8")

    def narrative(self, hazard: str) -> str:
        """One hazard's `narrative.txt` — stand-in for `record.text_raw`."""
        return self._path(hazard, "narrative.txt").read_text(encoding="utf-8")

    def features_manifest(self, hazard: str) -> Mapping[str, Any]:
        """One hazard's `features.json`, parsed but not yet converted."""
        raw = self._path(hazard, "features.json").read_text(encoding="utf-8")
        return cast("Mapping[str, Any]", json.loads(raw))

    def feature_block_entries(self, hazard: str) -> tuple[tuple[FeatureBlockEntry, ...], str]:
        """`features.json` turned into `FeatureBlockEntry` values, plus the
        manifest's requested rendering language."""
        manifest = self.features_manifest(hazard)
        entries = tuple(_entry_from_json(raw) for raw in manifest["features"])
        return entries, str(manifest["language"])


def _entry_from_json(raw: Mapping[str, Any]) -> FeatureBlockEntry:
    rule_raw = raw["matching_rule"]
    matching_rule = MatchingRule(
        kind=MatchingRuleKind(rule_raw["kind"]),
        tolerance_minutes=rule_raw["tolerance_minutes"],
        decimal_precision=rule_raw["decimal_precision"],
    )
    codelist_raw = raw["enum_codelist"]
    enum_codelist = (
        tuple(
            CodeValue(attribute_key=raw["key"], code=c["code"], label=dict(c["label"]))
            for c in codelist_raw
        )
        if codelist_raw is not None
        else None
    )
    return FeatureBlockEntry(
        key=raw["key"],
        kind=Kind(raw["kind"]),
        grain=Grain(raw["grain"]),
        value_type=ValueType(raw["value_type"]),
        description=raw["description"],
        matching_rule=matching_rule,
        enum_codelist=enum_codelist,
    )


@pytest.fixture
def ph() -> PromptHazards:
    return PromptHazards()
