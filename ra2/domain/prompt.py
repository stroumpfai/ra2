# FROZEN (types and signatures) — see CONTRACTS.md
"""The prompt template, as a pure value (sw-design.md §15.1, mvp-spec.md §10.2).

A template is **everything the model is told except the feature descriptions** —
the role framing, the rules about not guessing, the output format, and where
the narrative is placed. It is versioned independently of feature sets because
changing a single word changes every answer while no feature has changed
(`design/prompt-evaluation/README.md` §1).

Three things live here and nowhere else:

1. **The slot catalogue is closed** (`SLOTS`). `{{feature_block}}` and
   `{{narrative}}` are required; `{{language}}` is optional and resolves to the
   *evaluation's* `prompt_language` (§15 F10 — the language belongs to the
   question being asked, not to the wording asking it).
2. **Resolution is single-pass.** A narrative containing `{{` is text, not a
   slot, and is never re-expanded. `resolve_template` substitutes once.
3. **The fingerprint is sha256 over the exact source**, through the same
   canonicalisation `domain/fingerprint.py` uses for features, so the two
   cannot drift. Whitespace is part of a prompt: a template differing by one
   space is a different template and its fingerprint says so.

Pure — no SQLAlchemy, no network, no filesystem — like `census.py` and
`codelist_coverage.py`, even though its callers are the ones holding sessions
and sockets (sw-design.md §15.7).

**M17 freezes the types and the signatures. H1 writes the bodies.**
"""

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ra2.domain.codes import CodeValue
from ra2.domain.feature import Grain, Kind, MatchingRule, ValueType

__all__ = [
    "REQUIRED_SLOTS",
    "SLOTS",
    "FeatureBlockEntry",
    "PromptTemplateDraft",
    "PromptValidationCode",
    "PromptValidationError",
    "ResolvedPrompt",
    "Slot",
    "SlotName",
    "compute_template_fingerprint",
    "estimate_tokens",
    "render_feature_block",
    "resolve_template",
    "validate_template",
]


class SlotName(StrEnum):
    """The closed slot catalogue (sw-design.md §15.1). Never extended at
    runtime — an unknown `{{slot}}` is a validation error, not a pass-through."""

    FEATURE_BLOCK = "feature_block"
    NARRATIVE = "narrative"
    LANGUAGE = "language"


@dataclass(frozen=True, slots=True)
class Slot:
    """One catalogue entry — the "Slots available" strip's row."""

    name: SlotName
    required: bool
    #: The design's reference-strip description, e.g. "record text".
    description: str

    @property
    def token(self) -> str:
        """The literal text a template writes, e.g. `{{narrative}}`."""
        return f"{{{{{self.name.value}}}}}"


#: The whole catalogue, in the design's own order.
SLOTS: Final[tuple[Slot, ...]] = (
    Slot(
        name=SlotName.FEATURE_BLOCK,
        required=True,
        description="every labelled feature and exploratory attribute",
    ),
    Slot(name=SlotName.NARRATIVE, required=True, description="record text"),
    Slot(
        name=SlotName.LANGUAGE,
        required=False,
        description="the evaluation's prompt language",
    ),
)

#: The two a template cannot omit (`design/prompt-evaluation/README.md` §1).
REQUIRED_SLOTS: Final[tuple[SlotName, ...]] = tuple(s.name for s in SLOTS if s.required)


class PromptValidationCode(StrEnum):
    """Why a template was refused. A **stable identifier**, asserted on
    instead of message text — the same rule `FindingCode` follows (CLAUDE.md,
    "Findings, not prose"). Wording lives in one rendering table in `ui/`."""

    UNKNOWN_SLOT = "unknown_slot"
    MISSING_REQUIRED_SLOT = "missing_required_slot"
    #: `{{narrative}` — a half-brace is an error, never silently text.
    MALFORMED_SLOT = "malformed_slot"
    EMPTY_SOURCE = "empty_source"


@dataclass(frozen=True, slots=True)
class PromptValidationError:
    """One reason a save was blocked — a **payload**, not an exception.

    The same split as `domain.codes.CodeImportError` versus
    `services.errors.CodelistImportError`: the domain names the problem, the
    service raises the family the routers map to a status (P3-D1).

    `slot` carries the offending slot name where there is one — the raw text
    for an unknown or malformed slot, the catalogue name for a missing one.
    """

    code: PromptValidationCode
    slot: str | None = None
    #: Character offset into `source` where the problem starts, where the
    #: problem has a position at all. The editor highlights from here.
    offset: int | None = None


@dataclass(frozen=True, slots=True)
class PromptTemplateDraft:
    """An unsaved template — what "Save as vN" validates and then writes.

    Deliberately carries no id and no version: the version is assigned by the
    store at `INSERT` time (`version + 1`, sw-design.md §15.1), never chosen by
    a caller, so two concurrent saves cannot pick the same integer.
    """

    source: str


@dataclass(frozen=True, slots=True)
class FeatureBlockEntry:
    """One feature, reduced to exactly what the prompt is allowed to see.

    The prompt never sees a `FeatureId`, an ordinal or a fingerprint — only
    the key, the type, the description the expert wrote and, for an `enum`,
    the **full code -> label list** from the snapshot (mvp-spec.md §10.2).
    Pre-resolved by the caller so `render_feature_block` stays pure and needs
    no session.
    """

    key: str
    kind: Kind
    grain: Grain
    value_type: ValueType
    #: Sent to the model verbatim (mvp-spec.md §8).
    description: str
    matching_rule: MatchingRule
    #: `None` unless `value_type` is `ENUM`; the evaluation's snapshot, in the
    #: order it is to be rendered.
    enum_codelist: tuple[CodeValue, ...] | None = None


@dataclass(frozen=True, slots=True)
class ResolvedPrompt:
    """A template with every slot expanded — what would be sent, verbatim.

    Produced with **no model call** by both preview entry points (the Prompts
    toolbar's "Preview with record 1" and Evaluation's "Preview prompt";
    plan-phase-3.md C4) and by the run worker per record.

    `token_estimate` is an **estimate and says so** (§15 F/C6): an exact count
    needs the model's tokeniser and every tokeniser package downloads its
    vocabulary, which is egress (N1). The real `prompt_tokens` /
    `completion_tokens` come back from the endpoint per call and are stored on
    the `extraction` row, which is where a number has to be right.
    """

    text: str
    token_estimate: int
    #: Which slots this template actually used, in catalogue order. The
    #: optional `{{language}}` is absent from most templates.
    slots_used: tuple[SlotName, ...]


#: A well-formed slot: `{{`, one or more word characters, `}}`, with nothing
#: in between. Matched first so its spans can be excluded when hunting for
#: malformed half-braces below.
_WELLFORMED_SLOT: Final = re.compile(r"\{\{(\w+)\}\}")

#: Any `{{` opening, well-formed or not — used to find the ones
#: `_WELLFORMED_SLOT` did not already account for.
_OPEN_BRACE: Final = re.compile(r"\{\{")

#: The malformed opening's would-be slot name, e.g. `narrative` out of
#: `{{narrative}` or `{{narrative` — best-effort, for the error's `slot` field.
_MALFORMED_NAME: Final = re.compile(r"\{\{(\w*)")


def validate_template(source: str) -> tuple[PromptValidationError, ...]:
    """Every reason this template cannot be saved, or an empty tuple.

    Blocks the save (`design/prompt-evaluation/README.md`, "Validate on save"):

    - an unknown `{{slot}}` -> `UNKNOWN_SLOT`;
    - a missing `{{feature_block}}` or `{{narrative}}` ->
      `MISSING_REQUIRED_SLOT`, one error per missing slot;
    - a malformed half-brace such as `{{narrative}` -> `MALFORMED_SLOT`,
      never silently treated as text;
    - a blank source -> `EMPTY_SOURCE`.

    A **duplicated slot is legal** — a template may place `{{feature_block}}`
    twice. Returns *every* problem found, not just the first, so the analyst
    sees the whole thing at once (`validate_import`'s rule).

    Pure: no I/O, and it never raises on arbitrary input.

    A required slot that appears only in **malformed** form (e.g. the whole
    source is just `{{narrative}`) is reported once, as `MALFORMED_SLOT` —
    not *also* as `MISSING_REQUIRED_SLOT` for the same name. The two codes
    point at two different fixes (fix the typo / add the slot); reporting
    both for one broken token would send the analyst chasing a slot that is
    actually there, just spelled wrong.
    """
    if not source or not source.strip():
        return (PromptValidationError(code=PromptValidationCode.EMPTY_SOURCE),)

    errors: list[PromptValidationError] = []
    wellformed_spans: list[tuple[int, int]] = []
    present_names: set[str] = set()

    for match in _WELLFORMED_SLOT.finditer(source):
        wellformed_spans.append(match.span())
        name = match.group(1)
        present_names.add(name)
        if name not in set(SlotName):
            errors.append(
                PromptValidationError(
                    code=PromptValidationCode.UNKNOWN_SLOT, slot=name, offset=match.start()
                )
            )

    malformed_names: set[str] = set()
    for open_match in _OPEN_BRACE.finditer(source):
        start = open_match.start()
        if any(span_start <= start < span_end for span_start, span_end in wellformed_spans):
            continue  # already accounted for as a well-formed token
        name_match = _MALFORMED_NAME.match(source, start)
        name = name_match.group(1) if name_match else ""
        malformed_names.add(name)
        errors.append(
            PromptValidationError(
                code=PromptValidationCode.MALFORMED_SLOT, slot=name or None, offset=start
            )
        )

    for required in REQUIRED_SLOTS:
        if required.value in present_names:
            continue
        if required.value in malformed_names:
            continue  # already reported as MALFORMED_SLOT above
        errors.append(
            PromptValidationError(
                code=PromptValidationCode.MISSING_REQUIRED_SLOT, slot=required.value
            )
        )

    return tuple(errors)


def render_feature_block(
    features: Sequence[FeatureBlockEntry],
    *,
    language: str,
) -> str:
    """The `{{feature_block}}` expansion (mvp-spec.md §10.2).

    One `name — type` line per labelled feature, followed by the **full
    code -> label list** for every `enum`, plus each exploratory attribute's
    description **verbatim**. `language` picks which label of a `CodeValue` is
    rendered; a code with no label in that language must **fall back visibly**,
    never render as an empty string (the phase-2 `partial` coverage case seen
    from the prompt's side).

    Pure and deterministic: the same features in the same order render the
    same bytes, because those bytes travel in the template's resolved text and
    two runs must ask the same question.

    Format, one blank line between features:

    - a `Kind.LABELLED` feature: `"{key} — {value_type}"`, and when
      `value_type` is `ENUM`, one further indented line per code in
      `enum_codelist`, in snapshot order: `"  {code} — {label}"`. A code
      whose label map has no entry for `language` falls back to the visible
      marker `"[no {language} label]"` — never an empty string, and never a
      silently substituted other language (mvp-spec.md §10.2, phase-2's
      `partial` coverage case).
    - a `Kind.EXPLORATORY` attribute: `"{key}: {description}"`, the expert's
      wording verbatim, no type line — it has no structured counterpart.
    """
    blocks: list[str] = []
    for feature in features:
        if feature.kind is Kind.EXPLORATORY:
            blocks.append(f"{feature.key}: {feature.description}")
            continue

        lines = [f"{feature.key} — {feature.value_type.value}"]
        if feature.value_type is ValueType.ENUM and feature.enum_codelist:
            for code_value in feature.enum_codelist:
                label = code_value.label.get(language, f"[no {language} label]")
                lines.append(f"  {code_value.code} — {label}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def resolve_template(source: str, blocks: Mapping[SlotName, str]) -> ResolvedPrompt:
    """Expand `source` against already-rendered slot values. **Single pass.**

    `blocks` is what each slot resolves to — `render_feature_block`'s output
    for `FEATURE_BLOCK`, `record.text_raw` **verbatim** for `NARRATIVE`, the
    evaluation's `prompt_language` for `LANGUAGE`. Substitution happens once:
    a narrative containing `{{narrative}}` is record text and is never
    re-expanded (sw-design.md §15.1).

    A slot with no entry in `blocks` resolves to the empty string rather than
    raising — `validate_template` is what refuses a template, at save time,
    where the analyst can act on it.

    An unrecognised `{{token}}` (one `validate_template` would flag as
    `UNKNOWN_SLOT`) is left exactly as written — this function does not
    re-validate, it only expands what it recognises.

    Single-pass by construction: `re.sub` walks `source` once and substitutes
    into the *result* string without rescanning it, so a slot value that
    itself contains `{{narrative}}`-shaped text (record text can, verbatim)
    is never re-expanded.
    """
    slots_used: set[SlotName] = set()

    def _expand(match: re.Match[str]) -> str:
        try:
            slot = SlotName(match.group(1))
        except ValueError:
            return match.group(0)  # not one of ours — leave the literal text
        slots_used.add(slot)
        return blocks.get(slot, "")

    text = _WELLFORMED_SLOT.sub(_expand, source)
    ordered_slots_used = tuple(slot.name for slot in SLOTS if slot.name in slots_used)
    return ResolvedPrompt(
        text=text,
        token_estimate=estimate_tokens(text),
        slots_used=ordered_slots_used,
    )


def estimate_tokens(text: str) -> int:
    """An **estimate** of the prompt's token count (plan-phase-3.md C6).

    Pure arithmetic, no vocabulary, no download, no model. The preview renders
    it as `≈ N tokens`, never as an exact figure, because it is not one.

    Heuristic: roughly four characters per token, the same rule of thumb
    every "how many tokens is this" back-of-envelope uses for English-like
    text, rounded up so a non-empty string never estimates to zero tokens.
    """
    if not text:
        return 0
    return -(-len(text) // 4)  # ceiling division without importing math


def compute_template_fingerprint(source: str) -> str:
    """`sha256` over the exact template source (sw-design.md §15.1).

    Uses `domain/fingerprint.py`'s canonicalisation so the two fingerprint
    functions in this codebase cannot drift apart. Stable across calls, and
    sensitive to **every** byte: a template differing by one space is a
    different template, and every run stores this beside the model digest.

    `compute_fingerprint` (features, mvp-spec.md §8.5) canonicalises *eight
    fields* into one JSON document before this same `hashlib.sha256(...
    .encode("utf-8")).hexdigest()` call. A template is already exactly one
    field — its source text — so there is nothing to canonicalise into: the
    "canonicalisation" that must not drift between the two functions is this
    hashing step itself, reused verbatim rather than re-implemented.
    """
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
