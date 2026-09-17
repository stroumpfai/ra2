# STUB — bodies owned by Z1 (feat/p5-mismatches-view). Not frozen.
"""Mismatches — the eighth nav entry and the last capability (F11).

`mvp-spec.md` §12: *"Presented as a flat, sortable, exportable list."* The
first word is the instruction, and `plan-phase-5.md` §3.2 is this view's
design — there is no design handoff for this screen, and that section is what
replaces one (C1, §15 F1).

**A module, not a package**, where Results is a package (`SD22`, §17.9). The
reasoning there was that three tabs built by three agents in one wave need
three files; here one screen is built by one agent in a wave of one, and a
package would be ceremony.

**Built from what already exists.** The reference is Census: a filter toolbar
over one wide sortable table with an export. `data_table` with fixed-width
`ColumnSpec`s, `pagination_row`, `field_select` per filter, `segmented_control`
for the inline three-way tag, `chip` for the anonymisation marking, `card` +
`card_header` for the tally strip, `chrome.empty_card` for the empty states.
**If this view finds itself needing a new component, a new colour or a second
table scale, that is the signal to stop and raise it** (R2) — not to invent
one where there is no designer to answer to.

**The evaluation resolution is not re-derived here.** Read
`ui/views/results/__init__.py` and reuse its shape: `/mismatches?evaluation=<id>`
with `&run=` and `&feature=`, and the standard empty card listing launched
evaluations when the parameter is absent.

Three empty states, and the third is the one that matters: no evaluation ·
nothing scored yet · **no mismatches at all, which is a good result and must
not read like an error**.

The usual rules. No business logic (Do-NOT #7): every count, every narrowed
tag and every "is this row reviewed" arrives already decided from
`MismatchService`; what lives here is the **words** for `MismatchTag` — one
rendering table, exactly as `FindingCode` and `ProbeCode` work, and the reason
§12's own "record error" and the enum's `structured_data_error` can both be
right (C4). No module-level mutable state (Do-NOT #8): the filters, the sort
and the page live in `app.storage.client`.

**M35 freezes the signature. Z1 writes the body**, plus plan-phase-5.md §6.1's
two declared exceptions — the `mismatches` `built` flag in `shell.py`, and the
one deep link in `ui/views/results/extraction_tab.py`.
"""

from typing import Final

from nicegui import ui

from ra2.domain.mismatch import MismatchTag
from ra2.services.container import Services
from ra2.ui.shell import item_for_key

__all__ = ["OTHER_LABEL", "TAG_LABELS", "register"]

_ITEM: Final = item_for_key("mismatches")

#: `MismatchTag` -> the words on the screen. **The one rendering table**, the
#: same arrangement `FindingCode` and `ProbeCode` have: the enum values are the
#: stable identifiers that tests assert on, and the wording lives here.
#:
#: `structured_data_error` reads as **"record error"** because that is what
#: mvp-spec.md §12's own example calls it — *"of 40 reviewed, 32 hallucination,
#: 8 record error"* — and the spec and the screen have to agree without the
#: identifier moving (C4).
TAG_LABELS: Final[dict[MismatchTag, str]] = {
    MismatchTag.HALLUCINATION: "Hallucination",
    MismatchTag.STRUCTURED_DATA_ERROR: "Record error",
    MismatchTag.UNCLEAR: "Unclear",
}

#: What a stored tag `MismatchTag` does not name renders as. Nothing in the MVP
#: writes one (the wire is closed, §17.5); such a row shows its stored value
#: verbatim and is counted under this heading in the tally.
OTHER_LABEL: Final = "Other"

EMPTY_TITLE = "No evaluation selected."
EMPTY_BODY = (
    "Mismatches are reviewed one evaluation at a time. Pick a launched "
    "evaluation below, or follow an evidence link from Results."
)
NOT_SCORED_TITLE = "Not scored yet."
NOT_SCORED_BODY = (
    "Mismatches are written by the scoring pass. Scoring starts automatically when a run completes."
)
#: The third empty state, and the reason it has its own wording: **this is a
#: good result**. A run with nothing wrong in it must not render like a
#: failure, an error or a missing page.
NO_MISMATCHES_TITLE = "No mismatches in this run."
NO_MISMATCHES_BODY = "Every labelled feature this model answered, it answered correctly."


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    async def _page(evaluation: str = "", run: str = "", feature: str = "") -> None:
        raise NotImplementedError
