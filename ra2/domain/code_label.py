"""A mismatch value, decoded against the code table the model was shown (`SD70`).

The Mismatches view puts `code · label` beside both the record's value and the
model's. The code table is the **launch-time snapshot**
(`evaluation_feature.enum_codelist_json`), not the live Codelists mapping: a
mapping or an import can change after launch, and a label the model never saw
would put words in its mouth on the one screen where a human decides whether
it hallucinated.

Pure, as `domain/` is: plain values in, a plain value out. The service parses
the snapshot and hands its `CodeValue`s over.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ra2.domain.codes import CodeValue

__all__ = ["UNDECODED", "DecodedValue", "LabelState", "by_code", "decode"]


class LabelState(StrEnum):
    """What decoding found. A stable identifier, like `FindingCode`: the words
    for each state live in one table in `ui/`."""

    #: The code is in the snapshot with a label in the prompt language.
    LABELLED = "labelled"
    #: The code is in the snapshot, but has no label in the prompt language.
    #: Another language's label is **not** offered in its place: the model was
    #: never given it.
    NO_LABEL = "no_label"
    #: An enum feature, and the code is not in its snapshot. A fact the analyst
    #: needs (often the model inventing a code), never a blank.
    NOT_IN_TABLE = "not_in_table"
    #: Not an enum feature: there is nothing to decode, and the value is shown
    #: as it is.
    NOT_ENUM = "not_enum"
    #: No value at all. Rendered as the table's empty cell.
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class DecodedValue:
    """One value and what its code means, in the language that was asked."""

    #: The value verbatim, exactly as `mismatch` stores it.
    raw: str | None
    label: str | None
    state: LabelState
    #: The language the label was looked up in: the evaluation's prompt
    #: language. Carried so "no label" can say which language it lacks.
    language: str | None = None


#: No value, nothing decoded: the default a read model starts from.
UNDECODED: Final = DecodedValue(raw=None, label=None, state=LabelState.EMPTY)


def by_code(codes: Sequence[CodeValue]) -> Mapping[str, CodeValue]:
    """A snapshot keyed by its codes, built once per feature, so decoding a
    page is a lookup per value rather than a scan of the table."""
    return {code.code: code for code in codes}


def decode(
    value: str | None,
    codes: Mapping[str, CodeValue] | None,
    language: str,
) -> DecodedValue:
    """Decode `value` against `codes` (from `by_code`) in `language`.

    `codes` is `None` for a feature that is not an enum, which is what the
    snapshot column holds for one. **Exact codes only**: `"04"` is not `"4"`,
    the rule `compute_coverage` and the scorer already apply. Coercing a code
    to its nearest neighbour is what mvp-spec.md §7 forbids.

    **`no_label` means what the prompt means by it**: the language is absent
    from the code's labels, which is exactly when `render_feature_block`
    printed `[no de label]`. A label that is present but empty is what the
    model was shown, so it decodes as `labelled` with an empty label.
    """
    if not value:
        return DecodedValue(raw=value, label=None, state=LabelState.EMPTY, language=language)
    if codes is None:
        return DecodedValue(raw=value, label=None, state=LabelState.NOT_ENUM, language=language)
    found = codes.get(value)
    if found is None:
        return DecodedValue(raw=value, label=None, state=LabelState.NOT_IN_TABLE, language=language)
    label = found.label.get(language)
    if label is None:
        return DecodedValue(raw=value, label=None, state=LabelState.NO_LABEL, language=language)
    return DecodedValue(raw=value, label=label, state=LabelState.LABELLED, language=language)
