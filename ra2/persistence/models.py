# FROZEN — see CONTRACTS.md
"""The whole phase-1 schema (mvp-spec.md §5 + sw-design.md §4).

**Scope.** Phase 1 is shell, import and census (plan-phase-1.md §1). Codelists,
feature configs, runs, extractions, scores and mismatches are *out*, so their
tables are not here. `evaluation` is the one exception: sw-design.md §6.3
requires the corpus delete guard to be implemented and tested against a seeded
row, and J3 asserts the `LOCKED · 1 eval` pill, so the table must exist to seed.
See the note on `Evaluation` below.

**Immutability (N5, §12.2).** `corpus` and everything below it —
`record`, `unfall_row`, `objekt_row`, `objekt_cell`, `person_row`,
`person_cell`, `census_*` — is written once at freeze and never updated.
`delivery` and `delivery_file` are the only mutable tables: re-parsing after an
encoding override rewrites a `delivery_file` row.

**Storage rules (§4.4).**
- Values are stored `value_raw`, **verbatim**. Normalisation is a read-time
  domain function, never an in-place rewrite.
- EAV for the 67/77/18 wide columns (D10). The `census_*` tables exist
  precisely so no view ever queries EAV directly.
- `*_json` columns hold a serialised JSON **string**, not a JSON-typed column:
  the golden import report is asserted byte-for-byte, so the app controls key
  order and separators.
- Alembic from the first commit. `metadata.create_all()` appears nowhere, not
  even in tests (§12.10).
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ra2.domain.census import TypeHint
from ra2.domain.delivery import DeliveryStatus, FileKind, SourceKind
from ra2.domain.feature import Grain, Kind, ValueType
from ra2.domain.ids import (
    CensusColumnId,
    CodeAttributeId,
    CodeTableImportId,
    ColumnMappingId,
    CorpusId,
    DeliveryId,
    EvaluationId,
    FeatureConfigId,
    FeatureId,
    FileId,
    ObjektRowId,
    PersonRowId,
    RecordId,
)

__all__ = [
    "Base",
    "CensusBucketRow",
    "CensusColumn",
    "CensusValue",
    "CodeAttribute",
    "CodeTableImport",
    "CodeValue",
    "ColumnMapping",
    "Corpus",
    "Delivery",
    "DeliveryFile",
    "Evaluation",
    "Feature",
    "FeatureConfig",
    "ObjektCell",
    "ObjektRow",
    "PersonCell",
    "PersonRow",
    "Record",
    "UnfallRow",
]

#: Explicit constraint naming. Without it, SQLite produces unnamed constraints
#: that Alembic's batch mode cannot alter and `alembic check` cannot compare —
#: which would make A3's "migrations have not drifted" test unreliable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: A `UnfallUid` is exactly 32 hex characters; `ObjektUid` and `PersonUid`
#: follow the same shape. 36 leaves room for our own generated ids.
_ID_LEN = 36
_UID_LEN = 32


class Base(DeclarativeBase):
    """Declarative base. All ids are opaque strings; the `NewType`s from
    `ra2.domain.ids` are mapped straight onto `String`, so a `CorpusId` cannot
    be passed where a `DeliveryId` is wanted without mypy noticing."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this as a plain dict
        DeliveryId: String(_ID_LEN),
        FileId: String(_ID_LEN),
        CorpusId: String(_ID_LEN),
        RecordId: String(_ID_LEN),
        ObjektRowId: String(_ID_LEN),
        PersonRowId: String(_ID_LEN),
        CensusColumnId: String(_ID_LEN),
        EvaluationId: String(_ID_LEN),
        CodeTableImportId: String(_ID_LEN),
        CodeAttributeId: String(_ID_LEN),
        ColumnMappingId: String(_ID_LEN),
        FeatureConfigId: String(_ID_LEN),
        FeatureId: String(_ID_LEN),
        FileKind: String(16),
        SourceKind: String(16),
        DeliveryStatus: String(16),
        TypeHint: String(16),
        Kind: String(16),
        Grain: String(16),
        ValueType: String(16),
        datetime: DateTime(timezone=True),
        str: Text(),
        int: Integer(),
        float: Float(),
        bool: Boolean(),
    }


# ===========================================================================
# Delivery staging — SD1. The only mutable tables in the schema.
# ===========================================================================


class Delivery(Base):
    """One import staging area (sw-design.md §4.1).

    The Import view shows files with parse state *before* a corpus exists, and
    a "Create corpus · N records" button that sums the selection. That needs a
    staging concept mvp-spec.md §5 does not name.
    """

    __tablename__ = "delivery"

    id: Mapped[DeliveryId] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime]
    #: `upload` | `host_path`. Nothing downstream of `FileStore` reads this.
    source_kind: Mapped[SourceKind]
    #: The host directory for a `host_path` delivery; `None` for an upload.
    root_path: Mapped[str | None] = mapped_column(default=None)
    #: `registered` | `analysing` | `analysed` | `failed`.
    status: Mapped[DeliveryStatus] = mapped_column(default=DeliveryStatus.REGISTERED)
    analysed_at: Mapped[datetime | None] = mapped_column(default=None)

    files: Mapped[list[DeliveryFile]] = relationship(
        back_populates="delivery",
        cascade="all, delete-orphan",
        order_by="DeliveryFile.filename",
    )


class DeliveryFile(Base):
    """One file of one delivery, with its parse state (sw-design.md §4.1).

    **Mutable**: re-parsing after an encoding or delimiter override rewrites
    this row, and only this row.

    Note what is *not* here: nothing is read from `filename`. `file_kind` comes
    from the header (SD5), `canton` from `unfall.KantonAusw`, and `set_key`
    from FK reachability (SD6). `filename` is display only.
    """

    __tablename__ = "delivery_file"
    __table_args__ = (
        UniqueConstraint("delivery_id", "relative_path", name="uq_delivery_file_path"),
        Index("ix_delivery_file_delivery_id", "delivery_id"),
    )

    id: Mapped[FileId] = mapped_column(primary_key=True)
    delivery_id: Mapped[DeliveryId] = mapped_column(ForeignKey("delivery.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(400))
    relative_path: Mapped[str] = mapped_column(String(1000))
    byte_size: Mapped[int]
    #: Hex sha256 of the file's bytes — provenance, and the re-parse guard.
    sha256: Mapped[str] = mapped_column(String(64))

    #: `unfall` | `objekt` | `person` | `text` | `unknown`, from the header.
    file_kind: Mapped[FileKind] = mapped_column(default=FileKind.UNKNOWN)
    #: Groups the three structured files of one canton (SD6). `None` until
    #: analysis resolves it; always `None` for the shared text file.
    set_key: Mapped[str | None] = mapped_column(String(64), default=None)
    #: From `unfall.KantonAusw`, never from the filename.
    canton: Mapped[str | None] = mapped_column(String(16), default=None)

    #: Effective settings — detection, unless the analyst overrode them.
    encoding: Mapped[str | None] = mapped_column(String(32), default=None)
    delimiter: Mapped[str | None] = mapped_column(String(4), default=None)
    quote_char: Mapped[str | None] = mapped_column(String(4), default=None)
    #: What detection said, kept alongside the effective values so the file
    #: report modal can show "detected vs. effective" (sw-design.md §8.3).
    encoding_detected: Mapped[str | None] = mapped_column(String(32), default=None)
    #: The detected `Dialect` as serialised JSON: `{"delimiter": …, "quote_char": …}`.
    dialect_detected: Mapped[str | None] = mapped_column(default=None)

    #: `None` until analysed. `row_count` is data rows, header excluded.
    row_count: Mapped[int | None] = mapped_column(default=None)
    ok_count: Mapped[int] = mapped_column(default=0)
    recovered_count: Mapped[int] = mapped_column(default=0)
    rejected_count: Mapped[int] = mapped_column(default=0)
    #: `None` until analysed; `False` when the header matched no canonical set.
    header_ok: Mapped[bool | None] = mapped_column(default=None)

    #: `list[Finding]` serialised. Every recovered and rejected row is in here
    #: with its key — nothing is silently repaired or dropped (§12.6).
    findings_json: Mapped[str | None] = mapped_column(default=None)
    #: Deselected files stay in the list and are excluded from the corpus.
    selected: Mapped[bool] = mapped_column(default=True)
    analysed_at: Mapped[datetime | None] = mapped_column(default=None)

    delivery: Mapped[Delivery] = relationship(back_populates="files")


# ===========================================================================
# Corpus — mvp-spec.md §5, plus SD4's four additive columns. IMMUTABLE.
# ===========================================================================


class Corpus(Base):
    """An immutable snapshot produced by one import (mvp-spec.md §2).

    Never updated after the freeze transaction commits. A re-import creates a
    new corpus with a new version, it does not mutate this one (§12.2).
    """

    __tablename__ = "corpus"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_corpus_name_version"),
        CheckConstraint("record_count >= 0", name="record_count_non_negative"),
    )

    id: Mapped[CorpusId] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    #: SD4 — shown in the design's Corpora table, absent from mvp-spec.md §5.
    description: Mapped[str | None] = mapped_column(default=None)
    imported_at: Mapped[datetime]
    #: Monotonic per `name`. The design renders it as "v1".
    version: Mapped[int] = mapped_column(default=1)

    #: The files that went in: filename, size, sha256, encoding, dialect.
    source_file_manifest_json: Mapped[str]
    #: The non-blocking `list[Finding]` of the whole import (sw-design.md §5).
    import_report_json: Mapped[str]
    record_count: Mapped[int]
    #: mvp-spec.md §9 — from `RA2_DEV_RECORD_MAX` / `RA2_EVAL_RECORD_MIN`.
    #: Every view showing a dev corpus's numbers carries the "smoke test, not a
    #: result" marker.
    is_dev_sized: Mapped[bool] = mapped_column(default=False)
    #: mvp-spec.md §4.4, D11. **Zero, in a corpus containing French, proves the
    #: lossy cp1252 conversion happened.** One number per corpus; there are
    #: deliberately no per-record damage markers.
    cp1252_canary_count: Mapped[int] = mapped_column(default=0)

    #: SD4 — provenance of the freeze. Nullable so a corpus survives its
    #: delivery being deleted.
    delivery_id: Mapped[DeliveryId | None] = mapped_column(
        ForeignKey("delivery.id", ondelete="SET NULL"), default=None
    )
    #: SD4 — the `delivery_file` ids that were selected, serialised.
    source_file_ids_json: Mapped[str | None] = mapped_column(default=None)
    #: SD4 — the design's "de 2 812 · fr 1 402 · it 396", serialised as
    #: `{"de": 2812, "fr": 1402, "it": 396}`.
    language_counts_json: Mapped[str | None] = mapped_column(default=None)

    #: `passive_deletes=True`: a corpus delete lets SQLite's own `ON DELETE
    #: CASCADE` (every FK down this tree declares it, and `session.py` turns
    #: on `PRAGMA foreign_keys`) remove the whole record/EAV tree in one
    #: statement, instead of the ORM loading every row into Python first to
    #: issue a `DELETE` per object — a transaction long enough to blow past
    #: `BUSY_TIMEOUT_MS` and raise "database is locked" on a real corpus.
    records: Mapped[list[Record]] = relationship(
        back_populates="corpus", cascade="all, delete-orphan", passive_deletes=True
    )
    census_columns: Mapped[list[CensusColumn]] = relationship(
        back_populates="corpus", cascade="all, delete-orphan", passive_deletes=True
    )


class Record(Base):
    """One accident: `unfall` row + its children + its narrative.

    Keyed by `UnfallUid` (mvp-spec.md §2). `text_raw` is stored **verbatim and
    never normalised in place** (§5, N5).
    """

    __tablename__ = "record"
    __table_args__ = (
        UniqueConstraint("corpus_id", "unfall_uid", name="uq_record_corpus_unfall_uid"),
        Index("ix_record_corpus_id", "corpus_id"),
    )

    id: Mapped[RecordId] = mapped_column(primary_key=True)
    corpus_id: Mapped[CorpusId] = mapped_column(ForeignKey("corpus.id", ondelete="CASCADE"))
    unfall_uid: Mapped[str] = mapped_column(String(_UID_LEN))

    #: A `ra2.domain.language.Language` value. A plain string, not a DB enum,
    #: so a fourth language in a future delivery is a value, not a migration.
    #: Low confidence is stored as `mixed`, never forced to a winner (§4.5).
    language: Mapped[str] = mapped_column(String(16))
    language_confidence: Mapped[float]

    #: The narrative, verbatim. Never normalised in place.
    text_raw: Mapped[str | None] = mapped_column(default=None)
    #: Whether this record's text came from the anonymised column. Required
    #: wherever text is shown (mvp-spec.md §13).
    text_anonymised_flag: Mapped[bool] = mapped_column(default=False)

    corpus: Mapped[Corpus] = relationship(back_populates="records")
    unfall_cells: Mapped[list[UnfallRow]] = relationship(
        back_populates="record", cascade="all, delete-orphan", passive_deletes=True
    )
    objekt_rows: Mapped[list[ObjektRow]] = relationship(
        back_populates="record", cascade="all, delete-orphan", passive_deletes=True
    )


# ===========================================================================
# EAV — D10. 67 / 77 / 18 wide columns, in long form.
# ===========================================================================


class UnfallRow(Base):
    """One `unfall` cell, in long/EAV form (mvp-spec.md §5, 67 columns).

    `unfall` is 1:1 with `record`, so this needs no separate entity table — it
    *is* the cell table. Empty cells are stored: an empty string means "no
    value provided" and the census must be able to count it (§8.6).
    """

    __tablename__ = "unfall_row"
    __table_args__ = (Index("ix_unfall_row_record_id_column_name", "record_id", "column_name"),)

    record_id: Mapped[RecordId] = mapped_column(
        ForeignKey("record.id", ondelete="CASCADE"), primary_key=True
    )
    column_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    #: Verbatim. Normalisation is a read-time domain function (§4.4).
    value_raw: Mapped[str]

    record: Mapped[Record] = relationship(back_populates="unfall_cells")


class ObjektRow(Base):
    """One `objekt` row of a record. Its 77 columns live in `objekt_cell`."""

    __tablename__ = "objekt_row"
    __table_args__ = (
        UniqueConstraint("record_id", "objekt_uid", name="uq_objekt_row_record_objekt_uid"),
        Index("ix_objekt_row_record_id", "record_id"),
    )

    id: Mapped[ObjektRowId] = mapped_column(primary_key=True)
    record_id: Mapped[RecordId] = mapped_column(ForeignKey("record.id", ondelete="CASCADE"))
    objekt_uid: Mapped[str] = mapped_column(String(_UID_LEN))
    #: `ObjNr` — the within-accident ordinal. Kept as raw text: mvp-spec.md
    #: §16 flags that role codes may or may not map onto it, and that decision
    #: is not ours to pre-empt.
    obj_nr: Mapped[str | None] = mapped_column(String(16), default=None)

    record: Mapped[Record] = relationship(back_populates="objekt_rows")
    cells: Mapped[list[ObjektCell]] = relationship(
        back_populates="objekt_row", cascade="all, delete-orphan", passive_deletes=True
    )
    person_rows: Mapped[list[PersonRow]] = relationship(
        back_populates="objekt_row", cascade="all, delete-orphan", passive_deletes=True
    )


class ObjektCell(Base):
    """One `objekt` cell, in long/EAV form (77 columns)."""

    __tablename__ = "objekt_cell"
    __table_args__ = (
        Index("ix_objekt_cell_objekt_row_id_column_name", "objekt_row_id", "column_name"),
    )

    objekt_row_id: Mapped[ObjektRowId] = mapped_column(
        ForeignKey("objekt_row.id", ondelete="CASCADE"), primary_key=True
    )
    column_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_raw: Mapped[str]

    objekt_row: Mapped[ObjektRow] = relationship(back_populates="cells")


class PersonRow(Base):
    """One `person` row.

    **Hangs off `objekt_row`, not off `record`** (mvp-spec.md §4.1):
    person -> accident is a two-hop join, and a pedestrian still has an object
    row. Getting this wrong silently changes every person-grain aggregate.
    """

    __tablename__ = "person_row"
    __table_args__ = (
        UniqueConstraint("objekt_row_id", "person_uid", name="uq_person_row_objekt_person_uid"),
        Index("ix_person_row_objekt_row_id", "objekt_row_id"),
    )

    id: Mapped[PersonRowId] = mapped_column(primary_key=True)
    objekt_row_id: Mapped[ObjektRowId] = mapped_column(
        ForeignKey("objekt_row.id", ondelete="CASCADE")
    )
    person_uid: Mapped[str] = mapped_column(String(_UID_LEN))
    #: `PersNr` — the within-object ordinal. Raw text, same reasoning as `obj_nr`.
    pers_nr: Mapped[str | None] = mapped_column(String(16), default=None)

    objekt_row: Mapped[ObjektRow] = relationship(back_populates="person_rows")
    cells: Mapped[list[PersonCell]] = relationship(
        back_populates="person_row", cascade="all, delete-orphan", passive_deletes=True
    )


class PersonCell(Base):
    """One `person` cell, in long/EAV form (18 columns)."""

    __tablename__ = "person_cell"
    __table_args__ = (
        Index("ix_person_cell_person_row_id_column_name", "person_row_id", "column_name"),
    )

    person_row_id: Mapped[PersonRowId] = mapped_column(
        ForeignKey("person_row.id", ondelete="CASCADE"), primary_key=True
    )
    column_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_raw: Mapped[str]

    person_row: Mapped[PersonRow] = relationship(back_populates="cells")


# ===========================================================================
# Materialised census — SD2. Computed once at freeze, so it cannot go stale.
# ===========================================================================


class CensusColumn(Base):
    """One source column profiled over one corpus (sw-design.md §4.2).

    Materialised at freeze rather than aggregated per page load: a corpus is
    immutable so this can never be stale, and aggregating ~1.5M EAV cells on
    every request makes the Census view seconds slow for no gain.
    """

    __tablename__ = "census_column"
    __table_args__ = (
        UniqueConstraint(
            "corpus_id", "table_name", "column_name", name="uq_census_column_corpus_table_column"
        ),
        Index("ix_census_column_corpus_id", "corpus_id"),
        # No upper bound: `compute_census` (ra2/domain/census.py) uses the
        # *record* count as the denominator for every table so rates are
        # comparable across tables (sw-design.md §7), but objekt/person are
        # one-to-many with record — a multi-vehicle accident's objekt columns
        # legitimately populate more cells than there are records, so
        # populated_rate can exceed 1.0. Found at Wave 2 integration: a
        # `<= 1.0` upper bound here made corpus_service.freeze() crash on any
        # real delivery with more than one object per accident.
        CheckConstraint("populated_rate >= 0.0", name="populated_rate_is_a_rate"),
    )

    id: Mapped[CensusColumnId] = mapped_column(primary_key=True)
    corpus_id: Mapped[CorpusId] = mapped_column(ForeignKey("corpus.id", ondelete="CASCADE"))
    #: `unfall` | `objekt` | `person`.
    table_name: Mapped[str] = mapped_column(String(32))
    column_name: Mapped[str] = mapped_column(String(100))
    #: `Ausw`/`Feld` suffix rule first, then value-shape inspection.
    type_hint: Mapped[TypeHint]

    #: The denominator. Every column of a table shares it, including a column
    #: empty in every row (h08) — which is why it is stored per row.
    record_count: Mapped[int]
    #: Populated = **non-empty string** (mvp-spec.md §6).
    populated_count: Mapped[int]
    #: In [0, 1]. The UI renders the percentage; it never computes the rate.
    populated_rate: Mapped[float]
    distinct_count: Mapped[int]
    #: `top_values[0].share`, or 0.0. Stored so the long-tail rule and the
    #: legend need no recomputation.
    top_value_share: Mapped[float] = mapped_column(default=0.0)
    #: SD8: `distinct_count > 20 and top_value_share < 0.01`.
    long_tail: Mapped[bool] = mapped_column(default=False)

    corpus: Mapped[Corpus] = relationship(back_populates="census_columns")
    values: Mapped[list[CensusValue]] = relationship(
        back_populates="census_column",
        cascade="all, delete-orphan",
        order_by="CensusValue.rank",
        passive_deletes=True,
    )


class CensusValue(Base):
    """One of a column's top 20 values (sw-design.md §4.2).

    20 stored; the view shows the top 4 as bar segments and the top 3 in the
    legend. `rank` is 1-based and dense.
    """

    __tablename__ = "census_value"

    census_column_id: Mapped[CensusColumnId] = mapped_column(
        ForeignKey("census_column.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(primary_key=True)
    value_raw: Mapped[str]
    count: Mapped[int]
    #: `count / populated_count`, in [0, 1].
    share: Mapped[float]

    census_column: Mapped[CensusColumn] = relationship(back_populates="values")


class CensusBucketRow(Base):
    """One bar of the "Population profile · all tables" card.

    Named `CensusBucketRow` in Python because `CensusBucket` is the domain
    value object (`ra2.domain.census`); the table is `census_bucket` as
    sw-design.md §4.2 names it.
    """

    __tablename__ = "census_bucket"

    corpus_id: Mapped[CorpusId] = mapped_column(
        ForeignKey("corpus.id", ondelete="CASCADE"), primary_key=True
    )
    #: A `ra2.domain.census.CensusBucketLabel` value: `100-80` … `20-0`,
    #: `empty`. The "100–80 %" rendering lives in `ra2/ui/`.
    bucket_label: Mapped[str] = mapped_column(String(16), primary_key=True)
    column_count: Mapped[int]


# ===========================================================================
# Evaluation — phase 2. Present in phase 1 only so the delete guard is real.
# ===========================================================================


class Evaluation(Base):
    """one corpus + one feature config + N models (mvp-spec.md §9).

    **Phase 1 never creates one.** The table exists because sw-design.md §6.3
    requires the corpus delete guard — "deleting a corpus is refused (HTTP 409)
    when any evaluation cites it" — to be implemented and tested against a
    seeded row, and J3 asserts the `LOCKED · 1 eval` pill in the UI.

    `feature_config_id` is therefore a plain string with **no foreign key**:
    `feature_config` is a phase-2 table and pulling it forward would freeze a
    schema nobody has reviewed. Phase 2 adds the FK in its own migration.
    """

    __tablename__ = "evaluation"
    __table_args__ = (Index("ix_evaluation_corpus_id", "corpus_id"),)

    id: Mapped[EvaluationId] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    #: RESTRICT, not CASCADE: the delete guard is enforced in the service with
    #: a clear 409, and the database refuses it too if anything slips past.
    corpus_id: Mapped[CorpusId] = mapped_column(ForeignKey("corpus.id", ondelete="RESTRICT"))
    #: Phase 2 (M9): a real FK, replacing M0-D1's plain string. RESTRICT for
    #: the same reason as `corpus_id` — a frozen config an evaluation cites
    #: cannot be deleted out from under it (drafts still can be, per the
    #: design's "drafts can be renamed and deleted").
    feature_config_id: Mapped[FeatureConfigId] = mapped_column(
        ForeignKey("feature_config.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime | None] = mapped_column(default=None)
    #: mvp-spec.md §9 — a run over a corpus below the floor is a smoke test.
    is_dev: Mapped[bool] = mapped_column(default=False)


# ===========================================================================
# Codelists — phase 2, mvp-spec.md §5/§7, sw-design.md §14. Additive, never
# edited in place: a corrected import is a new `code_table_import` (Do-NOT #2).
# ===========================================================================


class CodeTableImport(Base):
    """One `codes-2018.json` (or successor) upload (sw-design.md §14.1).

    Never updated: a corrected file is a new row, and existing
    `column_mapping` rows are left pointing at the old generation until an
    analyst re-points them.
    """

    __tablename__ = "code_table_import"

    id: Mapped[CodeTableImportId] = mapped_column(primary_key=True)
    #: The uploaded filename. Display only, like `delivery_file.filename`.
    source_file: Mapped[str] = mapped_column(String(400))
    #: An analyst-facing label if one is ever supplied (e.g. "2018"); `None`
    #: is the common case. Distinct from `source_hash`, which is what dedupe
    #: actually keys on.
    source_version: Mapped[str | None] = mapped_column(String(64), default=None)
    #: sw-design.md §14.1 step 2 — additive beyond mvp-spec.md §5, the
    #: no-op-reupload dedupe key.
    source_hash: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[datetime]

    attributes: Mapped[list[CodeAttribute]] = relationship(
        back_populates="code_table_import", cascade="all, delete-orphan"
    )


class CodeAttribute(Base):
    """One top-level key of an imported codelist file (mvp-spec.md §5).

    Distinct from `ra2.domain.codes.CodeAttribute`, the pure pre-persistence
    shape `validate_import` produces.
    """

    __tablename__ = "code_attribute"
    __table_args__ = (
        UniqueConstraint("code_table_import_id", "key", name="uq_code_attribute_import_key"),
        Index("ix_code_attribute_code_table_import_id", "code_table_import_id"),
    )

    id: Mapped[CodeAttributeId] = mapped_column(primary_key=True)
    code_table_import_id: Mapped[CodeTableImportId] = mapped_column(
        ForeignKey("code_table_import.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(100))
    #: e.g. "4.1.4". Absent for non-chapter attributes.
    chapter: Mapped[str | None] = mapped_column(String(32), default=None)
    #: `{lang: display name}`, serialised (M0-D8 convention).
    name_json: Mapped[str]

    code_table_import: Mapped[CodeTableImport] = relationship(back_populates="attributes")
    values: Mapped[list[CodeValue]] = relationship(
        back_populates="code_attribute", cascade="all, delete-orphan"
    )


class CodeValue(Base):
    """One `(attribute, code)` pair (mvp-spec.md §5). `label_json` may omit
    languages — the known gap: `main_cause*` attributes have no `it`.

    No dedicated id `NewType` (plan-phase-2.md §5.1 names five, not six):
    nothing joins against a `code_value` by id outside its own attribute.
    """

    __tablename__ = "code_value"
    __table_args__ = (
        UniqueConstraint("code_attribute_id", "code", name="uq_code_value_attribute_code"),
        Index("ix_code_value_code_attribute_id", "code_attribute_id"),
    )

    id: Mapped[str] = mapped_column(String(_ID_LEN), primary_key=True)
    code_attribute_id: Mapped[CodeAttributeId] = mapped_column(
        ForeignKey("code_attribute.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(32))
    #: `{lang: label}`, serialised (M0-D8 convention).
    label_json: Mapped[str]

    code_attribute: Mapped[CodeAttribute] = relationship(back_populates="values")


class ColumnMapping(Base):
    """`(corpus_id, source_column) -> code_attribute_id` (mvp-spec.md §5).

    The only editable table Codelists introduces — re-editable at will,
    never writing to `code_value` or `code_attribute` (mvp-spec.md §7).
    """

    __tablename__ = "column_mapping"
    __table_args__ = (
        UniqueConstraint("corpus_id", "source_column", name="uq_column_mapping_corpus_column"),
        Index("ix_column_mapping_corpus_id", "corpus_id"),
    )

    id: Mapped[ColumnMappingId] = mapped_column(primary_key=True)
    corpus_id: Mapped[CorpusId] = mapped_column(ForeignKey("corpus.id", ondelete="CASCADE"))
    source_column: Mapped[str] = mapped_column(String(100))
    #: RESTRICT: `code_attribute` rows are never deleted (Do-NOT #2), but the
    #: constraint costs nothing and matches the rest of the schema's caution.
    code_attribute_id: Mapped[CodeAttributeId] = mapped_column(
        ForeignKey("code_attribute.id", ondelete="RESTRICT")
    )
    mapped_at: Mapped[datetime]


# ===========================================================================
# Feature configuration — phase 2, mvp-spec.md §5/§8.
# ===========================================================================


class FeatureConfig(Base):
    """One feature set, draft or frozen (mvp-spec.md §8).

    `frozen_at` is set the moment "Create a feature set" is pressed (F2,
    plan-phase-2.md §15) — not deferred until an evaluation first cites it.
    """

    __tablename__ = "feature_config"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_feature_config_name_version"),)

    id: Mapped[FeatureConfigId] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    #: P2-D1 (CONTRACTS.md) — additive beyond mvp-spec.md §5: the design's
    #: feature-sets table has a "Description" column mvp-spec never named.
    description: Mapped[str | None] = mapped_column(default=None)
    #: P2-D2 — additive, same reasoning as `corpus.version`: the design shows
    #: "Weather & conditions v3" next to older v2/v1 sets sharing the name.
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime]
    frozen_at: Mapped[datetime | None] = mapped_column(default=None)

    features: Mapped[list[Feature]] = relationship(
        back_populates="feature_config",
        cascade="all, delete-orphan",
        order_by="Feature.ordinal",
    )


class Feature(Base):
    """One thing the model is asked to extract (mvp-spec.md §8).

    `matching_rule` holds serialised JSON (M0-D8 convention) despite lacking
    the `_json` suffix its two siblings have — mvp-spec.md §5 names the
    column that way and mvp-spec wins on *what* a column is called.
    """

    __tablename__ = "feature"
    __table_args__ = (
        UniqueConstraint("feature_config_id", "key", name="uq_feature_config_key"),
        Index("ix_feature_feature_config_id", "feature_config_id"),
    )

    id: Mapped[FeatureId] = mapped_column(primary_key=True)
    feature_config_id: Mapped[FeatureConfigId] = mapped_column(
        ForeignKey("feature_config.id", ondelete="CASCADE")
    )
    #: Display and pagination order within the set.
    ordinal: Mapped[int]
    key: Mapped[str] = mapped_column(String(100))
    kind: Mapped[Kind]
    #: Sent to the model verbatim (mvp-spec.md §8, design §"Description").
    description: Mapped[str]
    grain: Mapped[Grain]
    #: `None` for a derived-aggregate or exploratory feature.
    source_column: Mapped[str | None] = mapped_column(String(100), default=None)
    #: `None` unless `grain` is `derived`. Not executed in phase 2 (Q1).
    derivation_json: Mapped[str | None] = mapped_column(default=None)
    value_type: Mapped[ValueType]
    #: Serialised `ra2.domain.feature.MatchingRule`, including its parameters.
    matching_rule: Mapped[str]
    #: `None` unless `value_type` is `enum`. A snapshot taken at evaluation
    #: creation (§8.5) — phase 2 never sets this; only the preview fingerprint
    #: is shown before that point exists.
    enum_codelist_json: Mapped[str | None] = mapped_column(default=None)
    #: `None` until frozen. The draft's "· preview" badge is computed on the
    #: fly by `domain.fingerprint`, never stored ahead of the freeze.
    fingerprint: Mapped[str | None] = mapped_column(String(64), default=None)

    feature_config: Mapped[FeatureConfig] = relationship(back_populates="features")
