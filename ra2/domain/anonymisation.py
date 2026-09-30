# NEW — fix-b5-d6-honest-labels. Not frozen.
"""What the per-record anonymisation marking may claim (risk B5, `SD50`).

`mvp-spec.md` §13 requires the marking wherever record text is shown. The one
fact the data carries is **where** a record's narrative came from: the shared
text file, or the `UnfHergangTextAnonym` fallback column when the text file
had no row for it (`record.text_anonymised_flag`). Whether a *delivered*
narrative is anonymised is not in the data at all, and what the fallback
column's name promises is still an open question with the supplier
(`mvp-spec.md` §18).

So the marking says only what is known. Until the supplier answers, a
delivered narrative is **unknown**, never "not anonymised" by silence. Their
answer is recorded once, in `RA2_DELIVERED_TEXT_ANONYMISED`, and every
delivered narrative's marking follows it. A marking that overstates certainty
about personal data is worse than one that admits it.
"""

from enum import StrEnum

__all__ = ["AnonymisationMarking", "DeliveredTextAnonymised", "anonymisation_marking"]


class DeliveredTextAnonymised(StrEnum):
    """The supplier's answer about the delivered text file, as configured."""

    UNKNOWN = "unknown"
    YES = "yes"
    NO = "no"


class AnonymisationMarking(StrEnum):
    """The four things the marking can say. Values are stable identifiers,
    written verbatim into CSV exports; wording lives in `ui/`."""

    #: The narrative came from the `UnfHergangTextAnonym` column. Named for its
    #: source, because what that column guarantees is not yet confirmed.
    ANONYMISED_COLUMN = "anonymised_column"
    #: A delivered narrative, and the supplier said the text file is anonymised.
    ANONYMISED = "anonymised"
    #: A delivered narrative, and the supplier said it is not.
    NOT_ANONYMISED = "not_anonymised"
    #: A delivered narrative, and nobody has said. The default.
    UNKNOWN = "unknown"


_DELIVERED: dict[DeliveredTextAnonymised, AnonymisationMarking] = {
    DeliveredTextAnonymised.UNKNOWN: AnonymisationMarking.UNKNOWN,
    DeliveredTextAnonymised.YES: AnonymisationMarking.ANONYMISED,
    DeliveredTextAnonymised.NO: AnonymisationMarking.NOT_ANONYMISED,
}


def anonymisation_marking(
    from_anonymised_column: bool, delivered: DeliveredTextAnonymised
) -> AnonymisationMarking:
    """The marking for one record, from its source and the configured answer."""
    if from_anonymised_column:
        return AnonymisationMarking.ANONYMISED_COLUMN
    return _DELIVERED[delivered]
