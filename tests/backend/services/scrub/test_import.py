"""`ScrubService`: importing files, the active set, and its history
(sw-design.md §19.4, §19.5, §19.7)."""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.backend.services.scrub.conftest import FIXTURE_LISTS, scrub_bytes

import ra2.services.scrub_service as scrub_service_module
from ra2.domain.scrub import ListKind, ScrubImportErrorCode, ScrubRules, compute_rules_fingerprint
from ra2.domain.scrub_mandatory import MANDATORY_RULES
from ra2.persistence.models import ScrubList, ScrubRuleset
from ra2.services.errors import ScrubImportRefusedError
from ra2.services.scrub_service import ScrubService

pytestmark = pytest.mark.backend


async def _count(factory: async_sessionmaker[AsyncSession], model: type) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_with_nothing_imported_the_mandatory_rules_are_active(
    scrub_service: ScrubService,
) -> None:
    view = await scrub_service.active()
    assert (view.ruleset_id, view.version) == (None, None)
    assert [r.rule_id for r in view.rules] == [r.rule_id for r in MANDATORY_RULES]
    assert all(r.source == "mandatory" for r in view.rules)
    assert view.lists == ()
    assert "B1" in view.protected


async def test_each_import_makes_the_next_version_with_one_kind_swapped(
    scrub_service: ScrubService, import_fixture_lists: Callable[[], Awaitable[None]]
) -> None:
    await import_fixture_lists()
    view = await scrub_service.active()
    assert view.version == len(FIXTURE_LISTS)
    assert [lst.kind for lst in view.lists] == ["regex", "firstname", "lastname", "whitelist"]
    assert [r.rule_id for r in view.rules][-3:] == ["iban-ch", "ahv", "date"]
    assert view.rules[-1].source == "imported"
    assert "Tempo 80" in view.protected
    assert [v.version for v in await scrub_service.versions()] == [4, 3, 2, 1]


async def test_an_import_reports_what_it_counted_without_refusing(
    scrub_service: ScrubService,
) -> None:
    result = await scrub_service.import_list(
        ListKind.LASTNAME, "s02_lastnames.txt", scrub_bytes("s02_lastnames.txt")
    )
    codes = {n.code: n for n in result.notices}
    assert {"bom", "crlf", "duplicates", "too_short", "no_letters"} <= set(codes)
    stored = (await scrub_service.active()).lists[0]
    assert stored.entry_count == 11
    assert {n.code for n in stored.notices} == set(codes)


async def test_importing_the_active_file_again_changes_nothing(
    scrub_service: ScrubService, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    content = scrub_bytes("s03_whitelist.txt")
    first = await scrub_service.import_list(ListKind.WHITELIST, "w.txt", content)
    again = await scrub_service.import_list(ListKind.WHITELIST, "w-copy.txt", content)
    assert (first.no_change, again.no_change) == (False, True)
    assert again.ruleset.version == first.ruleset.version == 1
    assert await _count(db_session_factory, ScrubRuleset) == 1


async def test_the_same_file_coming_back_reuses_its_row(
    scrub_service: ScrubService, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """v1 whitelist A, v2 whitelist B, v3 whitelist A again: three versions,
    two `scrub_list` rows."""
    a, b = scrub_bytes("s03_whitelist.txt"), b"Fink\nAmsel\n"
    for content in (a, b, a):
        await scrub_service.import_list(ListKind.WHITELIST, "w.txt", content)
    assert await _count(db_session_factory, ScrubRuleset) == 3
    assert await _count(db_session_factory, ScrubList) == 2


@pytest.mark.parametrize(
    ("kind", "fixture", "code"),
    [
        (ListKind.LASTNAME, "s05_lastnames_cp1252.txt", ScrubImportErrorCode.NOT_UTF8),
        (ListKind.REGEX, "s06_slow_rule.toml", ScrubImportErrorCode.PATTERN_TOO_SLOW),
    ],
)
async def test_a_refused_import_writes_nothing(
    scrub_service: ScrubService,
    db_session_factory: async_sessionmaker[AsyncSession],
    kind: ListKind,
    fixture: str,
    code: ScrubImportErrorCode,
) -> None:
    with pytest.raises(ScrubImportRefusedError) as refused:
        await scrub_service.import_list(kind, fixture, scrub_bytes(fixture))
    assert [e.code for e in refused.value.import_errors] == [code]
    assert await _count(db_session_factory, ScrubList) == 0
    assert await _count(db_session_factory, ScrubRuleset) == 0


async def test_a_list_is_checked_against_the_rest_of_the_set(scrub_service: ScrubService) -> None:
    """`Rega` alone on a surname list turns `Rega 1414` into a person: the
    composition is refused, though the file itself is well formed."""
    with pytest.raises(ScrubImportRefusedError) as refused:
        await scrub_service.import_list(ListKind.LASTNAME, "l.txt", b"Rega\nMeier\n")
    assert [(e.code, e.detail["protected"]) for e in refused.value.import_errors] == [
        (ScrubImportErrorCode.PROTECTED_ALTERED, "Rega 1414")
    ]


async def test_a_whitelist_that_resolves_a_collision_makes_the_list_importable(
    scrub_service: ScrubService,
) -> None:
    await scrub_service.import_list(ListKind.WHITELIST, "w.txt", b"Rega\n")
    result = await scrub_service.import_list(ListKind.LASTNAME, "l.txt", b"Rega\nMeier\n")
    assert result.ruleset.version == 2


async def test_removing_the_whitelist_that_a_list_relies_on_is_refused(
    scrub_service: ScrubService,
) -> None:
    await scrub_service.import_list(ListKind.WHITELIST, "w.txt", b"Rega\n")
    await scrub_service.import_list(ListKind.LASTNAME, "l.txt", b"Rega\nMeier\n")
    with pytest.raises(ScrubImportRefusedError):
        await scrub_service.remove_list(ListKind.WHITELIST)
    assert (await scrub_service.active()).version == 2


async def test_removing_a_file_makes_a_version_without_it(scrub_service: ScrubService) -> None:
    await scrub_service.import_list(ListKind.FIRSTNAME, "f.txt", b"Hans\nAnna\n")
    removed = await scrub_service.remove_list(ListKind.FIRSTNAME)
    assert (removed.no_change, removed.ruleset.version, removed.ruleset.lists) == (False, 2, ())
    again = await scrub_service.remove_list(ListKind.FIRSTNAME)
    assert (again.no_change, again.ruleset.version) == (True, 2)


async def test_entries_are_searched_the_way_the_scrubber_compares(
    scrub_service: ScrubService,
) -> None:
    await scrub_service.import_list(
        ListKind.LASTNAME, "s02_lastnames.txt", scrub_bytes("s02_lastnames.txt")
    )
    for query in ("müll", "MUELL", "Mull"):
        page = await scrub_service.entries(ListKind.LASTNAME, query=query)
        assert [e.entry for e in page.items] == ["Müller"], query
    assert (await scrub_service.entries(ListKind.LASTNAME, query="d'al")).items[0].key == (
        "d alessandro"
    )


async def test_entries_page_in_file_order(scrub_service: ScrubService) -> None:
    await scrub_service.import_list(
        ListKind.LASTNAME, "s02_lastnames.txt", scrub_bytes("s02_lastnames.txt")
    )
    page = await scrub_service.entries(ListKind.LASTNAME, page=2, page_size=4)
    assert page.total == 11
    assert [e.entry for e in page.items] == ["Martin", "Simon", "von Allmen", "D'Alessandro"]
    assert (await scrub_service.entries(ListKind.FIRSTNAME)).total == 0


async def test_a_sentence_is_scrubbed_with_the_active_rules(
    scrub_service: ScrubService, import_fixture_lists: Callable[[], Awaitable[None]]
) -> None:
    await import_fixture_lists()
    result = await scrub_service.try_text("Herr Meier, 079 123 45 67, am 12.03.2024.")
    assert result.text == "Herr <Lastname_1>, <Phone_1>, am <Date_1>."
    assert [h.rule_id for h in result.hits] == ["lastnames", "phone", "date"]


async def test_the_active_fingerprint_is_computed_once_per_set(
    scrub_service: ScrubService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Scrubbing screen shows it on every visit, and computing it reads
    every entry of every list: a surname list made each visit cost seconds."""
    computed: list[ScrubRules] = []

    def counting(rules: ScrubRules) -> str:
        computed.append(rules)
        return compute_rules_fingerprint(rules)

    monkeypatch.setattr(scrub_service_module, "compute_rules_fingerprint", counting)
    await scrub_service.import_list(
        ListKind.LASTNAME, "s02_lastnames.txt", scrub_bytes("s02_lastnames.txt")
    )
    first = await scrub_service.active()
    shown = len(computed)
    assert (await scrub_service.active()).fingerprint == first.fingerprint
    assert len(computed) == shown
    await scrub_service.import_list(
        ListKind.FIRSTNAME, "s01_firstnames.txt", scrub_bytes("s01_firstnames.txt")
    )
    assert (await scrub_service.active()).fingerprint != first.fingerprint
