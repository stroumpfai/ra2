"""Layer 3 — the discard dialog's two states (plan-reset-and-discard.md §8).

The dialog is the only place a user is told what a discard costs, so what is
asserted here is what it *says* and which button it leaves pressable:

- **nothing to export** — no Export button, Discard live immediately;
- **something to export** — the counts, the export prompt, both buttons;
- **tagged work** — the count in the lead sentence, and the button relabelled
  so pressing through the warning is a deliberate act (G2, `R-D3`);
- **blocked** — G1 or a cited delivery: the reason on screen and Discard
  disabled, never a dialog that fails when you press it.

`blocked` and `has_exportable` are read off the view, never recomputed here —
which these tests also pin, by handing the component views whose counts and
flags disagree with what a naive re-derivation would produce.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

import pytest
from nicegui import ui
from nicegui.testing.user import User

from ra2.services.readmodels import DiscardPreviewView
from ra2.ui.components.discard_dialog import (
    DISCARD_IRREVERSIBLE,
    DISCARD_KEEPS,
    EXPORT_LEAVES_RA2,
    EXPORT_PROMPT,
    NEVER_LAUNCHED,
    TYPE_CONFIRM_LABEL,
    discard_dialog,
    kept_refusal,
    loss_line,
    type_prompt,
)

pytestmark = pytest.mark.ui


async def _until(predicate: Callable[[], bool]) -> None:
    """The click handler is async, so its effect lands on the next tick —
    `test_evaluation_view._until`'s helper, for its reason."""
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


def _preview(**overrides: object) -> DiscardPreviewView:
    base: dict[str, object] = {
        "kind": "run",
        "target_id": "run-1",
        "label": "run-1 · qwen3:14b",
        "runs": 1,
        "extractions": 412,
        "scores": 96,
        "mismatches": 14,
        "tagged_mismatches": 0,
        "files": 0,
        "active": False,
    }
    base.update(overrides)
    return DiscardPreviewView(**base)  # type: ignore[arg-type]


def _page(path: str, preview: DiscardPreviewView, *, with_export: bool = True) -> list[bool]:
    """Register a route that opens the dialog, and hand back the `force` flags
    the confirm callback received.

    The collector is `async` because the component's callbacks are awaitable —
    a service call is what they really are, and a handler that only *returns* a
    coroutine changes nothing (NiceGUI awaits what a handler returns).
    """
    forced: list[bool] = []

    async def _record(force: bool) -> None:
        forced.append(force)

    async def _export() -> None:
        return None

    on_export: Callable[[], Awaitable[None]] | None = _export if with_export else None

    @ui.page(path)
    def _view() -> None:
        dialog = cast(
            "ui.dialog", discard_dialog(preview=preview, on_discard=_record, on_export=on_export)
        )
        # `.value = True` is what `Dialog.open()` does, spelled out — the N4
        # gate scans for `.open(` (`evaluation_view._open_settings`'s note).
        dialog.value = True

    return forced


# --- the two states -------------------------------------------------------


async def test_nothing_to_export_offers_no_export_button(user: User) -> None:
    _page("/d/empty", _preview(extractions=0, scores=0, mismatches=0))
    await user.open("/d/empty")

    await user.should_see(marker="discard-confirm")
    await user.should_not_see(marker="discard-export")
    await user.should_not_see(marker="discard-export-prompt")
    await user.should_not_see(marker="discard-export-warning")


async def test_the_export_offer_says_the_file_leaves_ra2(user: User) -> None:
    """Offering the export and saying what it costs are one affordance, not
    two (risk-assesment.md B3 §8.6, P4).

    The mismatch file carries verbatim narrative into Downloads, where nothing
    the app deletes can reach it. The sentence is asserted because it is
    load-bearing copy — the same reason `DISCARD_KEEPS` and
    `DISCARD_IRREVERSIBLE` are.
    """
    _page("/d/leaves", _preview())
    await user.open("/d/leaves")

    await user.should_see(EXPORT_LEAVES_RA2)
    await user.should_see(marker="discard-export-warning")


async def test_something_to_export_shows_the_counts_and_both_buttons(user: User) -> None:
    _page("/d/full", _preview())
    await user.open("/d/full")

    await user.should_see("412 extractions · 96 scores · 14 mismatches")
    await user.should_see(EXPORT_PROMPT)
    await user.should_see(marker="discard-export")
    await user.should_see(marker="discard-confirm")


async def test_it_says_what_is_kept_and_that_it_cannot_be_undone(user: User) -> None:
    """The two sentences that answer the questions this dialog actually
    provokes: "does this delete my corpus?" and "can I get it back?"."""
    _page("/d/copy", _preview())
    await user.open("/d/copy")

    await user.should_see(DISCARD_KEEPS)
    await user.should_see(DISCARD_IRREVERSIBLE)


# --- G2: warn and allow ---------------------------------------------------


async def test_tagged_work_is_named_and_the_button_is_relabelled(user: User) -> None:
    _page("/d/tagged", _preview(tagged_mismatches=3))
    await user.open("/d/tagged")

    await user.should_see("3 tagged mismatches would be destroyed")
    await user.should_see("Discard anyway")


async def test_confirming_through_the_warning_passes_force(user: User) -> None:
    forced = _page("/d/force", _preview(tagged_mismatches=3))
    await user.open("/d/force")

    user.find(marker="discard-type-confirm").trigger("input", args="3")
    user.find(marker="discard-confirm").click()

    await _until(lambda: forced == [True])


# --- SD60: typing the tagged count ----------------------------------------


def _disabled(user: User) -> bool:
    (button,) = user.find(marker="discard-confirm").elements
    return "disabled" in button._props


async def test_tagged_work_asks_for_the_count_and_holds_discard_until_it_is_typed(
    user: User,
) -> None:
    _page("/d/type", _preview(tagged_mismatches=3))
    await user.open("/d/type")

    await user.should_see(type_prompt(_preview(tagged_mismatches=3)))
    (field,) = user.find(marker="discard-type-confirm").elements
    assert field._props["aria-label"] == TYPE_CONFIRM_LABEL
    assert _disabled(user)

    user.find(marker="discard-type-confirm").trigger("input", args="3")
    assert not _disabled(user)
    # Taking it back takes the button back: the state follows the field.
    user.find(marker="discard-type-confirm").trigger("input", args="")
    assert _disabled(user)


@pytest.mark.parametrize("typed", ["", "2", "30", "three", "Discard"])
async def test_anything_but_the_count_leaves_discard_dead(user: User, typed: str) -> None:
    """A press that lands anyway is ignored too: `disabled` is a UI state."""
    forced = _page(f"/d/wrong-{typed or 'empty'}", _preview(tagged_mismatches=3))
    await user.open(f"/d/wrong-{typed or 'empty'}")

    user.find(marker="discard-type-confirm").trigger("input", args=typed)
    assert _disabled(user)
    user.find(marker="discard-confirm").click()
    await asyncio.sleep(0.05)
    assert forced == []


async def test_the_count_is_accepted_with_surrounding_spaces(user: User) -> None:
    forced = _page("/d/spaces", _preview(tagged_mismatches=1))
    await user.open("/d/spaces")

    user.find(marker="discard-type-confirm").trigger("input", args=" 1 ")
    user.find(marker="discard-confirm").click()

    await _until(lambda: forced == [True])


async def test_without_tagged_work_nothing_is_typed(user: User) -> None:
    _page("/d/untyped", _preview())
    await user.open("/d/untyped")

    await user.should_not_see(marker="discard-type-confirm")
    assert not _disabled(user)


async def test_a_blocked_dialog_with_tagged_work_asks_for_nothing(user: User) -> None:
    """G1 first: typing cannot unblock a run that is still being written."""
    _page(
        "/d/blocked-tagged",
        _preview(tagged_mismatches=2, active=True, active_detail="run-1 is running"),
    )
    await user.open("/d/blocked-tagged")

    await user.should_see("run-1 is running")
    await user.should_not_see(marker="discard-type-confirm")
    assert _disabled(user)


async def test_confirming_without_tagged_work_does_not_force(user: User) -> None:
    forced = _page("/d/noforce", _preview())
    await user.open("/d/noforce")

    user.find(marker="discard-confirm").click()

    await _until(lambda: forced == [False])


# --- G1 and the cited delivery: blocked, and visibly so -------------------


async def test_an_active_run_says_why_and_disables_discard(user: User) -> None:
    forced = _page("/d/active", _preview(active=True, active_detail="run-1 is running"))
    await user.open("/d/active")

    await user.should_see("run-1 is running")
    (button,) = user.find(marker="discard-confirm").elements
    assert "disabled" in button._props

    user.find(marker="discard-confirm").click()
    await asyncio.sleep(0.05)
    assert forced == [], "a blocked dialog must not call back even if the click lands"


async def test_a_cited_delivery_says_to_discard_the_corpus_first(user: User) -> None:
    _page(
        "/d/cited",
        _preview(
            kind="delivery", runs=0, extractions=0, scores=0, mismatches=0, files=4, cited_by=1
        ),
        with_export=False,
    )
    await user.open("/d/cited")

    await user.should_see("Discard the corpus first")
    (button,) = user.find(marker="discard-confirm").elements
    assert "disabled" in button._props


# --- the loss line is a rendering, and stays one --------------------------


def test_the_loss_line_drops_what_is_zero() -> None:
    """A run that was never scored must not read as one that scored nothing."""
    assert loss_line(_preview(scores=0, mismatches=0)) == "1 run · 412 extractions"
    assert (
        loss_line(_preview(runs=0, extractions=0, scores=0, mismatches=0)) == "nothing recorded yet"
    )
    assert loss_line(_preview(runs=1, extractions=1, scores=1, mismatches=1)) == (
        "1 run · 1 extraction · 1 score · 1 mismatch"
    )


# --- which evaluation (SD59) ------------------------------------------------


async def test_an_evaluation_that_never_launched_says_so_and_shows_its_id(user: User) -> None:
    """Two same-named evaluations differ in when, what and which models; a
    draft's "when" is that it never was, said rather than left blank."""
    _page(
        "/d/draft",
        _preview(
            kind="evaluation",
            target_id="eval-7f3a",
            label="Weather & conditions · 0 run(s)",
            runs=0,
            extractions=0,
            scores=0,
            mismatches=0,
            inputs="corpus · v1 · Weather & conditions · v2",
        ),
    )
    await user.open("/d/draft")

    await user.should_see(marker="discard-identity")
    await user.should_see(NEVER_LAUNCHED)
    await user.should_see("corpus · v1 · Weather & conditions · v2")
    await user.should_see("eval-7f3a")
    # No runs, so no models line rather than an empty one.
    await user.should_not_see(marker="discard-models")


async def test_a_run_carries_no_evaluation_identity(user: User) -> None:
    _page("/d/run-identity", _preview())
    await user.open("/d/run-identity")

    await user.should_see(marker="discard-target")
    await user.should_not_see(marker="discard-identity")


# --- G3: kept (SD61) --------------------------------------------------------


@pytest.mark.parametrize("kind", ["evaluation", "run"])
async def test_a_kept_target_says_where_it_is_released_and_stays_dead(
    user: User, kind: str
) -> None:
    """Refused whatever is pressed, and the sentence names the evaluation for
    a run too: the mark, and the control that releases it, are the
    evaluation's. A press that lands anyway does nothing."""
    preview = _preview(kind=kind, kept=True)
    forced = _page(f"/d/kept-{kind}", preview)
    await user.open(f"/d/kept-{kind}")

    await user.should_see(kept_refusal(preview))
    assert _disabled(user)
    user.find(marker="discard-confirm").click()
    await asyncio.sleep(0.05)
    assert forced == []


async def test_a_kept_target_with_tagged_work_asks_for_no_count(user: User) -> None:
    """G3 before G2: typing the count would enable nothing."""
    _page("/d/kept-tagged", _preview(kind="evaluation", kept=True, tagged_mismatches=2))
    await user.open("/d/kept-tagged")

    await user.should_see(marker="discard-blocked")
    await user.should_not_see(marker="discard-tagged")
    await user.should_not_see(marker="discard-type-confirm")


def test_the_refusal_names_the_evaluation_for_a_run() -> None:
    assert kept_refusal(_preview(kind="run", kept=True)).startswith("Its evaluation")
    assert kept_refusal(_preview(kind="evaluation", kept=True)).startswith("This evaluation")
