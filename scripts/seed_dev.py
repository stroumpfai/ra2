#!/usr/bin/env python
"""`just reset-seed` — land on a *working* state, not an empty one.

`reset_data.py` leaves a migrated, empty database, which is a state nobody can
do anything with: every screen in the app needs a corpus, and getting one means
six clicks and a delivery you have to find. This seeds one.

**It drives the services** — not raw SQL and not the ORM (§5). That is the
point of the script rather than an implementation detail:

- the seed cannot drift from the schema, because it goes through the same
  `DeliveryService.analyse` / `CorpusService.freeze` path the Import view does;
- it doubles as a smoke test of that path, on the real machine, with no test
  harness — a seed that fails is a defect in the import pipeline, and it says
  which step it failed on;
- nothing here is a second implementation of anything. `create_app(mount_ui=
  False)` builds the very same `Services` bundle the app serves from.

**Every byte it writes is synthetic.** The column *names* come from
`ra2.domain.parsing.headers` (as `tests/fixtures/deliveries/generate_hazards.py`
does, and for the same reason — a 67-column file stays 67 columns without
anyone counting); every value is invented here. Real data is gitignored, must
stay on the host, and must never be what a developer's seed leans on
(Do-NOT #11).

The delivery is **not clean**: it carries a declared-count mismatch and a
French record the upstream cp1252 conversion has already damaged. Both are
non-blocking, both show up in the import report, and a seed that produced a
spotless corpus would hide the two things this app exists to surface
(mvp-spec.md §15).

Run after a reset: `just reset-seed yes`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Final

from ra2.domain.delivery import FileKind, SourceKind
from ra2.domain.feature import Grain, Kind, MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.ids import CorpusId, DeliveryId
from ra2.domain.parsing.headers import (
    CANONICAL_COLUMN_SETS,
    OBJEKT_KEY_COLUMN,
    TEXT_KEY_COLUMN,
    TEXT_NARRATIVE_COLUMN,
    UNFALL_KEY_COLUMN,
)
from ra2.infra.config import Settings
from ra2.infra.idgen import Uuid7Factory
from ra2.infra.tasks import InlineTaskRunner
from ra2.main import create_app
from ra2.services.container import Services
from ra2.services.errors import ServiceError

#: `scripts/seed_dev.py` -> the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: The RADIS column vocabulary — index 0 of each kind's `ColumnSet`.
_RADIS: Final = {kind: sets[0] for kind, sets in CANONICAL_COLUMN_SETS.items()}

_CRLF: Final = "\r\n"
_STRUCTURED_DELIMITER: Final = "|"
_TEXT_DELIMITER: Final = ";"

#: How many accidents the seeded corpus holds. Deliberately dev-sized: the app
#: must mark it "smoke test, not a result" everywhere its numbers appear
#: (mvp-spec.md §9), and a seed that quietly looked like an evaluation corpus
#: would be teaching the wrong thing on day one.
RECORDS: Final = 12

#: Three narratives, so a seeded corpus is multilingual from the start —
#: per-record language detection is real work and a single-language seed never
#: exercises it.
#:
#: The French one is written **as the delivery really arrives**: `manœuvre`
#: has lost its `œ` and reads `manuvre`, while `é` and `è` are still there.
#: That asymmetry is the whole of mvp-spec.md §4.4 — the upstream
#: cp1252 -> Latin-1 conversion deletes only the characters Latin-1 does not
#: have, so a French corpus with accents intact and **zero** cp1252-only
#: characters is what proves the conversion happened.
_NARRATIVE_DE: Final = "Fahrzeug B1 bremste vor dem Kreisel, G1 fuhr auf. Leichter Sachschaden."
_NARRATIVE_FR: Final = "Le véhicule P a effectué une manuvre à gauche sur chaussée mouillée."
_NARRATIVE_IT: Final = "Il veicolo B1 non ha rispettato la precedenza all'incrocio."


def _uid(tag: str, number: int) -> str:
    """A 32-hex key — the shape the key-anchored recovery rule keys on."""
    return f"{tag}{number:0{32 - len(tag)}d}"


def _synthetic(column: str, index: int) -> str:
    """An invented value with the right *shape*.

    Shape matters because the census infers type hints from it (`Ausw` is a
    codelist, `Datum` is `YYYYMMDD`, `UnfZeitFeld` is `HH:MM`); content does
    not, and is nonsense on purpose.
    """
    if column.endswith("Uid"):
        return _uid("dd", index)
    if "Datum" in column or column.endswith("PruefungFeld") or column == "FahrzLetztePruefung":
        return "20250114"
    if column == "UnfZeitFeld":
        return "07:45"
    if column.endswith("Ausw"):
        return str(index % 9 + 1)
    if column.endswith("Feld"):
        return str(100 + index)
    if column.startswith("Ist"):
        return "0"
    return f"seed-{index}"


def _row(kind: FileKind, index: int, overrides: dict[str, str]) -> str:
    columns = _RADIS[kind].columns
    values = {c: _synthetic(c, index) for c in columns}
    values.update(overrides)
    return _STRUCTURED_DELIMITER.join(values[c] for c in columns)


def _table(kind: FileKind, rows: list[str]) -> str:
    header = _STRUCTURED_DELIMITER.join(_RADIS[kind].columns)
    return _CRLF.join([header, *rows]) + _CRLF


def delivery_files() -> dict[str, str]:
    """The four files of one small, deliberately imperfect delivery."""
    unfall_rows: list[str] = []
    objekt_rows: list[str] = []
    text_rows: list[tuple[str, str]] = []

    for index in range(RECORDS):
        unfall_key = _uid("a1", index)
        objekt_key = _uid("b2", index)
        narrative = (_NARRATIVE_DE, _NARRATIVE_FR, _NARRATIVE_IT)[index % 3]
        # The last record declares two objects and ships one: a count
        # mismatch, reported and non-blocking (mvp-spec.md §4.3).
        declared_objects = 2 if index == RECORDS - 1 else 1
        unfall_rows.append(
            _row(
                FileKind.UNFALL,
                index,
                {
                    UNFALL_KEY_COLUMN: unfall_key,
                    "KantonAusw": "380" if index % 2 else "381",
                    "AnzObjFeld": str(declared_objects),
                    "BeteiligtePersTotalFeld": "0",
                    # An all-empty column: 0 % populated in the census, and no
                    # denominator for any feature over it (§8.6).
                    "Witter0Ausw": "",
                },
            )
        )
        objekt_rows.append(
            _row(
                FileKind.OBJEKT,
                index,
                {OBJEKT_KEY_COLUMN: objekt_key, UNFALL_KEY_COLUMN: unfall_key},
            )
        )
        text_rows.append((unfall_key, narrative))

    header = _TEXT_DELIMITER.join((TEXT_KEY_COLUMN, TEXT_NARRATIVE_COLUMN))
    text = _CRLF.join([header, *(f"{k}{_TEXT_DELIMITER}{v}" for k, v in text_rows)]) + _CRLF
    return {
        "unfall.txt": _table(FileKind.UNFALL, unfall_rows),
        "objekt.txt": _table(FileKind.OBJEKT, objekt_rows),
        "text.csv": text,
    }


def write_delivery(root: Path) -> Path:
    """Write the files and return the directory they are in.

    `encoding="utf-8"` explicitly, like every file operation in this repo
    (N4) — and UTF-8 rather than cp1252 so the seeded corpus's canary count is
    the honest one for text that never went through the conversion.
    """
    root.mkdir(parents=True, exist_ok=True)
    for name, content in delivery_files().items():
        (root / name).write_text(content, encoding="utf-8", newline="")
    return root


async def seed(services: Services, *, delivery_root: Path) -> None:
    """Drive the services, in the order the Import view drives them."""
    delivery_id = await services.delivery.register(
        "seed delivery", source_kind=SourceKind.HOST_PATH, root_path=delivery_root
    )
    print(f"  delivery {delivery_id} registered from {delivery_root}")

    await services.delivery.analyse(delivery_id)
    view = await services.delivery.get(delivery_id)
    for file in view.files:
        print(f"    {file.filename}: {file.file_kind} · {file.encoding} · {file.row_count} rows")

    corpus_id = await _freeze(services, delivery_id)
    if corpus_id is None:
        return
    corpus = await services.corpus.get(corpus_id)
    print(
        f"  corpus {corpus_id} · {corpus.record_count} records · "
        f"dev-sized={corpus.is_dev_sized} · cp1252 canary={corpus.cp1252_canary_count}"
    )

    await _import_codelists(services)
    await _seed_features(services)
    await _seed_prompt(services)


async def _freeze(services: Services, delivery_id: DeliveryId) -> CorpusId | None:
    try:
        corpus_id = await services.corpus.freeze(delivery_id, name="seed corpus")
    except ServiceError as exc:
        # A blocked freeze is a **finding about the seed**, printed and not
        # swallowed: if this ever fails, the import pipeline changed and this
        # script is the cheapest place to have learned it (Do-NOT #6's spirit).
        print(f"  freeze refused: {exc}")
        return None
    return corpus_id


async def _import_codelists(services: Services) -> None:
    """Optional: `data/` is gitignored, so a fresh clone has no codelists.

    Skipping is printed rather than silent — a seeded corpus without code
    tables cannot carry an `enum` feature, and that is worth knowing before
    wondering why the Features view refuses one.
    """
    source = REPO_ROOT / "data" / "Codes" / "codes-2018.json"
    if not source.is_file():
        print(f"  codelists skipped: {source} is not here (data/ is gitignored)")
        return
    result = await services.codelist.import_file(source.name, source.read_bytes())
    print(f"  codelists imported: {result.attribute_count} attributes")


async def _seed_features(services: Services) -> None:
    """One labelled feature and one exploratory attribute — the smallest set
    that exercises both halves of the config (mvp-spec.md §19.4).

    No `enum` feature: that one needs a codelist mapping against a corpus, and
    the seed must work on a clone that has no `data/` (`_import_codelists`).
    """
    config = await services.feature.create_draft(name="seed features")
    config_id = config.feature_config_id
    await services.feature.add_feature(
        config_id,
        key="UnfZeitFeld",
        kind=Kind.LABELLED,
        description="The time of the accident, as the narrative states it.",
        grain=Grain.ACCIDENT,
        source_column="UnfZeitFeld",
        derivation=None,
        value_type=ValueType.TIME,
        matching_rule=MatchingRule(kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=5),
    )
    await services.feature.add_feature(
        config_id,
        key="phone_use",
        kind=Kind.EXPLORATORY,
        description="An explicit mention that a driver was using a phone.",
        grain=Grain.ACCIDENT,
        source_column=None,
        derivation=None,
        value_type=ValueType.FREE_TEXT,
        matching_rule=MatchingRule(kind=MatchingRuleKind.NONE),
    )
    try:
        frozen = await services.feature.freeze(config_id)
    except ServiceError as exc:
        print(f"  feature set left as a draft: {exc}")
        return
    print(f"  feature set {frozen.feature_config_id} frozen · {len(frozen.features)} features")


async def _seed_prompt(services: Services) -> None:
    source = (
        "You extract structured facts from Swiss accident reports.\n\n"
        "Language: {{language}}\n\n"
        "Read the narrative below. For each feature, emit only the value the\n"
        "narrative supports, and quote the span it came from.\n\n"
        "{{feature_block}}\n\n"
        "Answer as JSON only, one key per feature, no prose.\n\n"
        "--- narrative ---\n"
        "{{narrative}}\n"
    )
    template = await services.prompt.save_as_next_version(source)
    await services.prompt.activate(template.prompt_template_id)
    print(f"  prompt template v{template.version} saved and activated")


def main() -> int:
    settings = Settings()
    # `InlineTaskRunner` rather than the app's `AsyncioTaskRunner`: analysis
    # runs through the `TaskRunner` seam, and a script has no UI to poll
    # `GET /api/v1/tasks/{id}` from. Inline is the same work on the same seam,
    # finished before `submit()` returns — a composition-root choice, not a
    # branch inside anything (Do-NOT #12).
    app = create_app(
        settings=settings, task_runner=InlineTaskRunner(Uuid7Factory()), mount_ui=False
    )
    services: Services = app.state.services

    print(f"RA2_DATA_DIR: {settings.data_dir}")
    delivery_root = write_delivery(settings.data_dir / "seed")
    asyncio.run(seed(services, delivery_root=delivery_root))
    print("Seeded. Start the app with `just dev`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
