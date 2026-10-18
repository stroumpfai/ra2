# NEW — feat/text-scrubbing. Signatures frozen in CONTRACTS.md.
"""Import scrub rules and lists, and say what the next freeze will apply
(sw-design.md §19, `SD62`–`SD66`).

The scrubbing itself happens elsewhere: at freeze and in the dry run
(`CorpusService`, so both walk the delivery with the same code) and in the raw
preview (`DeliveryService`). All three ask `load_scrub_rules` for the rules,
so they cannot disagree about what is active.

**An import is checked whole.** The new file is composed with the mandatory
rules and the active set's other files, and `check_rules` runs over the
composition: a whitelist removed, a list added or a rule file swapped can each
turn a protected string into a placeholder, and only the composition can say.

**Never on the event loop.** A surname list runs to hundreds of thousands of
entries, and parsing one, checking a composition or building a `Scrubber`
over it takes seconds. NiceGUI drops a page whose socket misses its
heartbeat for about six seconds, which is how a refused import once lost the
dialog that said why. Every such step here runs in `asyncio.to_thread`
(§19.7), and the two results worth keeping are kept: a stored file's parse,
by its hash, and the scrubber of the set in use.
"""

import asyncio
import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import ScrubListId, ScrubRulesetId
from ra2.domain.scrub import (
    PROTECTED_STRINGS,
    ListKind,
    ListNotice,
    NameListFile,
    RegexRule,
    RegexRuleFile,
    Scrubber,
    ScrubImportError,
    ScrubRules,
    ScrubTimeoutError,
    check_rules,
    compute_rules_fingerprint,
    entry_key,
    parse_name_list,
    parse_regex_rules,
    search_entries,
)
from ra2.domain.scrub_mandatory import MANDATORY_RULES, MANDATORY_RULES_VERSION
from ra2.infra.clock import Clock
from ra2.infra.idgen import IdFactory
from ra2.persistence.models import ScrubList, ScrubRuleset
from ra2.persistence.repositories.scrub_repo import ScrubRepository
from ra2.persistence.session import session_scope
from ra2.services.errors import ScrubImportRefusedError
from ra2.services.readmodels import (
    Page,
    ScrubEntryView,
    ScrubHitView,
    ScrubImportView,
    ScrubListView,
    ScrubNoticeView,
    ScrubRulesetView,
    ScrubRuleView,
    ScrubTryView,
    ScrubVersionView,
    SortDir,
)

__all__ = [
    "LoadedRules",
    "ScrubService",
    "compile_scrubber",
    "load_scrub_rules",
    "mandatory_snapshot",
]

#: The order the screen lists a rule set's files in, and the column each
#: kind is stored under on `scrub_ruleset`.
_COMPONENT_COLUMNS: Mapping[ListKind, str] = {
    ListKind.REGEX: "regex_list_id",
    ListKind.FIRSTNAME: "firstname_list_id",
    ListKind.LASTNAME: "lastname_list_id",
    ListKind.WHITELIST: "whitelist_id",
}


@dataclass(frozen=True, slots=True)
class _Component:
    """One stored file, parsed back."""

    row: ScrubList
    parsed: RegexRuleFile | NameListFile


@dataclass(frozen=True, slots=True)
class LoadedRules:
    """A rule-set version and everything it composes to, with the
    mandatory rules. `ruleset` is `None` when nothing was imported."""

    ruleset: ScrubRuleset | None
    rules: ScrubRules


# ===========================================================================
# Loading and composing — shared with CorpusService and DeliveryService
# ===========================================================================


class _Recent[K: Hashable, V]:
    """The few most recently used values, by key. Locked, because a task
    runner may drive a service on a second event loop in its own thread."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._items: OrderedDict[K, V] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: K) -> V | None:
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key: K, value: V) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._size:
                self._items.popitem(last=False)


#: Stored files, parsed, by kind and `sha256`. A `scrub_list` row is never
#: rewritten, so a parse cannot go stale: without this, every screen that
#: shows the active set parsed every list in it again.
_PARSED: Final[_Recent[tuple[ListKind, str], RegexRuleFile | NameListFile]] = _Recent(8)

#: Compiled scrubbers, by the rules they apply. Keyed on the composed
#: `ScrubRules` itself, never on an id or a stored fingerprint, so a hit is a
#: scrubber for exactly these rules. Cheap to look up: the lists in it come
#: from `_PARSED`, so comparing two keys compares the same strings.
_SCRUBBERS: Final[_Recent[ScrubRules, Scrubber]] = _Recent(2)

#: Fingerprints of composed sets, by the same key. The Scrubbing screen shows
#: the active set's on every visit, and computing it reads every entry.
_FINGERPRINTS: Final[_Recent[ScrubRules, str]] = _Recent(4)


def _parse(kind: ListKind, content: bytes) -> RegexRuleFile | NameListFile | list[ScrubImportError]:
    return parse_regex_rules(content) if kind is ListKind.REGEX else parse_name_list(kind, content)


async def _parse_stored(row: ScrubList) -> RegexRuleFile | NameListFile:
    """A stored file, parsed again. It was valid when it was imported and is
    never rewritten, so a failure here is a corrupted database, not input."""
    kind = ListKind(row.kind)
    cached = _PARSED.get((kind, row.sha256))
    if cached is not None:
        return cached
    parsed = await asyncio.to_thread(_parse, kind, row.content_text.encode("utf-8"))
    if isinstance(parsed, list):
        raise RuntimeError(f"stored scrub list {row.id} no longer parses: {parsed[0].code}")
    _PARSED.put((kind, row.sha256), parsed)
    return parsed


def _compiled(rules: ScrubRules) -> Scrubber:
    scrubber = Scrubber(rules)
    # Every freeze and dry run reads it, so it is computed here, in the thread.
    _ = scrubber.fingerprint
    return scrubber


async def _fingerprint(rules: ScrubRules) -> str:
    fingerprint = _FINGERPRINTS.get(rules)
    if fingerprint is None:
        fingerprint = await asyncio.to_thread(compute_rules_fingerprint, rules)
        _FINGERPRINTS.put(rules, fingerprint)
    return fingerprint


async def compile_scrubber(rules: ScrubRules) -> Scrubber:
    """`Scrubber(rules)`, built off the event loop and kept for the next call
    with the same rules: the freeze, the dry run, the raw preview and the
    sentence on the Scrubbing screen all apply the active set."""
    scrubber = _SCRUBBERS.get(rules)
    if scrubber is None:
        scrubber = await asyncio.to_thread(_compiled, rules)
        _SCRUBBERS.put(rules, scrubber)
    return scrubber


def _compose(
    components: Mapping[ListKind, RegexRuleFile | NameListFile | None], *, mandatory: bool = True
) -> ScrubRules:
    regex_file = components.get(ListKind.REGEX)
    imported: tuple[RegexRule, ...] = ()
    protected: tuple[str, ...] = ()
    if isinstance(regex_file, RegexRuleFile):
        imported, protected = regex_file.rules, regex_file.protected

    def entries(kind: ListKind) -> tuple[str, ...]:
        parsed = components.get(kind)
        return parsed.entries if isinstance(parsed, NameListFile) else ()

    return ScrubRules(
        regex_rules=(*MANDATORY_RULES, *imported) if mandatory else imported,
        firstnames=entries(ListKind.FIRSTNAME),
        lastnames=entries(ListKind.LASTNAME),
        whitelist=entries(ListKind.WHITELIST),
        protected=protected,
    )


async def _components(
    repo: ScrubRepository, ruleset: ScrubRuleset | None
) -> dict[ListKind, _Component]:
    found: dict[ListKind, _Component] = {}
    if ruleset is None:
        return found
    for kind, column in _COMPONENT_COLUMNS.items():
        list_id: ScrubListId | None = getattr(ruleset, column)
        if list_id is None:
            continue
        row = await repo.get_list(list_id)
        if row is None:  # pragma: no cover - a RESTRICT foreign key forbids it
            raise RuntimeError(f"scrub rule set {ruleset.id} cites a missing list {list_id}")
        found[kind] = _Component(row, await _parse_stored(row))
    return found


async def load_scrub_rules(
    session: AsyncSession, ruleset_id: ScrubRulesetId | None = None
) -> LoadedRules:
    """The rules a scrub applies: the given version, or the active one.

    With nothing imported, the mandatory rules alone (`SD63`).

    :raises LookupError: `ruleset_id` names no version. Callers turn it into
        their own `NotFoundError`.
    """
    repo = ScrubRepository(session)
    if ruleset_id is None:
        ruleset = await repo.get_active()
    else:
        ruleset = await repo.get_ruleset(ruleset_id)
        if ruleset is None:
            raise LookupError(ruleset_id)
    components = await _components(repo, ruleset)
    rules = _compose({kind: c.parsed for kind, c in components.items()})
    return LoadedRules(ruleset, rules)


def mandatory_snapshot() -> list[dict[str, object]]:
    """The mandatory rules as a corpus records them (`scrub_mandatory_json`)."""
    return [
        {
            "version": MANDATORY_RULES_VERSION,
            "id": rule.rule_id,
            "tag": rule.tag,
            "pattern": rule.pattern,
        }
        for rule in MANDATORY_RULES
    ]


# ===========================================================================
# Views
# ===========================================================================


def _notices(notices: Sequence[ListNotice]) -> tuple[ScrubNoticeView, ...]:
    return tuple(ScrubNoticeView(n.code.value, n.count, n.examples) for n in notices)


def _dump_notices(notices: Sequence[ListNotice]) -> str:
    return json.dumps(
        [{"code": n.code.value, "count": n.count, "examples": list(n.examples)} for n in notices],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _load_notices(payload: str) -> tuple[ScrubNoticeView, ...]:
    """The inverse of `_dump_notices`, which wrote every field."""
    raw: list[dict[str, Any]] = json.loads(payload) if payload else []
    return tuple(
        ScrubNoticeView(str(n["code"]), int(n["count"]), tuple(str(e) for e in n["examples"]))
        for n in raw
    )


def _rule_view(rule: RegexRule) -> ScrubRuleView:
    return ScrubRuleView(
        rule_id=rule.rule_id,
        tag=rule.tag,
        pattern=rule.pattern,
        source=rule.source.value,
        description=rule.description,
        must_match=rule.must_match,
        must_not_match=rule.must_not_match,
    )


def _list_view(kind: ListKind, row: ScrubList) -> ScrubListView:
    return ScrubListView(
        scrub_list_id=ScrubListId(row.id),
        kind=kind.value,
        filename=row.filename,
        sha256=row.sha256,
        imported_at=row.imported_at,
        entry_count=row.entry_count,
        notices=_load_notices(row.import_report_json),
    )


async def _ruleset_view(
    ruleset: ScrubRuleset | None, components: Mapping[ListKind, _Component]
) -> ScrubRulesetView:
    rules = _compose({kind: c.parsed for kind, c in components.items()})
    return ScrubRulesetView(
        ruleset_id=ScrubRulesetId(ruleset.id) if ruleset else None,
        version=ruleset.version if ruleset else None,
        created_at=ruleset.created_at if ruleset else None,
        fingerprint=await _fingerprint(rules),
        mandatory_version=MANDATORY_RULES_VERSION,
        rules=tuple(_rule_view(r) for r in rules.regex_rules),
        lists=tuple(
            _list_view(kind, components[kind].row)
            for kind in _COMPONENT_COLUMNS
            if kind in components
        ),
        protected=(*PROTECTED_STRINGS, *rules.protected),
    )


# ===========================================================================
# The service
# ===========================================================================


class ScrubService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        ids: IdFactory,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._ids = ids

    # --- writes ------------------------------------------------------------

    async def import_list(self, kind: ListKind, filename: str, content: bytes) -> ScrubImportView:
        """Import one file and make the rule set it completes active (§19.7).

        1. Parse the file (`parse_regex_rules` / `parse_name_list`).
        2. Compose it with the mandatory rules and the active set's other
           files, and `check_rules` the composition.
        3. Reuse the `scrub_list` row an identical upload made, or add one,
           and add version n+1 with this kind swapped.

        Importing the file the active set already has for this kind changes
        nothing (`no_change=True`), as a codelist re-upload does (§14.1).

        :raises ScrubImportRefusedError: any refusal; nothing is written.
        """
        parsed = await asyncio.to_thread(_parse, kind, content)
        if isinstance(parsed, list):
            raise ScrubImportRefusedError(parsed)
        sha256 = hashlib.sha256(content).hexdigest()

        async with session_scope(self._session_factory) as session:
            repo = ScrubRepository(session)
            active = await repo.get_active()
            components = await _components(repo, active)
            current = components.get(kind)
            if active is not None and current is not None and current.row.sha256 == sha256:
                return ScrubImportView(
                    await _ruleset_view(active, components),
                    no_change=True,
                    notices=_notices(parsed.notices),
                )

            candidate: dict[ListKind, RegexRuleFile | NameListFile | None] = {
                k: c.parsed for k, c in components.items()
            }
            candidate[kind] = parsed
            await self._refuse_unless_valid(candidate)

            row = await repo.find_list(kind, sha256)
            if row is None:
                row = ScrubList(
                    id=ScrubListId(self._ids.new_id()),
                    kind=kind,
                    filename=filename,
                    sha256=sha256,
                    imported_at=self._clock.now(),
                    entry_count=(
                        len(parsed.rules)
                        if isinstance(parsed, RegexRuleFile)
                        else len(parsed.entries)
                    ),
                    content_text=content.decode("utf-8"),
                    import_report_json=_dump_notices(parsed.notices),
                )
                await repo.add_list(row)
            # The screen reloads the active set next; it need not parse this again.
            _PARSED.put((kind, sha256), parsed)
            ids = {k: ScrubListId(c.row.id) for k, c in components.items()}
            ids[kind] = ScrubListId(row.id)
            ruleset = await self._add_version(repo, ids, candidate)
            components[kind] = _Component(row, parsed)
            return ScrubImportView(
                await _ruleset_view(ruleset, components),
                no_change=False,
                notices=_notices(parsed.notices),
            )

    async def remove_list(self, kind: ListKind) -> ScrubImportView:
        """Make version n+1 without this kind's file.

        Checked like an import: removing the whitelist can turn a protected
        string into a placeholder, and that is refused.

        :raises ScrubImportRefusedError: the set without it fails a check.
        """
        async with session_scope(self._session_factory) as session:
            repo = ScrubRepository(session)
            active = await repo.get_active()
            components = await _components(repo, active)
            if kind not in components:
                return ScrubImportView(await _ruleset_view(active, components), no_change=True)
            del components[kind]
            candidate: dict[ListKind, RegexRuleFile | NameListFile | None] = {
                k: c.parsed for k, c in components.items()
            }
            await self._refuse_unless_valid(candidate)
            ids = {k: ScrubListId(c.row.id) for k, c in components.items()}
            ruleset = await self._add_version(repo, ids, candidate)
            return ScrubImportView(await _ruleset_view(ruleset, components), no_change=False)

    @staticmethod
    async def _refuse_unless_valid(
        candidate: Mapping[ListKind, RegexRuleFile | NameListFile | None],
    ) -> None:
        errors: list[ScrubImportError] = await asyncio.to_thread(check_rules, _compose(candidate))
        if errors:
            raise ScrubImportRefusedError(errors)

    async def _add_version(
        self,
        repo: ScrubRepository,
        ids: Mapping[ListKind, ScrubListId],
        candidate: Mapping[ListKind, RegexRuleFile | NameListFile | None],
    ) -> ScrubRuleset:
        ruleset = ScrubRuleset(
            id=ScrubRulesetId(self._ids.new_id()),
            version=await repo.next_version(),
            created_at=self._clock.now(),
            fingerprint=await asyncio.to_thread(
                compute_rules_fingerprint, _compose(candidate, mandatory=False)
            ),
            **{column: ids.get(kind) for kind, column in _COMPONENT_COLUMNS.items()},
        )
        await repo.add_ruleset(ruleset)
        return ruleset

    # --- reads -------------------------------------------------------------

    async def active(self) -> ScrubRulesetView:
        """What the next freeze applies. Never empty: with nothing imported,
        the mandatory rules."""
        async with self._session_factory() as session:
            repo = ScrubRepository(session)
            ruleset = await repo.get_active()
            return await _ruleset_view(ruleset, await _components(repo, ruleset))

    async def versions(self) -> list[ScrubVersionView]:
        """Every version, newest first, with the corpora frozen under it."""
        async with self._session_factory() as session:
            repo = ScrubRepository(session)
            counts = await repo.corpus_counts()
            views: list[ScrubVersionView] = []
            for ruleset in await repo.list_rulesets():
                components: dict[str, str] = {}
                for kind, column in _COMPONENT_COLUMNS.items():
                    list_id = getattr(ruleset, column)
                    row = await repo.get_list(list_id) if list_id else None
                    if row is not None:
                        components[kind.value] = row.filename
                views.append(
                    ScrubVersionView(
                        ruleset_id=ScrubRulesetId(ruleset.id),
                        version=ruleset.version,
                        created_at=ruleset.created_at,
                        fingerprint=ruleset.fingerprint,
                        components=components,
                        corpus_count=counts.get(ScrubRulesetId(ruleset.id), 0),
                    )
                )
            return views

    async def entries(
        self, kind: ListKind, *, query: str = "", page: int = 1, page_size: int = 50
    ) -> Page[ScrubEntryView]:
        """The active list of `kind`, searched the way the scrubber compares:
        `müll` finds `Müller` and `Mueller` alike. File order, paged."""
        async with self._session_factory() as session:
            repo = ScrubRepository(session)
            component = (await _components(repo, await repo.get_active())).get(kind)
        entries = (
            component.parsed.entries
            if component and isinstance(component.parsed, NameListFile)
            else ()
        )
        matching = await asyncio.to_thread(search_entries, entries, query)
        start = max(page - 1, 0) * page_size
        return Page(
            items=tuple(
                ScrubEntryView(e, entry_key(e)) for e in matching[start : start + page_size]
            ),
            total=len(matching),
            page=page,
            page_size=page_size,
            sort_key="file_order",
            sort_dir=SortDir.ASC,
        )

    async def try_text(self, text: str) -> ScrubTryView:
        """The active rules over one sentence. Nothing is stored, and nothing
        is logged: the sentence may be real narrative typed in to test."""
        async with self._session_factory() as session:
            loaded = await load_scrub_rules(session)
        scrubber = await compile_scrubber(loaded.rules)
        try:
            result = await asyncio.to_thread(scrubber.scrub, text)
        except ScrubTimeoutError as exc:
            return ScrubTryView(text="", hits=(), timed_out_rule=exc.rule_id)
        return ScrubTryView(
            text=result.text,
            hits=tuple(
                ScrubHitView(h.rule_id, h.tag, h.placeholder, h.start, h.end) for h in result.hits
            ),
        )
