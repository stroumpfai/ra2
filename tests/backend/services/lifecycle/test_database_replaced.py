"""The app notices when the database file is swapped under it.

`just reset` and `just reset-seed` unlink `ra2.sqlite` and write a new one. A
process that is up across that keeps its **pooled** connections on the deleted
inode while every connection it opens afterwards gets the new file — so it
reads and writes two databases at once, by pool luck, with no error anywhere.
Reproduced before this existed: sixteen concurrent reads in one process
returned two different corpora
(`plan-fix-results-visibility.md` §3.1).

Nothing can repair that from inside the process. What it can do is say so, on
every screen, which is what `DataDirView.database_replaced` carries.
"""

import pytest

from ra2.infra.config import Settings
from ra2.infra.filestore import UploadedFileStore
from ra2.services.lifecycle_service import LifecycleService

pytestmark = pytest.mark.backend


def _service(settings: Settings) -> LifecycleService:
    return LifecycleService(
        session_factory=None,  # type: ignore[arg-type]
        upload_store=UploadedFileStore(settings.deliveries_dir, max_bytes=1),
        settings=settings,
    )


def test_an_untouched_database_is_not_reported_as_replaced(run_upgrade_head: Settings) -> None:
    service = _service(run_upgrade_head)

    assert service.data_dir().database_replaced is False
    # Read twice: the check must not be a one-shot that arms itself on the
    # first call and then reports every later one.
    assert service.data_dir().database_replaced is False


def test_a_replaced_file_is_reported(run_upgrade_head: Settings) -> None:
    """The reported hazard, at its smallest: same path, different file.

    **The open handle is the point, not scaffolding.** A live app holds the
    database open on its pooled connections; that is what keeps the deleted
    inode alive, what makes the split brain possible, and what stops the
    filesystem from handing the same inode number straight back to the new
    file. Without it this test passes or fails depending on whether tmpfs
    recycled the number — and so, honestly, does the check itself: a process
    holding nothing open can be swapped under without noticing. The state
    worth detecting is the one where something *is* open.
    """
    service = _service(run_upgrade_head)
    assert service.data_dir().database_replaced is False

    with run_upgrade_head.database_path.open("rb"):
        run_upgrade_head.database_path.unlink()
        run_upgrade_head.database_path.write_bytes(b"")

        assert service.data_dir().database_replaced is True


def test_a_database_that_does_not_exist_yet_is_adopted_not_reported(
    backend_settings: Settings,
) -> None:
    """A file **appearing** is not a file being replaced.

    The app can legitimately start before `alembic upgrade head` has created
    the database — `just dev` on a fresh data directory does exactly that —
    and a check that called the first file it ever saw a replacement would
    put a permanent red banner on a perfectly healthy first run.
    """
    assert not backend_settings.database_path.exists()
    service = _service(backend_settings)

    backend_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    backend_settings.database_path.write_bytes(b"")

    assert service.data_dir().database_replaced is False


def test_a_deleted_database_is_not_yet_a_replacement(run_upgrade_head: Settings) -> None:
    """Mid-reset, between the unlink and the new file, there is nothing to
    compare against. "Absent" is a third answer, and the banner belongs to the
    state that is actually ambiguous — two files, one process."""
    service = _service(run_upgrade_head)
    assert service.data_dir().database_replaced is False

    run_upgrade_head.database_path.unlink()

    assert service.data_dir().database_replaced is False
