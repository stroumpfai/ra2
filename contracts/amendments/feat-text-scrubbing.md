# Amendment: `feat/text-scrubbing` (SD62–SD66)

> **APPLIED in the same commit**, as the other post-phase slices were. No
> wave is running. **One schema change and one migration**
> (`5b93f1f9617a`, `scrub_list`, `scrub_ruleset` and three `corpus` columns),
> **one new router** (`/api/v1/scrub`), **one new runtime dependency**
> (`regex`), **one new import-linter contract**, **one new nav item**.

Narratives are scrubbed at freeze: personal data replaced by numbered
placeholders (`<Lastname_1>`, `<Phone_2>`), by regular expressions and name
lists, with no LLM. Mandatory rules (plates, phones, emails) are code; a rule
file and three name lists are imported on a new Scrubbing screen and
versioned. Only scrubbed text is stored. Decided with the project owner;
`plan-text-scrubbing.md` is the plan and `sw-design.md` §19 the design.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/domain/ids.py` | + `ScrubListId`, `ScrubRulesetId` |
| `ra2/domain/findings.py` | + `FindingCode.TEXT_SCRUBBED` (REPORTED) and `FindingCode.TEXT_SCRUB_TIMEOUT` (BLOCKING), both in `DEFAULT_SEVERITY`; the docstring's hazard range is `h01-h18` |
| `ra2/persistence/models.py` | + `ScrubList`, `ScrubRuleset`; + `Corpus.scrub_ruleset_id` (**not** a foreign key, see the migration), `.scrub_fingerprint`, `.scrub_mandatory_json`, all nullable; `ListKind` and the two id types in `type_annotation_map` |
| `ra2/services/corpus_service.py` | `freeze(…, scrub_ruleset_id: ScrubRulesetId \| None = None)`, keyword-only and defaulted, so every existing caller is unchanged; + `scrub_preview(delivery_id, *, scrub_ruleset_id=None) -> ScrubPreviewView`. Constructor unchanged |
| `ra2/services/delivery_service.py` | Body of `preview` only: each line scrubbed with the active rules, empty on a timeout |
| `ra2/services/readmodels.py` | + `ScrubRuleView`, `ScrubNoticeView`, `ScrubListView`, `ScrubRulesetView`, `ScrubVersionView`, `ScrubImportView`, `ScrubEntryView`, `ScrubCountView`, `ScrubPreviewView`, `ScrubHitView`, `ScrubTryView`; + `CorpusView.scrubbed` / `.scrub_version` / `.scrub_counts` and `RunDescriptorView.scrubbed` / `.scrub_version`, all defaulted |
| `ra2/services/errors.py` | + `ScrubImportRefusedError(import_errors)`, 422, nothing written |
| `ra2/services/container.py`, `ra2/main.py` | + `Services.scrub`, built from the session factory, clock and ids. Wiring only |
| `ra2/api/schemas.py` | + `ScrubCountResponse` and the `/api/v1/scrub` response models; + `CreateCorpusRequest.scrub_ruleset_id`; + `CorpusResponse.scrubbed` / `.scrub_version` / `.scrub_counts`. All additive; `tests/api/openapi_snapshot.json` regenerated, 938 lines added, the one "removed" line a trailing comma |
| `ra2/api/deps.py` | + `ScrubServiceDep` |
| `ra2/api/v1/router.py` | + `scrub.router` |
| `pyproject.toml`, `uv.lock` | + `regex>=2026.9.29` (runtime); + `types-regex` (dev, `.pyi` only) |
| `.importlinter` | + `regex-only-in-the-scrubber`; the header names `regex` for `domain/scrub.py` |
| `.gitignore` | + `**/scrub-lists/`, `*.names.txt` |
| `tests/test_p3_contract.py`, `test_p4_contract.py`, `test_p5_contract.py` | The eight-item nav, the pinned dependency list and the seven-contract count each subtract a named post-phase set (`POST_PHASE_5_NAV_KEYS`, `POST_PHASE_5_DEPENDENCIES`, `POST_PHASE_5_CONTRACTS`); the revision and the error join `POST_PHASE_5_REVISIONS` and `POST_PHASE_5_ERRORS` |

```diff
# ra2/services/corpus_service.py
     async def freeze(
         self,
         delivery_id: DeliveryId,
         *,
         name: str,
         description: str | None = None,
         synthetic: bool = False,
+        scrub_ruleset_id: ScrubRulesetId | None = None,
     ) -> CorpusId:
+    async def scrub_preview(
+        self, delivery_id: DeliveryId, *, scrub_ruleset_id: ScrubRulesetId | None = None
+    ) -> ScrubPreviewView:
```

```diff
# ra2/domain/findings.py
+    TEXT_SCRUBBED = "TEXT_SCRUBBED"
+    TEXT_SCRUB_TIMEOUT = "TEXT_SCRUB_TIMEOUT"
```

## The migration

`20261018_0900_5b93f1f9617a_scrub_the_narratives.py`, revising
`3ce2190bd859`: two new tables, three nullable `corpus` columns, no backfill.
A corpus that exists before it reads as *not scrubbed*, which is true.

**`corpus` is altered in place in both directions, never rebuilt.**
Migrations run with `foreign_keys=ON` inside a transaction, where
`PRAGMA foreign_keys=OFF` is a no-op, so batch mode's copy-drop-rename would
cascade through `record` and everything below it. Native `ADD COLUMN` /
`DROP COLUMN` never drop the table; that is also why `scrub_ruleset_id` is not
a foreign key (SQLite will not drop a column that carries one without a
rebuild). `tests/backend/persistence/test_scrub_migration.py` writes rows
first and asserts they survive the upgrade and the downgrade. Registered in
`POST_PHASE_5_REVISIONS`; one head.

## Why a nav item

The plan's Q9: the rules act on the data at freeze, and a privacy control
hidden in the Codelists screen is not one an analyst finds. Data, after
Codelists. `design/nav-import-census/README.md`'s nav table gains the row;
there is no design for the screen yet. J5 and J6 are parametrised over
`NAV_ITEMS`, so the route is covered for navigation and for no egress.

## Changed, not frozen

`ra2/ui/shell.py`, `ra2/ui/components/icons.py` (+ `SHIELD`),
`ra2/ui/views/{__init__,import_view,file_report_modal}.py`,
`ra2/ui/views/results/chrome.py`, `ra2/services/run_descriptor.py`,
`ra2/api/v1/corpora.py`, `scripts/seed_dev.py`,
`tests/fixtures/deliveries/generate_hazards.py` (+ h18),
`tests/fixtures/golden/import_report_hazards.json` (+ three zero-hit
`TEXT_SCRUBBED` rows, nothing else), `tests/ui/test_shell_nav.py` (nine items),
`tests/unit/parsing/test_hazards_h01_h12.py` (eighteen hazards).
