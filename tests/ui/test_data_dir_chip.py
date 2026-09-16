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
