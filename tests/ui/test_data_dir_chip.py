"""Layer 3 — the header's data-directory chip
(plan-reset-and-discard.md §2.1 item 6).

One line of the header, and the reason it is worth a test is the failure it
prevents: `just dev` and `just dev-agent` run the same app against **different
databases**, and a screen that does not say which one it is looking at has
already cost a developer their live test data once.

What is asserted is the contract, not the styling: the chip renders the value
it was given, it renders **nothing** when there is none, and it is not a
control.
"""

import pytest
from nicegui import ui
from nicegui.testing.user import User

from ra2.ui.shell import shell

pytestmark = pytest.mark.ui

_DATA_DIR = "/srv/ra2/var"

#: The shape `scripts/dev_agent.py` actually produces on Windows: a
#: `tempfile.mkdtemp()` path under the user profile. `\U` is the hazard —
#: read as a Python string literal it is a truncated `\UXXXXXXXX` escape.
_WINDOWS_DATA_DIR = r"C:\Users\dev\AppData\Local\Temp\ra2-dev-agent-abc123"

#: Worse than the crash, because it does not crash: read as a Python string
#: literal every one of these backslash pairs is a valid escape, so the value
#: would arrive silently corrupted — `C:<TAB>mp<TAB>he<LF>ew<CR>eport`.
_ESCAPE_SOUP_DATA_DIR = r"C:\tmp\the\new\report"


def _page(path: str, data_dir: str | None) -> None:
    @ui.page(path)
    def _view() -> None:
        with shell(title="Import", description="One delivery.", active="import", data_dir=data_dir):
            ui.label("body")


async def test_the_header_names_the_data_directory(user: User) -> None:
    _page("/chip/with", _DATA_DIR)
    await user.open("/chip/with")

    await user.should_see(_DATA_DIR)
    (chip,) = user.find(marker="data-dir").elements
    # The full path is in `title` too: the chip ellipsises, and a truncated
    # path is exactly the case where someone needs to read the whole thing.
    assert chip._props["title"] == _DATA_DIR


async def test_a_windows_path_does_not_break_the_page(user: User) -> None:
    """The regression that made `just dev-agent` unusable on Windows (SD31).

    `scripts/dev_agent.py` points `RA2_DATA_DIR` at `tempfile.mkdtemp()`, and
    on Windows that is `C:\\Users\\...` — which the old `.props(f'title="{...}"')`
    handed to `ast.literal_eval`, so **every page** raised `SyntaxError` and
    returned 500. The POSIX `_DATA_DIR` above has no backslash, which is
    exactly why this went unnoticed: `just dev` defaults to `./var`.
    """
    _page("/chip/windows", _WINDOWS_DATA_DIR)
    await user.open("/chip/windows")

    await user.should_see(_WINDOWS_DATA_DIR)
    (chip,) = user.find(marker="data-dir").elements
    assert chip._props["title"] == _WINDOWS_DATA_DIR


async def test_a_path_of_valid_escapes_is_not_silently_rewritten(user: User) -> None:
    """The quieter half of the same bug, and the reason escaping backslashes
    would not have been a fix.

    Every backslash pair in `C:\\tmp\\the\\new\\report` is a *valid* Python
    escape, so `ast.literal_eval` would not have raised — it would have handed
    back `C:<TAB>mp<TAB>he<LF>ew<CR>eport`, and the tooltip would have named a
    directory that does not exist. A developer reading it to decide whether
    they are pointed at their own database would have been told the wrong
    answer, which is the one failure this chip exists to prevent.
    """
    _page("/chip/escapes", _ESCAPE_SOUP_DATA_DIR)
    await user.open("/chip/escapes")

    (chip,) = user.find(marker="data-dir").elements
    assert chip._props["title"] == _ESCAPE_SOUP_DATA_DIR
    assert "\t" not in chip._props["title"]
    assert "\n" not in chip._props["title"]


async def test_it_renders_nothing_when_there_is_none(user: User) -> None:
    """`placeholder_view` has no services to ask, and a header that guessed
    which database it was looking at would be worse than one that says
    nothing."""
    _page("/chip/without", None)
    await user.open("/chip/without")

    await user.should_not_see(marker="data-dir")


async def test_it_is_a_label_and_not_a_control(user: User) -> None:
    """Changing the data directory is an environment variable and a restart
    (`RA2_DATA_DIR`). A chip that looked clickable would imply otherwise."""
    _page("/chip/inert", _DATA_DIR)
    await user.open("/chip/inert")

    (chip,) = user.find(marker="data-dir").elements
    assert chip.tag != "button"
    assert not chip._event_listeners
