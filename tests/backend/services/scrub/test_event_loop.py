"""A large list never holds the event loop (sw-design.md §19.7).

NiceGUI drops a page whose socket misses its heartbeat for about six
seconds. A refused import of a full surname list once ran its parse and its
check on the event loop for longer than that, the page was deleted, and the
dialog saying why the list was refused went to a client that no longer
existed. These tests run that import beside a ticker and hold the longest
stall the ticker saw to a fraction of the import's own wall time: a step
back on the loop makes the two nearly equal, on a fast machine or a slow one.
"""

import asyncio
import itertools
import time
from collections.abc import Awaitable

import pytest

from ra2.domain.scrub import ListKind, ScrubImportErrorCode, ScrubRules
from ra2.domain.scrub_mandatory import MANDATORY_RULES
from ra2.services.errors import ScrubImportRefusedError
from ra2.services.scrub_service import ScrubService, compile_scrubber

pytestmark = pytest.mark.backend

_SYLLABLES = (
    *("ba", "ce", "di", "fo", "gu", "ha", "ke", "li", "mo", "nu", "pa"),
    *("re", "si", "to", "vu", "wa", "xe", "zo", "bri", "sta", "mü", "zé"),
)
#: 100 000 invented surnames, some accented: `Bacedifo`, `Mübaceza`, ...
_NAMES = tuple(
    "".join(parts).capitalize()
    for parts in itertools.islice(itertools.product(_SYLLABLES, repeat=4), 100_000)
)

#: A stall this share of the work's wall time means the work ran on the loop.
#: Measured on the development machine: 2-7 % off the loop, 25-48 % with the
#: same steps run inline, the lower figure where the work is split over four
#: calls and the longest stall is only one of them.
_STALL_SHARE = 0.15


async def _longest_stall(work: Awaitable[object]) -> tuple[object, float, float]:
    """What `work` returned or raised, the longest gap between two ticks of
    a 5 ms ticker beside it, and the wall time `work` took."""
    done = asyncio.Event()
    longest = 0.0

    async def tick() -> None:
        nonlocal longest
        last = time.perf_counter()
        while not done.is_set():
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            longest = max(longest, now - last)
            last = now

    ticker = asyncio.create_task(tick())
    await asyncio.sleep(0)
    started = time.perf_counter()
    outcome: object
    try:
        outcome = await work
    except ScrubImportRefusedError as exc:
        outcome = exc
    elapsed = time.perf_counter() - started
    done.set()
    await ticker
    return outcome, longest, elapsed


def _list(*extra: str) -> bytes:
    return ("\n".join((*_NAMES, *extra)) + "\n").encode("utf-8")


async def test_a_refused_list_is_refused_with_the_loop_still_turning(
    scrub_service: ScrubService,
) -> None:
    # `Rega` turns the protected `Rega 1414` into a surname: refused (§19.5).
    outcome, longest, elapsed = await _longest_stall(
        scrub_service.import_list(ListKind.LASTNAME, "lastnames.txt", _list("Rega"))
    )
    assert isinstance(outcome, ScrubImportRefusedError)
    assert {e.code for e in outcome.import_errors} == {ScrubImportErrorCode.PROTECTED_ALTERED}
    assert longest < _STALL_SHARE * elapsed, f"stalled {longest:.2f} s of {elapsed:.2f} s"


async def test_an_accepted_list_and_the_screen_that_shows_it_leave_the_loop_turning(
    scrub_service: ScrubService,
) -> None:
    async def work() -> object:
        await scrub_service.import_list(ListKind.LASTNAME, "lastnames.txt", _list())
        await scrub_service.active()
        await scrub_service.entries(ListKind.LASTNAME, query="müba")
        return await scrub_service.try_text("Zeuge Bacedifo rief an.")

    outcome, longest, elapsed = await _longest_stall(work())
    assert getattr(outcome, "text", None) == "Zeuge <Lastname_1> rief an."
    assert longest < _STALL_SHARE * elapsed, f"stalled {longest:.2f} s of {elapsed:.2f} s"


async def test_one_scrubber_is_compiled_per_rule_set() -> None:
    meier = await compile_scrubber(ScrubRules(MANDATORY_RULES, lastnames=("Meier",)))
    again = await compile_scrubber(ScrubRules(MANDATORY_RULES, lastnames=("Meier",)))
    other = await compile_scrubber(ScrubRules(MANDATORY_RULES, lastnames=("Muster",)))
    assert again is meier
    assert other is not meier
    assert other.scrub("Herr Muster").text == "Herr <Lastname_1>"
