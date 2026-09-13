# FROZEN (types and signatures) — see CONTRACTS.md
"""The extraction output schema and its parser (mvp-spec.md §10.3, §10.4).

Two pure functions, one boundary:

- `build_output_schema(features)` builds the §10.3 shape **for this feature
  set** with `pydantic.create_model`. It becomes a JSON Schema and goes to the
  endpoint as the constrained-decoding format, so its **key order is stable
  across calls** — two runs must ask the same question (sw-design.md §15.3).
- `parse_output(raw, features)` **never raises and never repairs**. A missing
  key, an extra key, a non-null value with no evidence span, an enum value
  outside the snapshotted codelist: each is a typed, recorded outcome. This is
  how the Do-NOT list's #6 lands on model output — the row carrying the
  evidence *is* the finding, which is why this phase adds no `FindingCode`
  values.

`entities` is **captured and stored, never scored** in the MVP (mvp-spec.md
§10.3). It is the cheap capture that makes per-entity alignment possible later
without re-running the corpus.

Pure — no SQLAlchemy, no network (sw-design.md §15.7).

**M17 freezes the types and the signatures. H2 writes the bodies.**
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from pydantic import BaseModel

from ra2.domain.prompt import FeatureBlockEntry

__all__ = [
    "ENTITIES_KEY",
    "FEATURES_KEY",
    "TERMINAL_RUN_STATUSES",
    "EntityAnswer",
    "EvaluationSize",
    "ExtractionOutput",
    "FeatureAnswer",
    "ParseFailure",
    "ParseIssue",
    "ParseIssueCode",
    "ParsedExtraction",
    "ParsedValue",
    "RunStatus",
    "build_output_schema",
    "parse_output",
]

#: The two top-level keys of mvp-spec.md §10.3's shape. Named constants
#: because the schema builder, the parser and H1's template all have to agree
#: on them and a typo in any one of them is a silent adherence failure.
FEATURES_KEY = "features"
ENTITIES_KEY = "entities"


# ===========================================================================
# The run's own vocabulary
#
# `RunStatus` and `EvaluationSize` live here, beside the shapes a run
# produces, rather than in a module of their own: `domain/delivery.py` holds
# `DeliveryStatus` by exactly the same logic, and plan-phase-3.md §6's
# ownership matrix names four domain modules — a fifth would belong to no
# wave. Recorded as P3-D2 in CONTRACTS.md.
# ===========================================================================


class RunStatus(StrEnum):
    """One model's pass over one evaluation (sw-design.md §15.2)."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    #: The process died mid-run. **Nothing auto-restarts** (§15 F8): the
    #: Evaluation view offers an explicit Resume, because a run that resumes
    #: itself on every app start burns GPU hours on work the user may have
    #: abandoned.
    INTERRUPTED = "interrupted"


#: Statuses the worker never leaves on its own. `INTERRUPTED` is deliberately
#: absent — it is the one state a human moves out of.
TERMINAL_RUN_STATUSES: Final[frozenset[RunStatus]] = frozenset({RunStatus.DONE, RunStatus.FAILED})


class EvaluationSize(StrEnum):
    """The design's step 6: "Evaluation · all N" or "Dev · N records".

    A `DEV` selection takes the **first `RA2_DEV_RECORD_MAX` records by id** —
    deterministic, because "a re-run is a check, not a new sample" is false the
    moment the record selection is random (§15 F9). The seed fixes what the
    model does with what it sees; determinism has to cover what it is *shown*
    too.
    """

    FULL = "full"
    DEV = "dev"


# ===========================================================================
# The wire shape — mvp-spec.md §10.3, as Pydantic
# ===========================================================================


class FeatureAnswer(BaseModel):
    """One feature's answer. `value` is the **code** for an enum.

    `evidence` is a span quoted **verbatim from the narrative** and is
    required for every non-null value (mvp-spec.md §10.2). `present` is the
    per-feature presence flag, scored as Goal 2 in phase 4.
    """

    value: str | float | bool | None = None
    present: bool = False
    evidence: str | None = None


class EntityAnswer(BaseModel):
    """One vehicle or person, referenced by the role codes the anonymisation
    uses (`B1`, `G1`, `P`). Captured, never scored (mvp-spec.md §10.3)."""

    kind: str
    ref: str
    attributes: dict[str, str] = {}


class ExtractionOutput(BaseModel):
    """The **generic** §10.3 envelope: `{features: {...}, entities: [...]}`.

    The schema actually sent to the endpoint is the *narrow* one
    `build_output_schema` derives per feature set, with one declared key per
    feature key rather than an open mapping — constrained decoding is only
    worth anything when the schema names the keys. This class is what the
    generic half of the shape looks like, and what a parse result is measured
    against.
    """

    features: dict[str, FeatureAnswer] = {}
    entities: list[EntityAnswer] = []


# ===========================================================================
# The parse result — a datum either way (mvp-spec.md §10.4)
# ===========================================================================


class ParseIssueCode(StrEnum):
    """What was wrong with one part of an otherwise-usable response.

    A **stable identifier**, asserted on instead of message text (CLAUDE.md,
    "Findings, not prose"). These are *not* `FindingCode` values: a parse
    problem is recorded on the `extraction` row that already carries the raw
    output, not reported through the import-report vocabulary.
    """

    #: A configured feature has no key in the response.
    MISSING_FEATURE = "missing_feature"
    #: The response carries a key no feature asked for.
    UNKNOWN_FEATURE = "unknown_feature"
    #: A non-null value arrived with no evidence span (mvp-spec.md §10.2).
    MISSING_EVIDENCE = "missing_evidence"
    #: An enum answer that is not a code in the evaluation's snapshot.
    ENUM_CODE_NOT_IN_CODELIST = "enum_code_not_in_codelist"
    #: The value could not be read as the feature's `value_type`.
    VALUE_TYPE_MISMATCH = "value_type_mismatch"


@dataclass(frozen=True, slots=True)
class ParseIssue:
    """One recorded problem, carrying the key it belongs to (Do-NOT #6)."""

    code: ParseIssueCode
    feature_key: str | None = None
    #: The offending value, verbatim, where there is one.
    value_raw: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedValue:
    """One feature's parsed answer — the `extraction_value` row's contents.

    `value_raw` is stored **verbatim**; `value_normalised` is exact-and-trimmed
    only (D6: no fuzzy matching, ever). Normalisation is a read-time domain
    function, never an in-place rewrite of what the model said.
    """

    feature_key: str
    value_raw: str | None
    value_normalised: str | None
    present_flag: bool
    evidence_span: str | None


@dataclass(frozen=True, slots=True)
class ParsedExtraction:
    """A response that parsed. It may still carry issues.

    `parse_ok` is `True` here by construction: the JSON was readable and the
    envelope matched. Per-feature problems live in `issues` and do **not**
    make the extraction a failure — the run continues either way
    (mvp-spec.md §10.4).
    """

    values: tuple[ParsedValue, ...]
    entities: tuple[EntityAnswer, ...] = ()
    issues: tuple[ParseIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class ParseFailure:
    """A response that could not be read at all — truncated JSON, prose
    instead of JSON, an envelope of the wrong shape.

    Stored as `parse_ok = False` with `parse_error` set and the raw output
    kept **verbatim**, and **the run continues**. A parse failure is a datum,
    not an exception (sw-design.md §15.3).
    """

    reason: str
    issues: tuple[ParseIssue, ...] = ()


def build_output_schema(features: Sequence[FeatureBlockEntry]) -> type[BaseModel]:
    """The mvp-spec.md §10.3 shape, narrowed to *this* feature set.

    Built with `pydantic.create_model`: one declared key per feature key, each
    a `FeatureAnswer`, plus `entities`. The returned model's JSON Schema is
    what goes to the endpoint as the constrained-decoding format.

    **Key order is stable across calls** for the same feature sequence — the
    schema is part of the question, and two runs of the same evaluation must
    ask the same one (sw-design.md §15.3).
    """
    raise NotImplementedError


def parse_output(
    raw: str,
    features: Sequence[FeatureBlockEntry],
    *,
    enum_codelists: Mapping[str, frozenset[str]] | None = None,
) -> ParsedExtraction | ParseFailure:
    """Read one model response. **Never raises, never repairs.**

    :param raw: the response text, exactly as the endpoint returned it.
    :param features: the configured features — the authority on which keys
        should be present and what type each value is.
    :param enum_codelists: `{feature_key: {valid code, ...}}` from the
        evaluation's `enum_codelist_json` snapshot. A value outside its set is
        an `ENUM_CODE_NOT_IN_CODELIST` issue, never a silent repair and never
        a dropped row (Do-NOT #6).

    :returns: a `ParsedExtraction` when the envelope was readable — possibly
        carrying issues — or a `ParseFailure` when it was not. Both are
        outcomes the caller persists; neither is an exception.
    """
    raise NotImplementedError
