"""Layer 3 — scrubbing on the Import screen (sw-design.md §19.7, `SD65`).

The dry run beside "Create corpus", the freeze it offers, and the scrub line
in the Corpora table's Status cell. The delivery is h18, the committed hazard
with invented personal data in its narratives, analysed through the real
`DeliveryService`; the rules are the committed scrub fixtures.
"""

import asyncio
import io
import os
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.element import Element
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.factories import seed_corpus

from ra2.domain.delivery import DeliveryStatus, SourceKind
from ra2.domain.ids import DeliveryId
from ra2.domain.scrub import ListKind
from ra2.infra.config import Settings
from ra2.services.container import Services
from ra2.ui.views.import_view import NOT_SCRUBBED, SCRUB_PREVIEW_LABEL

pytestmark = pytest.mark.ui

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
H18 = _FIXTURES / "deliveries" / "hazards" / "h18_names_in_narrative"
SCRUB = _FIXTURES / "scrub" / "hazards"


@dataclass(frozen=True, slots=True)
class Mounted:
    user: User
    services: Services
    session_factory: async_sessionmaker[AsyncSession]
    delivery_id: DeliveryId


@pytest.fixture
async def mounted(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[Mounted]:
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            services: Services = app.state.services
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                delivery_id = await services.delivery.register("h18", source_kind=SourceKind.UPLOAD)
                for name in ("unfall.txt", "text.csv"):
                    await services.delivery.add_file(
                        delivery_id, name, io.BytesIO((H18 / name).read_bytes())
                    )
                await services.delivery.analyse(delivery_id)
                await _analysed(services, delivery_id)
                yield Mounted(User(client), services, app.state.session_factory, delivery_id)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            from nicegui.functions.download import download
            from nicegui.functions.navigate import Navigate
            from nicegui.functions.notify import notify

            ui.navigate = Navigate()
            ui.notify = notify
            ui.download = download


async def _analysed(services: Services, delivery_id: DeliveryId) -> None:
    """Wait out `analyse`, which returns at once and works behind it. A page
    opened before it ends draws the dry-run button disabled for good, and a
    loaded host opens the page first."""
    for _ in range(3000):
        deliveries = await services.delivery.list_deliveries()
        if any(
            d.delivery_id == delivery_id and d.status is DeliveryStatus.ANALYSED for d in deliveries
        ):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the delivery never finished analysing")


def _ordered(elements: Iterable[Element]) -> list[Element]:
    return sorted(elements, key=lambda e: e.id)


def _find(user: User, testid: str) -> list[Element]:
    return _ordered(
        e for e in user.find(kind=ui.element).elements if e._props.get("data-testid") == testid
    )


def _one(user: User, element: Element) -> UserInteraction[Element]:
    return UserInteraction(user, {element}, None)


async def _until(predicate: Callable[[], bool]) -> None:
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


async def _open_preview(user: User) -> None:
    await user.open("/import")
    await _until(lambda: bool(_find(user, "scrub-preview")))
    _one(user, _find(user, "scrub-preview")[0]).click()
    await _until(lambda: bool(_find(user, "scrub-preview-row")))


async def test_the_dry_run_lists_every_rule_that_would_run(mounted: Mounted) -> None:
    await mounted.services.scrub.import_list(
        ListKind.LASTNAME, "l.txt", (SCRUB / "s02_lastnames.txt").read_bytes()
    )
    user = mounted.user
    await _open_preview(user)
    await user.should_see(f"{SCRUB_PREVIEW_LABEL} · rules v1")
    rows = [e._props["data-rule-id"] for e in _find(user, "scrub-preview-row")]
    assert rows == ["license-plate", "phone", "email", "lastnames"]
    (records,) = _find(user, "scrub-preview-records")
    assert "3 of 3 records" in str(getattr(records, "text", ""))


async def test_the_dialog_freezes_with_the_version_it_showed(mounted: Mounted) -> None:
    """Shown v1; v2 imported meanwhile; the dialog's Create still uses v1."""
    await mounted.services.scrub.import_list(
        ListKind.LASTNAME, "l.txt", (SCRUB / "s02_lastnames.txt").read_bytes()
    )
    user = mounted.user
    await _open_preview(user)
    await mounted.services.scrub.import_list(
        ListKind.WHITELIST, "w.txt", (SCRUB / "s03_whitelist.txt").read_bytes()
    )
    _one(user, _find(user, "scrub-preview-create")[0]).click()
    await _until(lambda: bool(_find(user, "scrub-status")))
    (corpus,) = (await mounted.services.corpus.list_corpora()).items
    assert (corpus.scrubbed, corpus.scrub_version) == (True, 1)
    (status,) = _find(user, "scrub-status")
    assert status._props["data-scrubbed"] == "true"
    assert str(getattr(status, "text", "")) == "scrubbed · rules v1"
    assert "Lastname" in str(status._props.get("title", ""))


async def test_a_corpus_from_before_scrubbing_says_not_scrubbed(mounted: Mounted) -> None:
    async with mounted.session_factory() as session:
        await seed_corpus(session, "old-corpus", name="before")
        await session.commit()
    user = mounted.user
    await user.open("/import")
    await _until(lambda: bool(_find(user, "scrub-status")))
    (status,) = _find(user, "scrub-status")
    assert status._props["data-scrubbed"] == "false"
    await user.should_see(NOT_SCRUBBED)
    await user.should_see("Not used by any evaluation")


async def test_a_placeholder_row_opens_to_what_it_replaced(mounted: Mounted) -> None:
    """SD70 through the real dialog: the span is shown as delivered inside a
    sentence, only rules that replaced something have a toggle, and the dialog
    still has its one Create."""
    await mounted.services.scrub.import_list(
        ListKind.LASTNAME, "l.txt", (SCRUB / "s02_lastnames.txt").read_bytes()
    )
    user = mounted.user
    await _open_preview(user)
    preview = await mounted.services.corpus.scrub_preview(mounted.delivery_id)
    replaced = {c.rule_id for c in preview.counts if c.hits}
    assert replaced
    assert {e._props["data-rule-id"] for e in _find(user, "scrub-toggle")} == replaced
    spans = _find(user, "scrub-example-span")
    assert spans, "a rule with a handful of values opens expanded"
    assert all(str(getattr(s, "text", "")).strip() for s in spans)
    assert len(_find(user, "scrub-preview-create")) == 1
