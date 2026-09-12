# FROZEN — see CONTRACTS.md
"""Typed identifiers.

Every id in RA2 is an opaque string. `NewType` gives the type checker a way to
stop a `CorpusId` being passed where a `DeliveryId` is wanted, at zero runtime
cost.

Ids are minted by the injected `IdFactory` (`ra2.infra.idgen`), never by
`uuid.uuid4()` at a call site — `SeededFactory` is what makes golden reports and
E2E runs reproducible (sw-design.md §3).
"""

from typing import NewType

__all__ = [
    "CensusColumnId",
    "CodeAttributeId",
    "CodeTableImportId",
    "ColumnMappingId",
    "CorpusId",
    "DeliveryId",
    "EvaluationId",
    "FeatureConfigId",
    "FeatureId",
    "FileId",
    "ObjektRowId",
    "PersonRowId",
    "RecordId",
    "TaskId",
]

#: One import staging area (sw-design.md §4.1, SD1).
DeliveryId = NewType("DeliveryId", str)

#: One file inside a delivery. Carried on every `Finding` that has a file.
FileId = NewType("FileId", str)

#: One immutable corpus produced by one freeze (mvp-spec.md §2).
CorpusId = NewType("CorpusId", str)

#: One accident: `unfall` row + children + narrative, keyed by `UnfallUid`.
RecordId = NewType("RecordId", str)

#: One background job handled by the `TaskRunner` (sw-design.md §9).
TaskId = NewType("TaskId", str)

# --- additive beyond plan-m0-m5.md §3.1's five, so later agents need no amendment ---

#: One `objekt` row of a record.
ObjektRowId = NewType("ObjektRowId", str)

#: One `person` row, hanging off an `objekt` row (never off `unfall`; mvp-spec.md §4.1).
PersonRowId = NewType("PersonRowId", str)

#: One materialised census row: (corpus, table, column) (sw-design.md §4.2, SD2).
CensusColumnId = NewType("CensusColumnId", str)

#: One evaluation. Phase 1 only ever seeds these, to exercise the corpus delete
#: guard (sw-design.md §6.3).
EvaluationId = NewType("EvaluationId", str)

# --- phase 2 (M9, plan-phase-2.md §3) ---------------------------------------

#: One `codes-2018.json` (or successor) upload (sw-design.md §14.1).
CodeTableImportId = NewType("CodeTableImportId", str)

#: One top-level key of an imported codelist file, e.g. `accident_type`.
#: `code_value` rows have no dedicated id type — nothing joins against one by
#: id outside its own attribute (plan-phase-2.md §5.1 names five new types,
#: not six).
CodeAttributeId = NewType("CodeAttributeId", str)

#: One `(corpus_id, source_column) -> code_attribute_id` pointer (mvp-spec.md
#: §5). The only editable table Codelists introduces.
ColumnMappingId = NewType("ColumnMappingId", str)

#: One feature set, draft or frozen (mvp-spec.md §8).
FeatureConfigId = NewType("FeatureConfigId", str)

#: One feature inside a `feature_config`.
FeatureId = NewType("FeatureId", str)
