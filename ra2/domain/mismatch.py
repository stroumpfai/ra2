# FROZEN (types and signatures) — see CONTRACTS.md
"""The review vocabulary and the tally (mvp-spec.md §12, sw-design.md §17).

Phase 4 wrote every `wrong` outcome to `mismatch` and never read one back.
This module is the first half of reading them: the three words an analyst may
write, the states the list may be filtered by, the keys it may be sorted by,
and the one piece of arithmetic the whole phase contains.

**A closed enum over an open column** (`SD24`, §17.5). `mismatch.analyst_tag`
stays `String(32)` because `models.py` promised that "a fourth tag must be a
value, not a migration"; `MismatchTag` is closed because the list, the tally,
the CSV and the wire have to agree on three identifiers and because a typo
should be a lint error rather than a row nobody can find. `OTHER_TAG` is what
stops that asymmetry becoming a crash: a stored value this enum does not name
is counted, never dropped.

**The tag never feeds back into a metric** (mvp-spec.md §12). Nothing here can
reach a `ScoreRow`, an `Outcome` or a `MetricCell`, and `domain` cannot reach
a session to find one — the absence of the edge is the whole of §17.3.

Pure — no SQLAlchemy, no session, no filesystem.

**M35 freezes the types and the signatures. W1 writes the bodies.**
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "MISMATCH_SORT_KEYS",
    "OTHER_TAG",
    "MismatchTag",
    "ReviewTally",
    "TagFilter",
    "TagState",
    "tally",
]


class MismatchTag(StrEnum):
    """The three words an analyst may write (mvp-spec.md §12).

    The **values** are the stable identifiers — asserted on in tests, carried
    on the wire, stored in the column, written to the CSV. The *words* on the
    screen are `ui/`'s, in one rendering table, exactly as `FindingCode` and
    `ProbeCode` work: §12's own example says "record error" where this enum
    says `structured_data_error`, and the screen has to agree with the spec
    without the identifier changing.
    """

    #: The model asserted something the narrative does not support.
    HALLUCINATION = "hallucination"
    #: The narrative is right and the structured record is wrong. Note that
    #: **the record stays authoritative anyway** (§12): this tag records a
    #: judgement, and no adjudication step exists anywhere in the pipeline.
    STRUCTURED_DATA_ERROR = "structured_data_error"
    #: Neither of the above — the model read the text correctly and the text
    #: genuinely disagrees with the record. §12 includes it because "a real
    #: list will contain cases that are neither"; it costs nothing and answers
    #: the question from data.
    UNCLEAR = "unclear"


#: The bucket a stored `analyst_tag` falls into when `MismatchTag` does not
#: name it (§17.5, `SD24`).
#:
#: **Deliberately not a `MismatchTag` member**, so no code path can write it.
#: It is a bucket, not a vocabulary word: nothing in the MVP can create such a
#: row — the wire is closed and answers 422 — and it exists for a value a later
#: phase, a migration or a hand-edited database introduces. Such a row renders
#: as itself, counts here, and travels verbatim in the export. A tally that
#: dropped it would report "of 40 reviewed" over 38.
OTHER_TAG: Final = "other"


class TagState(StrEnum):
    """The three tag-*states* the list may be filtered by, beside the three
    tags themselves."""

    ANY = "any"
    #: No tag at all — the analyst's work queue.
    UNTAGGED = "untagged"
    #: Any tag, including one `MismatchTag` does not name.
    TAGGED = "tagged"


#: What the Tag filter asks for: one of the three states, or one named tag.
#:
#: One field rather than two, because the toolbar is one control with six
#: options. The two enums' values are disjoint, so the union discriminates
#: itself and a repository decides by `isinstance`.
#:
#: The filter vocabulary is closed even though the column is not (§17.5): a
#: fourth stored tag is visible in the list, counted under `other` and carried
#: in the CSV — it is simply not offered as a filter option until somebody adds
#: it. That is the honest boundary of the asymmetry, not an oversight.
type TagFilter = TagState | MismatchTag


#: The four keys this list may be sorted by, and there is no fifth (§17.8).
#:
#: In particular **nothing sorts by "how wrong"**: there is no such number, and
#: inventing one is §16.9's clustering / cross-model-agreement / sampling
#: deferral arriving as a helpful-looking feature. A closed tuple is what makes
#: that a test rather than a review comment.
MISMATCH_SORT_KEYS: Final[tuple[str, ...]] = ("feature", "record", "tag", "reviewed")


@dataclass(frozen=True, slots=True)
class ReviewTally:
    """One feature's review counts — mvp-spec.md §12's "of 40 reviewed, 32
    hallucination, 8 record error".

    **Computed on read, never stored** (§17.4, F5's third application). A
    stored tally is a second source of truth that both a re-score and a tag can
    desynchronise, and the query behind this is one `GROUP BY` over an indexed
    column.

    Two identities hold, and both are asserted rather than assumed:

        sum(counts.values()) + other == reviewed
        reviewed + untagged        == total
    """

    #: Every mismatch in scope, tagged or not.
    total: int
    #: Rows carrying any tag — §12's "of **40** reviewed".
    reviewed: int
    #: `total - reviewed`. Stored rather than derived at every call site so a
    #: renderer cannot get the subtraction backwards.
    untagged: int
    #: One entry for **every** `MismatchTag`, always all three, so no renderer
    #: can `KeyError` on a tag nobody has used yet.
    counts: Mapping[MismatchTag, int]
    #: Rows whose stored tag is non-empty and is not a `MismatchTag` value
    #: (`OTHER_TAG`, §17.5). Counted, never dropped.
    other: int


def tally(counts: Mapping[str | None, int]) -> ReviewTally:
    """Fold stored `analyst_tag` values and their row counts into one tally.

    Takes **the shape `GROUP BY` produces** — stored value to number of rows —
    rather than a list of rows, so the grouped query stays grouped all the way
    into the domain (§17.4). `tally_for` is one query per run, not one per
    feature, and a signature taking rows would have quietly undone that.

    `None` and `""` are untagged. Anything else is a tag: one this enum names,
    or `other`.

    **An empty input yields a zero tally rather than raising** — unlike
    `domain/stats.py`'s `macro`, and for the opposite reason. There is nothing
    dishonest about "0 reviewed"; there is a great deal dishonest about a macro
    F1 over no features.
    """
    raise NotImplementedError
