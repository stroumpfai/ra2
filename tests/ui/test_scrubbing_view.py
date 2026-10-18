"""Layer 3 — the Scrubbing view (sw-design.md §19, `plan-text-scrubbing.md` §7.1).

The **real** view over the **real** `ScrubService` and a migrated temp-file
SQLite database. Files go in through the real `ui.upload`, by the seam NiceGUI
documents for tests (`Upload.handle_uploads`), and every file is a committed
fixture from `tests/fixtures/scrub/hazards/`.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.element import Element
from nicegui.elements.upload import Upload
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction

from ra2.domain.scrub import ListKind, ListNoticeCode, ScrubImportErrorCode
from ra2.infra.config import Settings
from ra2.services.container import Services
from ra2.ui.views.scrubbing_view import (
    ERROR_LABELS,
    KIND_LABELS,
    MANDATORY_ONLY,
    NO_FILE,
    NO_VERSIONS_MESSAGE,
    NOTICE_LABELS,
    REFUSED_TITLE,
    SCRUBBED_NOT_ANONYMISED,
)

pytestmark = pytest.mark.ui

SCRUB = Path(__file__).resolve().parents[1] / "fixtures" / "scrub" / "hazards"


def _fixture(name: str) -> bytes:
    return (SCRUB / name).read_bytes()


@dataclass(frozen=True, slots=True)
class Mounted:
    user: User
    services: Services


@pytest.fixture
async def mounted(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[Mounted]:
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                yield Mounted(User(client), app.state.services)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            from nicegui.functions.download import download
            from nicegui.functions.navigate import Navigate
            from nicegui.functions.notify import notify

            ui.navigate = Navigate()
            ui.notify = notify
            ui.download = download


# --- helpers -------------------------------------------------------------------


def _ordered(elements: Iterable[Element]) -> list[Element]:
    return sorted(elements, key=lambda e: e.id)


def _find(user: User, testid: str) -> list[Element]:
    return _ordered(
        e for e in user.find(kind=ui.element).elements if e._props.get("data-testid") == testid
    )


def _one(user: User, element: Element) -> UserInteraction[Element]:
    return UserInteraction(user, {element}, None)


def _text(element: Element) -> str:
    return str(getattr(element, "text", ""))


async def _until(predicate: Callable[[], bool]) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


def _file_row(user: User, kind: ListKind) -> Element:
    (row,) = [e for e in _find(user, "scrub-file-row") if e._props.get("data-kind") == kind.value]
    return row


def _texts_in(user: User, testid: str) -> list[str]:
    return [_text(e) for e in _find(user, testid)]


async def _upload(user: User, kind: ListKind, name: str) -> None:
    _one(user, _find(user, f"scrub-import-{kind.value}")[0]).click()
    await _until(lambda: bool(_find(user, "scrub-upload")))
    (element,) = [e for e in _find(user, "scrub-upload") if isinstance(e, Upload)]
    await element.handle_uploads([SmallFileUpload(name, "text/plain", _fixture(name))])


# --- the wording tables ------------------------------------------------------------


def test_every_refusal_every_notice_and_every_kind_has_words() -> None:
    """Codes are the stable identifiers; the words are this file's alone."""
    assert set(ERROR_LABELS) == set(ScrubImportErrorCode)
    assert set(NOTICE_LABELS) == set(ListNoticeCode)
    assert set(KIND_LABELS) == set(ListKind)


# --- before anything is imported ---------------------------------------------------


async def test_with_nothing_imported_the_mandatory_rules_are_shown(mounted: Mounted) -> None:
    user = mounted.user
    await user.open("/scrubbing")
    await user.should_see(MANDATORY_ONLY)
    await user.should_see(SCRUBBED_NOT_ANONYMISED)
    await user.should_see(NO_VERSIONS_MESSAGE)
    assert _texts_in(user, "scrub-rule-id") == ["license-plate", "phone", "email"]
    assert len(_find(user, "scrub-file-row")) == len(ListKind)
    assert len(_find(user, "scrub-file-none")) == len(ListKind)
    assert "B1" in _texts_in(user, "scrub-protected-string")


# --- importing -----------------------------------------------------------------------


async def test_an_imported_list_shows_its_file_and_what_was_counted(mounted: Mounted) -> None:
    user = mounted.user
    await user.open("/scrubbing")
    await _upload(user, ListKind.LASTNAME, "s02_lastnames.txt")
    await _until(lambda: bool(_find(user, "scrub-file-name")))
    await user.should_see("Rule set v1 is active.")
    row = _file_row(user, ListKind.LASTNAME)
    texts = [_text(e) for e in _ordered(row.descendants())]
    assert "s02_lastnames.txt" in texts
    assert "11 entries" in texts
    (notices,) = _find(user, "scrub-file-notices")
    assert NOTICE_LABELS[ListNoticeCode.DUPLICATES] in _text(notices)
    assert _texts_in(user, "scrub-version") == ["v1"]


async def test_a_refused_import_says_why_and_changes_nothing(mounted: Mounted) -> None:
    user = mounted.user
    await user.open("/scrubbing")
    await _upload(user, ListKind.LASTNAME, "s05_lastnames_cp1252.txt")
    await _until(lambda: bool(_find(user, "scrub-refusal-error")))
    await user.should_see(REFUSED_TITLE)
    (error,) = _find(user, "scrub-refusal-error")
    assert error._props["data-code"] == ScrubImportErrorCode.NOT_UTF8.value
    assert ERROR_LABELS[ScrubImportErrorCode.NOT_UTF8] in _text(error)
    assert (await mounted.services.scrub.active()).version is None


async def test_a_slow_rule_is_refused_by_its_own_code(mounted: Mounted) -> None:
    user = mounted.user
    await user.open("/scrubbing")
    await _upload(user, ListKind.REGEX, "s06_slow_rule.toml")
    await _until(lambda: bool(_find(user, "scrub-refusal-error")))
    (error,) = _find(user, "scrub-refusal-error")
    assert error._props["data-code"] == ScrubImportErrorCode.PATTERN_TOO_SLOW.value


async def test_removing_a_list_makes_a_version_without_it(mounted: Mounted) -> None:
    await mounted.services.scrub.import_list(
        ListKind.WHITELIST, "s03_whitelist.txt", _fixture("s03_whitelist.txt")
    )
    user = mounted.user
    await user.open("/scrubbing")
    _one(user, _find(user, "scrub-remove-whitelist")[0]).click()
    await _until(lambda: len(_find(user, "scrub-file-none")) == len(ListKind))
    assert _texts_in(user, "scrub-version") == ["v2", "v1"]


async def test_imported_rules_are_listed_after_the_mandatory_ones(mounted: Mounted) -> None:
    await mounted.services.scrub.import_list(
        ListKind.REGEX, "s04_rules.toml", _fixture("s04_rules.toml")
    )
    user = mounted.user
    await user.open("/scrubbing")
    assert _texts_in(user, "scrub-rule-id") == [
        "license-plate",
        "phone",
        "email",
        "iban-ch",
        "ahv",
        "date",
    ]
    assert "Tempo 80" in _texts_in(user, "scrub-protected-string")


# --- the list search -----------------------------------------------------------------


async def test_a_search_finds_a_name_however_it_is_spelt(mounted: Mounted) -> None:
    await mounted.services.scrub.import_list(
        ListKind.LASTNAME, "s02_lastnames.txt", _fixture("s02_lastnames.txt")
    )
    user = mounted.user
    await user.open("/scrubbing")
    await _until(lambda: len(_find(user, "scrub-entry")) == 11)
    (search,) = _find(user, "scrub-entry-search")
    _one(user, search).trigger("input", args="MUELL")
    await _until(lambda: _texts_in(user, "scrub-entry") == ["Müller"])


async def test_switching_the_list_shows_its_entries(mounted: Mounted) -> None:
    await mounted.services.scrub.import_list(
        ListKind.FIRSTNAME, "s01_firstnames.txt", _fixture("s01_firstnames.txt")
    )
    user = mounted.user
    await user.open("/scrubbing")
    await user.should_see(f"No {KIND_LABELS[ListKind.LASTNAME].lower()} imported.")
    (option,) = user.find(marker="seg-first-names").elements
    _one(user, option).click()
    await _until(lambda: "Hans" in _texts_in(user, "scrub-entry"))


# --- trying a sentence -----------------------------------------------------------------


async def test_a_typed_sentence_comes_back_scrubbed_as_plain_text(mounted: Mounted) -> None:
    for kind, name in (
        (ListKind.LASTNAME, "s02_lastnames.txt"),
        (ListKind.REGEX, "s04_rules.toml"),
    ):
        await mounted.services.scrub.import_list(kind, name, _fixture(name))
    user = mounted.user
    await user.open("/scrubbing")
    (editor,) = _find(user, "scrub-try-input")
    _one(user, editor).trigger("change", args="Herr Meier, 079 123 45 67, am 12.03.2024.")
    _one(user, _find(user, "scrub-try-run")[0]).click()
    await _until(lambda: bool(_find(user, "scrub-try-output")))
    (output,) = _find(user, "scrub-try-output")
    # A label, so the angle brackets are text, never markup.
    assert _text(output) == "Herr <Lastname_1>, <Phone_1>, am <Date_1>."
    (hits,) = _find(user, "scrub-try-hits")
    assert "<Lastname_1> (lastnames)" in _text(hits)


async def test_the_nav_reaches_the_screen(mounted: Mounted) -> None:
    user = mounted.user
    await user.open("/import")
    await user.should_see("Scrubbing")
    await user.open("/scrubbing")
    await user.should_see(KIND_LABELS[ListKind.REGEX])
    assert NO_FILE in _texts_in(user, "scrub-file-none")
