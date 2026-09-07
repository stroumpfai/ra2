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
from ra2.domain.ids import (
    CensusColumnId,
    CorpusId,
    DeliveryId,
    EvaluationId,
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
    "Corpus",
    "Delivery",
    "DeliveryFile",
    "Evaluation",
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
        FileKind: String(16),
        SourceKind: String(16),
        DeliveryStatus: String(16),
        TypeHint: String(16),
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

    records: Mapped[list[Record]] = relationship(
        back_populates="corpus", cascade="all, delete-orphan"
    )
    census_columns: Mapped[list[CensusColumn]] = relationship(
        back_populates="corpus", cascade="all, delete-orphan"
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
        back_populates="record", cascade="all, delete-orphan"
    )
    objekt_rows: Mapped[list[ObjektRow]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
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
        back_populates="objekt_row", cascade="all, delete-orphan"
    )
    person_rows: Mapped[list[PersonRow]] = relationship(
        back_populates="objekt_row", cascade="all, delete-orphan"
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
        back_populates="person_row", cascade="all, delete-orphan"
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
        CheckConstraint(
            "populated_rate >= 0.0 AND populated_rate <= 1.0", name="populated_rate_is_a_rate"
        ),
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
    #: Phase 2. No FK yet — see the class docstring.
    feature_config_id: Mapped[str | None] = mapped_column(String(_ID_LEN), default=None)
    created_at: Mapped[datetime | None] = mapped_column(default=None)
    #: mvp-spec.md §9 — a run over a corpus below the floor is a smoke test.
    is_dev: Mapped[bool] = mapped_column(default=False)
