# FROZEN — see CONTRACTS.md
"""The schema (mvp-spec.md §5 + sw-design.md §4, §14, §15).

**Scope.** Phase 1 built import and census, phase 2 added codelists and
feature configs, and phase 3 (M17) adds prompts and runs — `prompt_template`,
`evaluation_feature`, `run`, `extraction`, `extraction_value`,
`extraction_entity`, plus the setup columns `evaluation` was always implying.
Phase 4 (M27) adds the last two tables mvp-spec.md §5 names — `score` and
`mismatch` — plus `evaluation.min_cell_count`. Nothing in §5 is unbuilt after
this.

**Immutability (N5, §12.2).** `corpus` and everything below it —
`record`, `unfall_row`, `objekt_row`, `objekt_cell`, `person_row`,
`person_cell`, `census_*` — is written once at freeze and never updated. So is
`prompt_template` (a save is a new version) and so is `extraction` and its two
child tables (a re-run adds rows). `delivery`, `delivery_file`,
`column_mapping`, a draft `feature_config` and an unlaunched `evaluation` are
the mutable ones: re-parsing after an encoding override rewrites a
`delivery_file` row, and a draft is editable until it is pinned.

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

from datetime import UTC, datetime

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
from sqlalchemy.types import TypeDecorator

from ra2.domain.census import TypeHint
from ra2.domain.delivery import DeliveryStatus, FileKind, SourceKind
from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.domain.feature import Grain, Kind, ValueType
from ra2.domain.ids import (
    CensusColumnId,
    CodeAttributeId,
    CodeTableImportId,
    ColumnMappingId,
    CorpusId,
    DeliveryId,
    EvaluationId,
    ExtractionId,
    FeatureConfigId,
    FeatureId,
    FileId,
    MismatchId,
    ObjektRowId,
    PersonRowId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.domain.scoring import ScoreMetric

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
    "EvaluationFeature",
    "Extraction",
    "ExtractionEntity",
    "ExtractionValue",
    "Feature",
    "FeatureConfig",
    "Mismatch",
    "ObjektCell",
    "ObjektRow",
    "PersonCell",
    "PersonRow",
    "PromptTemplate",
    "Record",
    "Run",
    "Score",
    "UnfallRow",
    "UtcDateTime",
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


class UtcDateTime(TypeDecorator[datetime]):
    """`DateTime(timezone=True)` that always hands back an **aware** UTC value.

    `Clock.now()` is "timezone-aware, UTC. Never naive — every stored timestamp
    carries its offset so a Windows and a Linux run agree" (`infra/clock.py`).
    SQLite has nowhere to keep that offset: it stores the wall clock as text and
    returns it **naive**, so subtracting a stored timestamp from a fresh
    `Clock.now()` raises `TypeError`.

    Phase 3 hit this twice — `evaluation_service` and `run_service` each grew a
    private `_as_utc` helper within a wave of each other — and `P3-D15` recorded
    that near-identical code in two services means the asymmetry belongs one
    layer down, where every caller inherits the fix instead of remembering it.
    Same column type, same stored bytes, **no migration**.

    Binding normalises to UTC first, which is what makes reading a naive value
    back *as* UTC sound rather than merely conventional: a caller that passed a
    `+02:00` timestamp would otherwise have its wall clock stored and reread two
    hours wrong, silently.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


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
        PromptTemplateId: String(_ID_LEN),
        RunId: String(_ID_LEN),
        ExtractionId: String(_ID_LEN),
        MismatchId: String(_ID_LEN),
        FileKind: String(16),
        SourceKind: String(16),
        DeliveryStatus: String(16),
        TypeHint: String(16),
        Kind: String(16),
        Grain: String(16),
        ValueType: String(16),
        RunStatus: String(16),
        EvaluationSize: String(16),
        ScoreMetric: String(32),
        datetime: UtcDateTime(),
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

    **A draft is a saved setup; an evaluation is a pinned one** (sw-design.md
    §15.2). Every column below is editable while `launched_at IS NULL` and
    immutable after — `evaluation_service.launch` stamps it, writes the
    `evaluation_feature` snapshot and creates one `queued` `run` per selected
    model, all in one transaction. After that every edit path raises
    `EvaluationLockedError`.

    Phases 1 and 2 never created one: the table existed because sw-design.md
    §6.3 requires the corpus delete guard — "deleting a corpus is refused
    (HTTP 409) when any evaluation cites it" — to be tested against a seeded
    row, and J3 asserts the `LOCKED · 1 eval` pill. Phase 3 is where it grows
    the setup it was always implying (SD13).
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

    # --- phase 3 (M17): the setup the design's six steps collect -----------

    #: Step 3. **Nullable on purpose**: a draft can be saved before any
    #: template exists, and the launch transaction is what requires one.
    #: RESTRICT is the other half of "delete only when uncited" — a `run`
    #: citing a version is the hard guard (see `Run.prompt_template_id`);
    #: this one keeps a draft's choice from vanishing under it.
    prompt_template_id: Mapped[PromptTemplateId | None] = mapped_column(
        ForeignKey("prompt_template.id", ondelete="RESTRICT"), default=None
    )
    #: C1 / §15 F10 — the prompt language belongs to the **evaluation**, not
    #: to the template: the codelist labels the prompt carries are
    #: language-specific, and which language is a property of the question
    #: being asked, not of the wording asking it. A `ra2.domain.language.
    #: Language` value, stored as a plain string for the same reason
    #: `record.language` is (M0-D7).
    prompt_language: Mapped[str] = mapped_column(String(16), default="de")
    #: Step 5. The design draws 0.0 and 42; both travel in every run's
    #: provenance (mvp-spec.md §19.8).
    temperature: Mapped[float] = mapped_column(default=0.0)
    seed: Mapped[int] = mapped_column(default=42)
    #: Step 6. `DEV` takes the first `RA2_DEV_RECORD_MAX` records by id —
    #: deterministic, so a re-run is a check and not a new sample (§15 F9).
    size: Mapped[EvaluationSize] = mapped_column(default=EvaluationSize.FULL)
    #: Step 4, serialised (M0-D8 convention): `["llama3.1:8b-instruct-q8_0",
    #: ...]`. One `run` per entry is created at launch. No FK — a model tag
    #: is what the endpoint happens to hold, not a row this app owns.
    selected_models_json: Mapped[str | None] = mapped_column(default=None)
    #: `None` while this is a draft. Stamping it is the launch commit, and
    #: "evaluation creation" in mvp-spec.md §8.5's sense is **this moment** —
    #: not the moment the draft row appeared (sw-design.md §15.2).
    launched_at: Mapped[datetime | None] = mapped_column(default=None)

    # --- phase 4 (M27) ------------------------------------------------------

    #: mvp-spec.md §11.4's floor: "cells with n below the minimum count render
    #: as 'insufficient data', never as a number. Default **20**, configurable
    #: **per evaluation**." Defaulted from `config.min_cell_count` when the
    #: draft is created, and pinned like every other input at launch.
    #:
    #: A column rather than a global constant because the spec says so, and
    #: because it is cheap: **suppression is applied at read time** from stored
    #: `n` (SD19), so raising or lowering this never requires a re-score.
    min_cell_count: Mapped[int] = mapped_column(default=20)

    features: Mapped[list[EvaluationFeature]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan", passive_deletes=True
    )
    runs: Mapped[list[Run]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan", passive_deletes=True
    )


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


# ===========================================================================
# Prompts and evaluation runs — phase 3, mvp-spec.md §5/§9/§10,
# sw-design.md §15. `prompt_template`, `extraction` and everything under it
# are IMMUTABLE: a save is a new row, a re-run is a new run (N5, Do-NOT #2).
# ===========================================================================


class PromptTemplate(Base):
    """One version of the wording around the feature descriptions (§15.1).

    **IMMUTABLE. A save is an `INSERT` at `version + 1`, never an `UPDATE`** —
    copy-on-write, not versioning-by-convention: the runs citing a version
    must keep resolving to the exact text they used, so the previous row's
    `source` stays byte-identical. There is deliberately no `PATCH` route and
    no service method that updates a `source`; the absence is the contract.

    mvp-spec.md §10.2 called this "a versioned **on-disk** template". SD11
    corrects it: the design's version list carries a citation count, an active
    flag, a per-version fingerprint and "delete only when nothing cites it",
    and the one that matters is enforceable only where the citations are —
    which is `Run.prompt_template_id`'s `RESTRICT`, below.
    """

    __tablename__ = "prompt_template"
    __table_args__ = (
        UniqueConstraint("version", name="uq_prompt_template_version"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[PromptTemplateId] = mapped_column(primary_key=True)
    #: One lineage, `v1…vN`, **no names** — a name is what a forked template
    #: needs and nothing in the MVP forks one (§15.1, plan-phase-3.md C2).
    version: Mapped[int]
    #: The template text, verbatim, `{{slots}}` and all. Never rewritten.
    source: Mapped[str]
    created_at: Mapped[datetime]
    #: Marks the one version new evaluations default to. Activating another
    #: clears it, so at most one row is non-null at a time.
    activated_at: Mapped[datetime | None] = mapped_column(default=None)
    #: `domain.prompt.compute_template_fingerprint(source)` — sha256 over the
    #: exact source. Stored on every run beside the model digest.
    fingerprint: Mapped[str] = mapped_column(String(64))


class EvaluationFeature(Base):
    """The per-evaluation resolution of one feature (SD12, §15.2).

    mvp-spec.md §5 puts `enum_codelist_json` and `fingerprint` on `feature`.
    Phase 2 then decided a frozen `feature_config` is corpus-**independent**
    and reusable across evaluations (plan-phase-2.md §15 F2), and the two
    cannot both hold: the same frozen config cited against two corpora has two
    different `column_mapping` generations under it, so two different codelist
    snapshots and two different fingerprints.

    **Written once, inside the launch transaction**, and never updated. That
    is what makes "a later `code_table_import` never moves the fingerprint of
    an already-created evaluation" (mvp-spec.md §8.5) true.

    `feature.fingerprint` (phase 2) stays the draft-time **preview**: the same
    function over the same inputs minus the codelist snapshot, which is
    exactly why a preview badge and a run's fingerprint can legitimately
    differ.
    """

    __tablename__ = "evaluation_feature"
    __table_args__ = (Index("ix_evaluation_feature_evaluation_id", "evaluation_id"),)

    evaluation_id: Mapped[EvaluationId] = mapped_column(
        ForeignKey("evaluation.id", ondelete="CASCADE"), primary_key=True
    )
    #: RESTRICT: a frozen config's features are never deleted, and an
    #: evaluation citing one must not be able to lose its snapshot.
    feature_id: Mapped[FeatureId] = mapped_column(
        ForeignKey("feature.id", ondelete="RESTRICT"), primary_key=True
    )
    #: The mapped attribute's whole code table, **including label text**,
    #: serialised at launch (M0-D8 convention). `None` unless the feature's
    #: `value_type` is `enum`.
    enum_codelist_json: Mapped[str | None] = mapped_column(default=None)
    #: `domain.fingerprint.compute_fingerprint` over the eight §8.5 inputs
    #: *with* the snapshot above — the real one, not the draft preview.
    fingerprint: Mapped[str] = mapped_column(String(64))

    evaluation: Mapped[Evaluation] = relationship(back_populates="features")


class Run(Base):
    """One model's pass over one evaluation (mvp-spec.md §5, §9).

    **Provenance is written at run start, not at completion** (§15.4): a run
    that dies mid-corpus is still a reproducible run (mvp-spec.md §19.8).

    There is **no `records_done` column**. Progress is
    `COUNT(extraction WHERE run_id = …)` over an indexed column (§15 F6): a
    counter would be a second source of truth that a restart can disagree
    with, and being wrong about how much work is done is the one thing this
    worker cannot afford.
    """

    __tablename__ = "run"
    __table_args__ = (Index("ix_run_evaluation_id", "evaluation_id"),)

    id: Mapped[RunId] = mapped_column(primary_key=True)
    evaluation_id: Mapped[EvaluationId] = mapped_column(
        ForeignKey("evaluation.id", ondelete="CASCADE")
    )

    # --- what varies inside an evaluation: the model, and only the model ---
    model_name: Mapped[str] = mapped_column(String(200))
    #: mvp-spec.md §19.8 — the digest, not just the tag. A tag is mutable at
    #: the endpoint; the digest is what makes the run reproducible.
    model_digest: Mapped[str] = mapped_column(String(64))

    # --- the pinned inputs, copied here so a run is self-describing --------
    #: mvp-spec.md §5's human-facing citation, kept as drawn ("prompt template
    #: v4").
    prompt_template_version: Mapped[int]
    #: Added beside it (§15.2): a version integer alone cannot resolve exact
    #: text once a lineage is long. **RESTRICT is "delete only when
    #: uncited"** — the database refuses to drop a version a run cites, which
    #: is the invariant §15.1 says can only be enforced where the citations
    #: are.
    prompt_template_id: Mapped[PromptTemplateId] = mapped_column(
        ForeignKey("prompt_template.id", ondelete="RESTRICT")
    )
    prompt_template_fingerprint: Mapped[str] = mapped_column(String(64))
    temperature: Mapped[float]
    seed: Mapped[int]

    # --- lifecycle ---------------------------------------------------------
    status: Mapped[RunStatus] = mapped_column(default=RunStatus.QUEUED)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    #: Why a `failed` run failed — the design's muted "log" action. A failure
    #: is a recorded outcome, never a silent stop (mvp-spec.md §10.4).
    error: Mapped[str | None] = mapped_column(default=None)

    # --- host provenance (mvp-spec.md §19.8) -------------------------------
    #: e.g. `win11-x64`. `platform.platform()`'s answer, not a guess.
    host_platform: Mapped[str] = mapped_column(String(200))
    #: `None` when `GpuProbe.describe()` returned `None` — an honest
    #: "unknown", not an error (§15.6).
    gpu_name: Mapped[str | None] = mapped_column(String(200), default=None)
    llm_endpoint: Mapped[str] = mapped_column(String(400), default="")
    #: `RA2_LLM_REASONING_EFFORT` as this run asked it — beside the model
    #: digest, the temperature and the seed, because it decides the answer as
    #: much as they do. On the reporting host the same record cost 190 s at
    #: the model's own default and 6 s at `none`, and both answered correctly;
    #: whether the thinking one is *better* is what RA2 exists to measure, so
    #: two runs that differ in it must not look identical afterwards.
    #:
    #: `None` on rows written before the column existed — an honest "this run
    #: did not record it", never a guessed default (`gpu_name`'s reasoning).
    llm_reasoning_effort: Mapped[str | None] = mapped_column(String(16), default=None)

    evaluation: Mapped[Evaluation] = relationship(back_populates="runs")
    extractions: Mapped[list[Extraction]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    #: Phase 4. Deleting a run takes its scores with it — they are derived, so
    #: there is nothing to preserve. Its mismatches go too: a tag on a run that
    #: no longer exists describes nothing.
    scores: Mapped[list[Score]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    mismatches: Mapped[list[Mismatch]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class Extraction(Base):
    """One model's output for one `(run, record)` (mvp-spec.md §5, §10.4).

    **IMMUTABLE** (N5). A re-run creates a new `run` and new rows; `run_id` is
    the discriminator everywhere.

    `UNIQUE (run_id, record_id)` **is the resume key** (§15.3). Resume is "the
    record ids in this run's scope with no `extraction` row" — a query, not
    bookkeeping — and the constraint means a double write raises instead of
    quietly updating (Do-NOT #2). Note the resume set can have **holes in the
    middle**, not just a missing tail: a record whose retries were exhausted
    leaves one, and resume must find it.

    One of these rows, its `extraction_value` children and its
    `extraction_entity` children are committed **together, per record**.
    Nothing batches across records, and nothing holds a transaction open
    across an LLM call.
    """

    __tablename__ = "extraction"
    __table_args__ = (
        UniqueConstraint("run_id", "record_id", name="uq_extraction_run_record"),
        Index("ix_extraction_run_id", "run_id"),
    )

    id: Mapped[ExtractionId] = mapped_column(primary_key=True)
    run_id: Mapped[RunId] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    #: RESTRICT: an extraction is evidence. A corpus delete is already refused
    #: while an evaluation cites it (§6.3); this is the second lock.
    record_id: Mapped[RecordId] = mapped_column(ForeignKey("record.id", ondelete="RESTRICT"))

    #: The response **verbatim**, stored alongside the parsed values
    #: (mvp-spec.md §10.4). Non-null: a record whose retries were exhausted
    #: leaves no row at all, so every row here has text.
    raw_output_text: Mapped[str]
    #: `False` is a **recorded outcome, not an exception** — the run
    #: continues. The row carrying the evidence *is* the finding, which is why
    #: this phase adds no `FindingCode` values (§15.3).
    parse_ok: Mapped[bool] = mapped_column(default=True)
    parse_error: Mapped[str | None] = mapped_column(default=None)

    latency_ms: Mapped[int | None] = mapped_column(default=None)
    #: The **real** counts, from the endpoint. `domain.prompt.estimate_tokens`
    #: is the preview's estimate; these are the numbers that have to be right.
    prompt_tokens: Mapped[int | None] = mapped_column(default=None)
    completion_tokens: Mapped[int | None] = mapped_column(default=None)
    #: mvp-spec.md §10.4 — retries are bounded **and counted**. Rendered in
    #: the progress card's "retries 11 (bounded, counted)" metrics line.
    retry_count: Mapped[int] = mapped_column(default=0)

    run: Mapped[Run] = relationship(back_populates="extractions")
    values: Mapped[list[ExtractionValue]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan", passive_deletes=True
    )
    entities: Mapped[list[ExtractionEntity]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan", passive_deletes=True
    )


class ExtractionValue(Base):
    """One feature's answer inside one extraction (mvp-spec.md §5).

    One row per `(extraction, feature)` — the composite primary key says so,
    the same shape `unfall_row` uses for its cells.
    """

    __tablename__ = "extraction_value"

    extraction_id: Mapped[ExtractionId] = mapped_column(
        ForeignKey("extraction.id", ondelete="CASCADE"), primary_key=True
    )
    feature_id: Mapped[FeatureId] = mapped_column(
        ForeignKey("feature.id", ondelete="RESTRICT"), primary_key=True
    )
    #: What the model said, **verbatim**. `None` is a real answer: the
    #: narrative did not support a value.
    value_raw: Mapped[str | None] = mapped_column(default=None)
    #: Exact-and-trimmed only (D6). Never fuzzy, never a repair.
    value_normalised: Mapped[str | None] = mapped_column(default=None)
    present_flag: Mapped[bool] = mapped_column(default=False)
    #: A span quoted **verbatim from the narrative**, required for every
    #: non-null value (mvp-spec.md §10.2). Its absence is a recorded issue,
    #: not a dropped row.
    evidence_span: Mapped[str | None] = mapped_column(default=None)

    extraction: Mapped[Extraction] = relationship(back_populates="values")


class ExtractionEntity(Base):
    """One vehicle or person the model reported (mvp-spec.md §5, §10.3).

    **Captured and stored, never scored** in the MVP. It is the cheap capture
    that makes set matching and per-entity alignment possible later without
    re-running the corpus.

    A plain string primary key, no dedicated id `NewType` — the same treatment
    `code_value` gets (P2-D6): nothing joins against one of these by id
    outside its own extraction. A model that repeats `(kind, ref)` therefore
    produces two rows rather than a constraint violation, which is the right
    answer for output nothing scores.
    """

    __tablename__ = "extraction_entity"
    __table_args__ = (Index("ix_extraction_entity_extraction_id", "extraction_id"),)

    id: Mapped[str] = mapped_column(String(_ID_LEN), primary_key=True)
    extraction_id: Mapped[ExtractionId] = mapped_column(
        ForeignKey("extraction.id", ondelete="CASCADE")
    )
    #: `vehicle` | `person`, as the model wrote it. Not an enum: nothing
    #: scores this, and a fourth kind must be a value, not a migration.
    entity_kind: Mapped[str] = mapped_column(String(32))
    #: The role code the anonymisation uses — `B1`, `G1`, `P`.
    entity_ref: Mapped[str] = mapped_column(String(32))
    #: The free attribute bag, serialised (M0-D8 convention).
    attributes_json: Mapped[str]

    extraction: Mapped[Extraction] = relationship(back_populates="entities")


# ===========================================================================
# Scoring — phase 4 (M27), mvp-spec.md §5/§11/§12, sw-design.md §16.
#
# `score` is derived and rewritable: it is a pure function of immutable inputs,
# so a re-score either reproduces a feature's rows byte-for-byte or the scorer
# changed, and in both cases replacement is correct. `mismatch` is **not** —
# it is the one row in this pipeline a human writes to (SD21).
# ===========================================================================


class Score(Base):
    """One metric, for one `(run, feature, language)` (mvp-spec.md §5, §11).

    **Written one `(run, feature)` at a time, in one transaction** — every
    language and every metric for that pair together (sw-design.md §16.1). That
    boundary is what makes the pass resumable: the features of a run with no
    `score` rows are the work left, which is a query rather than bookkeeping,
    and an interrupted pass leaves whole features done and whole features
    absent, never a feature half-scored from two different reads of the corpus.

    **There is no scoring-status column anywhere**, for the reason §15.3
    refused `records_done`: the count that answers "how far did it get" is the
    same one that answers "where does it resume", so the two cannot disagree.

    `metric` is `domain.scoring.ScoreMetric`'s closed vocabulary, and it holds
    **raw counts as well as rates** (SD18) — the design's breakdown row needs
    hit/wrong/missing and its cross-tab needs six cells, and back-deriving
    those from three rounded floats is off by one exactly at small `n`, where
    the number matters most. `ci_low`/`ci_high` are `None` for a count.

    `n` is the **labelled-case count** for this cell, never the corpus size: a
    record whose source column is empty left the denominator entirely (§8.6).
    Suppression is *not* applied here — every cell is computed and stored, and
    the read model substitutes the insufficient-data shape (SD19).
    """

    __tablename__ = "score"
    __table_args__ = (Index("ix_score_run_id", "run_id"),)

    run_id: Mapped[RunId] = mapped_column(
        ForeignKey("run.id", ondelete="CASCADE"), primary_key=True
    )
    feature_id: Mapped[FeatureId] = mapped_column(
        ForeignKey("feature.id", ondelete="RESTRICT"), primary_key=True
    )
    #: The language this cell is about, or `domain.scoring.ALL_LANGUAGES`
    #: (`'*'`) for the all-languages row.
    #:
    #: **`NOT NULL`, against mvp-spec.md §5's `language|NULL`** (SD16). SQL
    #: treats two NULLs as distinct in a unique constraint, so a composite key
    #: over a nullable column permits exactly the duplicate rows it looks like
    #: it prevents — and "rewrite this feature's rows" would orphan the old
    #: ones on every re-score. The sentinel makes the key real.
    language: Mapped[str] = mapped_column(String(16), primary_key=True)
    metric: Mapped[ScoreMetric] = mapped_column(primary_key=True)
    #: The rate, or the count as a float for `scoring.COUNT_METRICS`.
    value: Mapped[float]
    n: Mapped[int]
    #: Wilson 95 % bounds (D4). `None` for a count — a count has no interval,
    #: and a renderer must not reach for one.
    ci_low: Mapped[float | None] = mapped_column(default=None)
    ci_high: Mapped[float | None] = mapped_column(default=None)

    run: Mapped[Run] = relationship(back_populates="scores")


class Mismatch(Base):
    """One `wrong` outcome, for review (mvp-spec.md §5, §12).

    **The one mutable row in this pipeline.** Everything else is append-only:
    Do-NOT #2 covers `corpus`, `record` and `extraction`, prompt templates are
    copy-on-write, and code tables are superseded rather than edited. Tagging a
    mismatch is the whole of F11, so `analyst_tag`, `tagged_at` and `note` are
    written by review — and a **re-score upserts around them** rather than
    replacing the row (SD21).

    `UNIQUE (run_id, record_id, feature_id)` is what makes that upsert
    expressible. The obvious implementation — `DELETE` then `INSERT` — destroys
    review work silently, at the moment a developer is most confident, because
    they have just fixed the scorer.

    **The structured record is fully authoritative** (§12). `record_value` is
    what the corpus holds, `extracted_value` what the model said, and no
    adjudication step exists anywhere in the pipeline: the analyst's tag is a
    tally, and **nothing is ever rescored from it**.

    Phase 4 writes these rows and never reads them; `analyst_tag` stays `None`
    for the whole phase. The review view is F11, deliberately out of scope
    (plan-phase-4.md §1 Q1) — which is exactly why the rows are written now,
    so that phase is a view over data that already exists.
    """

    __tablename__ = "mismatch"
    __table_args__ = (
        UniqueConstraint("run_id", "record_id", "feature_id"),
        Index("ix_mismatch_run_id_feature_id", "run_id", "feature_id"),
    )

    id: Mapped[MismatchId] = mapped_column(primary_key=True)
    run_id: Mapped[RunId] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    record_id: Mapped[RecordId] = mapped_column(ForeignKey("record.id", ondelete="CASCADE"))
    feature_id: Mapped[FeatureId] = mapped_column(ForeignKey("feature.id", ondelete="RESTRICT"))
    #: What the corpus holds — authoritative, always.
    record_value: Mapped[str | None] = mapped_column(default=None)
    #: What the model said. Non-null by construction: a null model value is a
    #: `MISSING`, not a `WRONG`, and produces no row here.
    extracted_value: Mapped[str | None] = mapped_column(default=None)
    #: Quoted verbatim from the narrative. The evidence automatic
    #: hallucination triage would need, captured now because it is free and
    #: unrecoverable later (mvp-spec.md §16).
    evidence_span: Mapped[str | None] = mapped_column(default=None)

    # --- review (F11, phase 5). Preserved across a re-score. ---------------

    #: `hallucination` | `structured_data_error` | `unclear` (mvp-spec.md §12).
    #: Not an enum column: the vocabulary is the analyst's, a fourth tag must
    #: be a value rather than a migration, and **the tag never feeds back into
    #: a metric** — nothing is rescored from it, so nothing joins on it.
    analyst_tag: Mapped[str | None] = mapped_column(String(32), default=None)
    tagged_at: Mapped[datetime | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(default=None)

    run: Mapped[Run] = relationship(back_populates="mismatches")
