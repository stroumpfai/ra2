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

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from ra2.domain.feature import ValueType
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


#: Class names for the two dynamically-built models. Fixed and unexported:
#: nothing outside this module inspects a schema's `__name__`, and reusing the
#: same two names across calls keeps the generated JSON Schema's `$defs`
#: labelling identical run to run, which is one less accidental source of
#: "two runs asked a different question" (sw-design.md §15.3).
_FEATURES_MODEL_NAME = "ExtractionFeatures"
_SCHEMA_MODEL_NAME = "ExtractionSchema"

#: `extra="forbid"` on both levels: constrained decoding is only worth
#: anything when the schema names every key and refuses an extra one, and a
#: `parse_output` that later meets an `UNKNOWN_FEATURE` key is reading a
#: response that *disagreed* with the very schema it was decoded against —
#: still recorded, never trusted as a shortcut past this rule.
_FORBID_EXTRA: Final = ConfigDict(extra="forbid")


def build_output_schema(features: Sequence[FeatureBlockEntry]) -> type[BaseModel]:
    """The mvp-spec.md §10.3 shape, narrowed to *this* feature set.

    Built with `pydantic.create_model`: one declared key per feature key, each
    a `FeatureAnswer`, plus `entities`. The returned model's JSON Schema is
    what goes to the endpoint as the constrained-decoding format.

    **Key order is stable across calls** for the same feature sequence — the
    schema is part of the question, and two runs of the same evaluation must
    ask the same one (sw-design.md §15.3). `pydantic.create_model`'s
    `**field_definitions` is an ordinary `dict`, and both `dict` insertion
    order and Pydantic's own field bookkeeping preserve it end to end, so the
    feature sequence's order is the schema's order, verbatim.
    """
    # Typed `dict[str, Any]` rather than the more precise
    # `dict[str, tuple[type[FeatureAnswer], Any]]`: mypy's `create_model`
    # overloads only unify a `**dict` of dynamic keys (the feature keys
    # themselves, known only at runtime) against `field_definitions: Any`.
    feature_fields: dict[str, Any] = {
        feature.key: (FeatureAnswer, Field(...)) for feature in features
    }
    features_model: type[BaseModel] = create_model(
        _FEATURES_MODEL_NAME,
        __config__=_FORBID_EXTRA,
        **feature_fields,
    )
    schema_fields: dict[str, Any] = {
        FEATURES_KEY: (features_model, Field(...)),
        ENTITIES_KEY: (list[EntityAnswer], Field(...)),
    }
    return create_model(
        _SCHEMA_MODEL_NAME,
        __config__=_FORBID_EXTRA,
        **schema_fields,
    )


#: `ParseFailure.reason` values. Short, stable identifiers rather than prose —
#: not a `StrEnum` because the frozen `ParseFailure` dataclass types `reason`
#: as `str`, but chosen and used the same way `ParseIssueCode` is: assert on
#: the value, never on a sentence built around it.
_REASON_INVALID_JSON = "invalid_json"
_REASON_NOT_AN_OBJECT = "not_an_object"
_REASON_FEATURES_NOT_OBJECT = "features_not_object"


def _stringify(value: object) -> str | None:
    """One JSON scalar — as `json.loads` produced it, **before** it is handed
    to `FeatureAnswer` — to `ParsedValue.value_raw`: a string, verbatim.

    Taken pre-validation deliberately: `FeatureAnswer.value`'s type is
    `str | float | bool | None` with no `int`, so Pydantic's lenient-union
    coercion would turn the JSON integer `2` into the Python float `2.0` and
    `value_raw` would read `"2.0"` for an answer the model wrote as `2` —
    "stored verbatim" (mvp-spec.md §10.4) means verbatim, not
    verbatim-after-a-union-coercion. `bool` is checked before `int`/`float`
    because `bool` is a Python subclass of `int`, and JSON's own literals
    (`true`/`false`) are used rather than Python's `True`/`False` so
    `value_raw` reads as the JSON the model produced.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(value)
    return str(value)  # pragma: no cover - unreachable once FeatureAnswer validated


def _value_matches_type(value: object, value_type: ValueType) -> bool:
    """A coarse "could this possibly be a `value_type`" check, over the same
    pre-validation JSON scalar `_stringify` takes.

    Deliberately coarse: mvp-spec.md §8.4's real normalisation and matching
    rules (rounding, date parsing, truthy mapping, ...) belong to Scoring
    (§11), which is unbuilt in phase 3 (sw-design.md §15.8) — `parse_output`
    only tells apart shapes the endpoint could plausibly have meant from ones
    it could not, e.g. a boolean feature answered with a code string. `None`
    always matches: an absent value is what `present` / `MISSING_FEATURE`
    already describe, not a type problem.
    """
    if value is None:
        return True
    if value_type is ValueType.BOOLEAN:
        return isinstance(value, bool)
    if isinstance(value, bool):
        # Only a BOOLEAN feature may answer with a bool.
        return False
    if value_type in (ValueType.INTEGER, ValueType.DECIMAL):
        return isinstance(value, int | float) or (isinstance(value, str) and value.strip() != "")
    # ENUM, DATE, TIME, FREE_TEXT all read as a string.
    return isinstance(value, str)


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
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Truncated JSON and "prose instead of JSON" (mvp-spec.md §10.4) look
        # identical to `json.loads`: neither is valid JSON, full stop. No
        # attempt is made to salvage an embedded `{...}` from surrounding
        # text — that would be *repairing* the response, which Do-NOT #6
        # forbids just as much for model output as for an imported row.
        return ParseFailure(reason=_REASON_INVALID_JSON)

    if not isinstance(data, dict):
        return ParseFailure(reason=_REASON_NOT_AN_OBJECT)

    features_raw = data.get(FEATURES_KEY)
    if not isinstance(features_raw, dict):
        # Missing entirely, or present as the wrong JSON type — either way
        # there is no per-feature content to recover anything from, which is
        # what makes this "an envelope of the wrong shape" rather than a set
        # of per-feature issues.
        return ParseFailure(reason=_REASON_FEATURES_NOT_OBJECT)

    configured_keys = {feature.key: feature for feature in features}
    values: list[ParsedValue] = []
    issues: list[ParseIssue] = []

    for feature in features:
        if feature.key not in features_raw:
            issues.append(ParseIssue(code=ParseIssueCode.MISSING_FEATURE, feature_key=feature.key))
            values.append(
                ParsedValue(
                    feature_key=feature.key,
                    value_raw=None,
                    value_normalised=None,
                    present_flag=False,
                    evidence_span=None,
                )
            )
            continue

        raw_answer = features_raw[feature.key]
        try:
            answer = FeatureAnswer.model_validate(raw_answer)
        except ValidationError:
            issues.append(
                ParseIssue(
                    code=ParseIssueCode.VALUE_TYPE_MISMATCH,
                    feature_key=feature.key,
                    value_raw=str(raw_answer),
                )
            )
            values.append(
                ParsedValue(
                    feature_key=feature.key,
                    value_raw=None,
                    value_normalised=None,
                    present_flag=False,
                    evidence_span=None,
                )
            )
            continue

        # Read the pre-validation JSON scalar for storage/type-checking
        # (see `_stringify`'s docstring); `raw_answer` is guaranteed a
        # mapping here, or `FeatureAnswer.model_validate` above would already
        # have raised.
        raw_value: object = raw_answer.get("value") if isinstance(raw_answer, dict) else None

        if raw_value is not None and answer.evidence is None:
            issues.append(
                ParseIssue(
                    code=ParseIssueCode.MISSING_EVIDENCE,
                    feature_key=feature.key,
                    value_raw=_stringify(raw_value),
                )
            )

        if not _value_matches_type(raw_value, feature.value_type):
            issues.append(
                ParseIssue(
                    code=ParseIssueCode.VALUE_TYPE_MISMATCH,
                    feature_key=feature.key,
                    value_raw=_stringify(raw_value),
                )
            )
        elif (
            feature.value_type is ValueType.ENUM
            and isinstance(raw_value, str)
            and enum_codelists is not None
            and feature.key in enum_codelists
            and raw_value not in enum_codelists[feature.key]
        ):
            issues.append(
                ParseIssue(
                    code=ParseIssueCode.ENUM_CODE_NOT_IN_CODELIST,
                    feature_key=feature.key,
                    value_raw=raw_value,
                )
            )

        value_raw = _stringify(raw_value)
        values.append(
            ParsedValue(
                feature_key=feature.key,
                value_raw=value_raw,
                value_normalised=value_raw.strip() if value_raw is not None else None,
                present_flag=answer.present,
                evidence_span=answer.evidence,
            )
        )

    for key, raw_answer in features_raw.items():
        if key not in configured_keys:
            issues.append(
                ParseIssue(
                    code=ParseIssueCode.UNKNOWN_FEATURE,
                    feature_key=key,
                    value_raw=str(raw_answer),
                )
            )

    entities: list[EntityAnswer] = []
    entities_raw = data.get(ENTITIES_KEY, [])
    if isinstance(entities_raw, list):
        for entity_raw in entities_raw:
            try:
                entities.append(EntityAnswer.model_validate(entity_raw))
            except ValidationError:
                # `entities` is captured and never scored (mvp-spec.md
                # §10.3), and `ParseIssueCode` has no entity-shaped member —
                # inventing one for a value nothing downstream reads would be
                # exactly the report vocabulary CLAUDE.md's Do-NOT #6 note
                # says this phase does not need. One malformed entity does
                # not cost the record its feature answers.
                continue
    # A non-list `entities` is treated the same way: the feature answers
    # above are the extraction; a malformed capture-only list is not grounds
    # to fail the whole response.

    return ParsedExtraction(values=tuple(values), entities=tuple(entities), issues=tuple(issues))
