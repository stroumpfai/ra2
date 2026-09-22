# NEW — `plan-scoring-visibility-follow-ups.md` Part 1. Not frozen.
"""What a screen says about a scoring pass, said **once**.

Two views render this now: Results (the boards) and Mismatches (the review
list). They are looking at the same four facts about the same run — it has not
finished, its pass is in flight, its pass wrote nothing, its pass wrote some
of it — and before this module they answered them separately. Mismatches had
its own "Not scored yet." with its own body, knew only `any(is_scored)` over
the whole evaluation, and therefore told a run whose pass had **crashed** that
*"Every labelled feature this model answered, it answered correctly."* — on
the one screen in the product where a human decides which model to believe.

So the sentences live here, and so does the decision of which one applies to
a given run. `chrome.py` is the precedent one layer down ("Everything here
exists once rather than three times… the three tabs must not drift into three
slightly different headers on one screen"); this is that rule applied to two
screens instead of three tabs.

**No business logic** (Do-NOT #7). `card_for` reads properties
`ScoringStatusView` already computed — `running`, `is_finished`,
`is_scoreable`, `is_scored`, `scoring_stalled`, `scoring_incomplete` — and
chooses words for them. It decides nothing about scoring itself.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final

from nicegui import ui

from ra2.domain.ids import RunId
from ra2.services.readmodels import ScoringStatusView

__all__ = [
    "INCOMPLETE_BODY",
    "INCOMPLETE_TITLE",
    "NOTHING_SCOREABLE_BODY",
    "NOTHING_SCOREABLE_TITLE",
    "NOT_SCORED_BODY",
    "NOT_SCORED_TITLE",
    "PARTIAL_NOTE",
    "POLL_FAST_S",
    "POLL_SLOW_S",
    "RESCORE_LABEL",
    "RESCORE_STARTED",
    "SCORING_BODY",
    "SCORING_TITLE",
    "STALLED_BODY",
    "STALLED_TITLE",
    "ScoringCard",
    "card_for",
    "rescore_row",
    "run_label",
]

# --- the sentences ----------------------------------------------------------

NOT_SCORED_TITLE: Final = "Not scored yet."
#: **Rewritten** in `fix/results-visibility`, and this is what is left of it.
#: It used to read *"This run finished but has not been scored. Scoring starts
#: automatically when a run completes; use Re-score if you need to run it
#: again"* — three claims, none of which held when it was written: nothing
#: chained scoring off a finished run (`SD17`, fixed in `6bae3a3`), no
#: Re-score existed in `ui/`, and the card was also what a run that had *not*
#: finished got. The other two states have their own cards below, so this one
#: says the only true thing left.
NOT_SCORED_BODY: Final = (
    "This run has not finished yet. Scoring starts automatically the moment "
    "it does, and this page refreshes itself."
)

SCORING_TITLE: Final = "Scoring…"
SCORING_BODY: Final = "Progress is polled; this page refreshes itself."

#: A finished run, something scoreable, nothing in flight, and **no rows**.
#: The pass either crashed or never ran, and *waiting* is the one thing that
#: will not help — which is why this cannot share a card with the sentence
#: above it.
STALLED_TITLE: Final = "Scoring did not finish."
STALLED_BODY: Final = (
    "This run is done and has labelled features, but no scores were written "
    "and nothing is running. Re-score starts the pass again; the log line "
    "for this run says what stopped it."
)

#: The same, with **some** rows: `0 < scored < labelled`. One of the three
#: states `ScoringStatus`'s own docstring says must not be conflated, and it
#: was conflated — with "not scored yet", which is a sentence about waiting.
INCOMPLETE_TITLE: Final = "Partly scored."
INCOMPLETE_BODY: Final = (
    "Scoring stopped part-way: some features have scores and some have none, "
    "so any numbers here would be over a corpus nobody stated. Re-score runs "
    "the pass again and keeps your review tags."
)

NOTHING_SCOREABLE_TITLE: Final = "Nothing in this run could be scored."
NOTHING_SCOREABLE_BODY: Final = "This evaluation has no labelled features."

#: Shown above a screen that **is** rendering numbers while some other run of
#: the same evaluation has none. Without it that run's cells are simply blank,
#: which reads as a model that answered nothing rather than one nobody scored.
PARTIAL_NOTE: Final = "One or more runs in this evaluation are not fully scored."

RESCORE_LABEL: Final = "Re-score"
RESCORE_STARTED: Final = "Re-scoring {run} — this page refreshes itself."

#: The poll's two intervals. **A scoring pass is 0.14 s on the development
#: seed**, so a page waiting for one wants to be quick. **A run is hours**,
#: and a page opened during one waits for the run first and the pass second —
#: holding the fast interval there would put reads a second against the SQLite
#: file the worker is committing to, which is the mistake
#: `plan-fix-evaluation-runs.md` §1.2 catalogued on the Evaluation screen.
POLL_FAST_S: Final = 0.4
POLL_SLOW_S: Final = 3.0


# --- which one applies ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScoringCard:
    """One state's wording, plus whether a button belongs under it."""

    title: str
    body: str
    #: `True` for the two states a re-score would move: a pass that wrote
    #: nothing and one that wrote some of it. Never for a run still in flight
    #: — `submit_rescore` refuses that, and offering it would be a button that
    #: answers 409.
    offers_rescore: bool = False


def card_for(status: ScoringStatusView) -> ScoringCard | None:
    """The card this run's scoring state deserves, or `None` when it has one.

    `None` means *render the real thing*: the run is scored and the screen
    should show its numbers, its rows, or its "no mismatches" result.

    The order matters and is the order the facts exclude each other in: an
    evaluation with nothing scoreable is not "not scored yet"; a pass in
    flight is not a pass that failed; a run that has not finished is waiting
    rather than broken.
    """
    if not status.is_scoreable:
        return ScoringCard(NOTHING_SCOREABLE_TITLE, NOTHING_SCOREABLE_BODY)
    if status.running:
        return ScoringCard(SCORING_TITLE, SCORING_BODY)
    if not status.is_finished:
        return ScoringCard(NOT_SCORED_TITLE, NOT_SCORED_BODY)
    if status.scoring_stalled:
        return ScoringCard(STALLED_TITLE, STALLED_BODY, offers_rescore=True)
    if status.scoring_incomplete:
        return ScoringCard(INCOMPLETE_TITLE, INCOMPLETE_BODY, offers_rescore=True)
    return None


def run_label(ordinal: int) -> str:
    """ "run 2", or "this run" when the ordinal could not be read.

    A run is named by its ordinal everywhere a person has to say which one —
    `mismatch_service._run_label`, the discard dialog, the runs table — and
    "run 0" is not a name this product uses for anything.
    """
    return f"run {ordinal}" if ordinal else "this run"


# --- the control ------------------------------------------------------------


def rescore_row(
    runs: Sequence[tuple[RunId, int]],
    *,
    on_rescore: Callable[[RunId, int], Awaitable[None]],
    note: str | None = None,
) -> None:
    """One Re-score button per run that needs one, `(run_id, ordinal)`.

    The control `NOT_SCORED_BODY` named from phase 4 while no such control
    existed anywhere in `ui/` — the only route to one was a `POST` nothing in
    the product issued. A sentence naming a control the product does not have
    is worse than no sentence: it tells the analyst the dead end is their own
    fault for not finding the button.
    """
    if not runs:
        return
    with (
        ui.element("div")
        .props('data-testid="rescore-row"')
        .mark("rescore-row")
        .style("padding:0 18px 18px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;")
    ):
        if note is not None:
            ui.label(note).classes("mono warn").props('data-testid="rescore-note"').mark(
                "rescore-note"
            ).style("font-size:11px;")
        for run_id, ordinal in runs:
            button = (
                ui.element("button")
                .classes("btn secondary")
                .props(f'type="button" data-testid="rescore" data-run="{run_id}"')
                .mark("rescore")
            )
            button.on(
                "click",
                lambda _event, run_id=run_id, ordinal=ordinal: on_rescore(run_id, ordinal),
            )
            with button:
                ui.label(f"{RESCORE_LABEL} {run_label(ordinal)}")
