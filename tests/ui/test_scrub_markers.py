"""Layer 3 — the scrub markers outside the Scrubbing screen (`SD65`, §8.3).

The Results descriptor's pill, in both states, and the file report's caption
over its scrubbed raw preview. Never the word *anonymised*.
"""

import pytest
from nicegui.testing.user import User

from ra2.ui.views.file_report_modal import preview_caption
from ra2.ui.views.results.chrome import NOT_SCRUBBED_PILL, SCRUBBED_LABEL

pytestmark = pytest.mark.ui


def _descriptor(*, scrubbed: bool, scrub_version: int | None):  # type: ignore[no-untyped-def]
    from ra2.services.readmodels import RunDescriptorView

    return RunDescriptorView(
        evaluation_id="eval-x",  # type: ignore[arg-type]
        corpus_label="corpus-x",
        record_count=300,
        model_count=2,
        config_fingerprint="cfg12345678",
        is_dev=False,
        min_cell_count=20,
        scrubbed=scrubbed,
        scrub_version=scrub_version,
    )


async def test_a_board_over_a_corpus_from_before_scrubbing_warns(user: User) -> None:
    from nicegui import ui

    from ra2.ui.views.results.chrome import run_descriptor

    @ui.page("/t/not-scrubbed")
    def _view() -> None:
        run_descriptor(_descriptor(scrubbed=False, scrub_version=None))

    await user.open("/t/not-scrubbed")
    (pill,) = user.find(marker="scrub-pill").elements
    assert pill.props["data-scrubbed"] == "false"
    assert "pill-danger" in pill.classes
    await user.should_see(NOT_SCRUBBED_PILL)


@pytest.mark.parametrize(
    ("version", "label"), [(4, f"{SCRUBBED_LABEL} v4"), (None, SCRUBBED_LABEL)]
)
async def test_a_board_over_a_scrubbed_corpus_says_scrubbed_with_its_version(
    user: User, version: int | None, label: str
) -> None:
    from nicegui import ui

    from ra2.ui.views.results.chrome import run_descriptor

    @ui.page("/t/scrubbed")
    def _view() -> None:
        run_descriptor(_descriptor(scrubbed=True, scrub_version=version))

    await user.open("/t/scrubbed")
    (pill,) = user.find(marker="scrub-pill").elements
    assert pill.props["data-scrubbed"] == "true"
    await user.should_see(label)
    await user.should_not_see("anonymised")


def test_the_raw_preview_says_what_it_was_scrubbed_with() -> None:
    assert "rule set v2" in preview_caption(2)
    assert "mandatory rules" in preview_caption(None)
    assert "anonymis" not in preview_caption(2) + preview_caption(None)
