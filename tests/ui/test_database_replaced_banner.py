"""Layer 3 — the banner that says the database was swapped under this process.

`just reset-seed` while the app is up leaves that process reading **two**
databases: the deleted inode on its pooled connections, the new file on every
connection it opens afterwards. Reproduced at sixteen concurrent reads in one
process returning two different corpora (`plan-fix-results-visibility.md`
§3.1). `LifecycleService` detects it; this is the half a person sees.

Asserted on the shell rather than on a view, because the condition belongs to
the **process**: any screen can be the one showing a page built from either
file, so every screen carries it.
"""

import pytest
from nicegui import ui
from nicegui.testing.user import User

from ra2.ui.shell import DATABASE_REPLACED_MESSAGE, shell

pytestmark = pytest.mark.ui


def _page(path: str, *, replaced: bool) -> None:
    @ui.page(path)
    def _view() -> None:
        with shell(
            title="Import",
            description="One delivery.",
            active="import",
            data_dir="/srv/ra2/var",
            database_replaced=replaced,
        ):
            ui.label("body")


async def test_the_banner_is_absent_when_the_database_is_the_one_we_opened(
    user: User,
) -> None:
    """The normal case is every case but one, and a warning that is always
    on screen is furniture."""
    _page("/banner/none", replaced=False)
    await user.open("/banner/none")

    await user.should_not_see(marker="database-replaced")


async def test_the_banner_names_the_cause_and_the_fix(user: User) -> None:
    """Verbatim, because the sentence is the whole feature: an analyst who
    reads "restart the app" restarts it, and one who reads a generic warning
    reloads the page and gets the same two databases."""
    _page("/banner/replaced", replaced=True)
    await user.open("/banner/replaced")

    await user.should_see(DATABASE_REPLACED_MESSAGE)
    assert "Restart the app." in DATABASE_REPLACED_MESSAGE


async def test_the_banner_does_not_replace_the_page(user: User) -> None:
    """It warns; it does not hide the screen. The analyst may be mid-way
    through something they need to finish reading, and the state is about
    where the data came from rather than about the controls."""
    _page("/banner/with-body", replaced=True)
    await user.open("/banner/with-body")

    await user.should_see(marker="database-replaced")
    await user.should_see("body")
