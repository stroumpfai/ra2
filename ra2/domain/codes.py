# FROZEN (types and signature) — see CONTRACTS.md
"""The imported codelist shape (mvp-spec.md §7, sw-design.md §14.1).

Code tables are imported, never authored in the app. This module holds the
Pydantic schema `codes-2018.json` must match, the pure post-parse shape that
schema is turned into, and the `validate_import` signature.

**M9 freezes the types and the schema. D1 writes `validate_import`'s body.**

`compute_coverage` is a sibling function in `codelist_coverage.py`, not here
(sw-design.md §14.3's package layout: the imported shape and the coverage
computation are two different concerns with two different callers). This is
a deliberate correction of plan-phase-2.md §5.1, which named both bodies as
`codes.py`'s — sw-design.md wins ties on *how* (CLAUDE.md, plan-phase-2.md
line 13).
"""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, RootModel

__all__ = [
    "CodeAttribute",
    "CodeAttributeSchema",
    "CodeEntrySchema",
    "CodeImportError",
    "CodeTableImportResult",
    "CodeValue",
    "CodelistImportSchema",
    "validate_import",
]


# ===========================================================================
# The wire shape of codes-2018.json (sw-design.md §14.1)
# ===========================================================================


class CodeEntrySchema(BaseModel):
    """One `{de, fr, it}` label map. Languages present may vary per code."""

    model_config = ConfigDict(extra="forbid")

    de: str | None = None
    fr: str | None = None
    it: str | None = None


class CodeAttributeSchema(BaseModel):
    """One top-level key of the imported JSON, e.g. `accident_type`."""

    model_config = ConfigDict(extra="forbid")

    chapter: str | None = None
    name: CodeEntrySchema
    codes: dict[str, CodeEntrySchema]


class CodelistImportSchema(RootModel[dict[str, CodeAttributeSchema]]):
    """The whole uploaded file: `{attribute_key: CodeAttributeSchema}`."""


# ===========================================================================
# The pure post-parse shape (what a validated import turns into)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class CodeAttribute:
    """One code attribute, identified by its JSON key — pre-id, pre-persistence.

    Distinct from `ra2.persistence.models.CodeAttribute` (the ORM row this
    becomes once `codelist_service.import_file` writes it), the same way
    `ra2.domain.census.ColumnCensus` is distinct from `CensusColumn`.
    """

    key: str
    chapter: str | None
    name: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CodeValue:
    """One `(attribute, code)` pair with its per-language labels.

    `attribute_key` ties it back to a `CodeAttribute` before either has a
    database id — mirrors `code_value.code_attribute_id`, just not yet an id.
    """

    attribute_key: str
    code: str
    label: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CodeImportError:
    """One structural problem with the uploaded file.

    `attribute_key` is `None` for an error at the top level (e.g. the file is
    not even a JSON object).
    """

    attribute_key: str | None
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class CodeTableImportResult:
    """A validated import, ready for `codelist_service` to write.

    Do-NOT list #6: this is the success case only. Any structural error
    fails the *whole* import (§14.1 step 1) — there is no partial result to
    represent, so failure is `list[CodeImportError]`, not a result with holes.
    """

    attributes: tuple[CodeAttribute, ...]
    values: tuple[CodeValue, ...]


def validate_import(raw_json: str) -> CodeTableImportResult | list[CodeImportError]:
    """Parse and validate against `CodelistImportSchema`. Pure: no I/O.

    Any structural error — malformed JSON, an unknown field, a missing
    `codes` key on one attribute — fails the whole import; there is no
    best-effort row skipping (Do-NOT list #6, sw-design.md §14.1 step 1).

    :returns: the validated attributes and codes, or every error found (not
        just the first) so the analyst sees the whole problem at once.
    """
    raise NotImplementedError
