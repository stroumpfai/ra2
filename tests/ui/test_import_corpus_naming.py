"""A corpus is named when it is created (`SD68`, plan-corpus-naming.md)."""

import asyncio

import pytest
from nicegui.testing.user import User
from tests.ui.test_import_scrub import Mounted, _find, _one, _until, mounted  # noqa: F401

from ra2.domain.delivery import DeliveryStatus

pytestmark = pytest.mark.ui


async def _until_enabled(user: User, testid: str) -> None:
    """The button is drawn disabled until the delivery has been read."""
    await _until(
        lambda: bool(_find(user, testid)) and "disabled" not in _find(user, testid)[0]._props
    )


async def _open_analysed(env: Mounted) -> None:
    """`mounted` starts the analysis and does not wait for it, and the page
    does not poll for its end: open it only once the delivery is read."""
    await _until_status(env)
    await env.user.open("/import")


async def _until_status(env: Mounted) -> None:
    for _ in range(1000):
        if (await env.services.delivery.get(env.delivery_id)).status is (DeliveryStatus.ANALYSED):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the delivery was never analysed")


async def _freeze_by_button(env: Mounted, *, name: str | None, description: str) -> None:
    user = env.user
    await _open_analysed(env)
    await _until(lambda: bool(_find(user, "corpus-name-input")))
    if name is not None:
        _one(user, _find(user, "corpus-name-input")[0]).trigger("input", args=name)
    if description:
        _one(user, _find(user, "corpus-description-input")[0]).trigger("input", args=description)
    await _until_enabled(user, "create-corpus")
    _one(user, _find(user, "create-corpus")[0]).click()
    await _until(lambda: bool(_find(user, "corpus-name")))


async def test_the_name_defaults_to_the_deliverys_and_a_typed_one_wins(
    mounted: Mounted,  # noqa: F811
) -> None:
    user = mounted.user
    await _open_analysed(mounted)
    await _until(lambda: bool(_find(user, "corpus-name-input")))
    default = _find(user, "corpus-name-input")[0]._props["value"]
    assert default == (await mounted.services.delivery.get(mounted.delivery_id)).name

    await _freeze_by_button(mounted, name="only-canton-x", description="canton X, 2023")

    (corpus,) = (await mounted.services.corpus.list_corpora()).items
    assert (corpus.name, corpus.description) == ("only-canton-x", "canton X, 2023")
    (shown,) = _find(user, "corpus-description")
    assert str(getattr(shown, "text", "")) == "canton X, 2023"


async def test_an_untouched_form_freezes_under_the_deliverys_name(
    mounted: Mounted,  # noqa: F811
) -> None:
    await _freeze_by_button(mounted, name=None, description="")

    (corpus,) = (await mounted.services.corpus.list_corpora()).items
    delivery = await mounted.services.delivery.get(mounted.delivery_id)
    assert (corpus.name, corpus.description) == (delivery.name, None)


async def test_the_dialog_freezes_with_the_typed_name_too(mounted: Mounted) -> None:  # noqa: F811
    user = mounted.user
    await _open_analysed(mounted)
    await _until(lambda: bool(_find(user, "corpus-name-input")))
    _one(user, _find(user, "corpus-name-input")[0]).trigger("input", args="via-dialog")
    await _until_enabled(user, "scrub-preview")
    _one(user, _find(user, "scrub-preview")[0]).click()
    await _until(lambda: bool(_find(user, "scrub-preview-create")))
    _one(user, _find(user, "scrub-preview-create")[0]).click()
    await _until(lambda: bool(_find(user, "corpus-name")))

    (corpus,) = (await mounted.services.corpus.list_corpora()).items
    assert corpus.name == "via-dialog"


async def test_the_form_resets_after_a_freeze_and_the_same_name_is_v2(
    mounted: Mounted,  # noqa: F811
) -> None:
    await _freeze_by_button(mounted, name="data-2023", description="first")
    user = mounted.user
    await _until(lambda: _find(user, "corpus-name-input")[0]._props["value"] != "data-2023")
    assert _find(user, "corpus-description-input")[0]._props["value"] == ""

    _one(user, _find(user, "corpus-name-input")[0]).trigger("input", args="data-2023")
    await _until_enabled(user, "create-corpus")
    _one(user, _find(user, "create-corpus")[0]).click()
    await _until(lambda: len(_find(user, "corpus-name")) == 2)

    versions = sorted(c.version for c in (await mounted.services.corpus.list_corpora()).items)
    assert versions == [1, 2]
