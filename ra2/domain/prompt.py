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
    """
    raise NotImplementedError


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
    """
    raise NotImplementedError


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
    """
    raise NotImplementedError


def estimate_tokens(text: str) -> int:
    """An **estimate** of the prompt's token count (plan-phase-3.md C6).

    Pure arithmetic, no vocabulary, no download, no model. The preview renders
    it as `≈ N tokens`, never as an exact figure, because it is not one.
    """
    raise NotImplementedError


def compute_template_fingerprint(source: str) -> str:
    """`sha256` over the exact template source (sw-design.md §15.1).

    Uses `domain/fingerprint.py`'s canonicalisation so the two fingerprint
    functions in this codebase cannot drift apart. Stable across calls, and
    sensitive to **every** byte: a template differing by one space is a
    different template, and every run stores this beside the model digest.
    """
    raise NotImplementedError
