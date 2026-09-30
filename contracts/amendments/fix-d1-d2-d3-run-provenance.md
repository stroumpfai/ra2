# Amendment: `fix-d1-d2-d3-run-provenance` (risks D1, D2, D3)

> **APPLIED in the same commit**, as the other risk slices were. No wave is
> running. **One schema change**, revision `b4f2c81e6d37`: three nullable
> `run` columns, no backfill.

`risk-assesment.md` §5 rows **6**, **7** and **8**, all Gate 1.

| Row | Asked for | State before this commit |
|---|---|---|
| 6 · D1 | Record the context length on the run; flag any extraction whose returned `prompt_tokens` sits at or near the limit | No context was sent, asked for or recorded. `/api/show` was never called. `prompt_tokens` was stored and compared with nothing |
| 7 · D2 | Carry the parse-failure rate onto Results and Ranking | It was counted on the run's progress card and nowhere else |
| 8 · D3 | Record the model-server version and decoding options on the run; state the determinism caveat in the report template | The version was asked only when a parallel-calls entry applied, and was never stored. Server-side options were not read. No report template existed, and the design's step-5 note said "Same inputs, same output" |

Decisions taken with the project owner before building:
- **The context recorded is the loaded one**, read from `/api/ps` after the
  first record, so it is whatever the server applied.
- **At the limit means ≥ 95 %** of that context.
- **Both figures are shown on the Ranking** (a column) **and on Results**
  (under each model's column header).
- **The caveat goes in a new template document and in the app**: the
  reproducibility card and the ranking footer.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/domain/llm.py` | `ModelCatalog` gains `parameters(tag)` (`/api/show`) and `context_length(tag)` (`/api/ps`). Both never raise and answer `None` when the endpoint does not say. Also `CONTEXT_LIMIT_SHARE = 0.95` and `at_context_limit(prompt_tokens, context_length)`, the one statement of the threshold |
| `ra2/persistence/models.py` | + `Run.ollama_version` (String 64), `Run.server_parameters_json` (Text), `Run.context_length` (int), all nullable |
| `ra2/services/readmodels.py` | + `ReadingQuality`; + `quality` on `ModelColumnView` and `RankingRow`; + `ollama_version`, `server_parameters`, `context_length` on `ProvenanceView`. All defaulted, so every existing constructor still builds |
| `ra2/api/schemas.py` | + `ReadingQualityResponse`; + `quality` on `ModelColumnResponse` and `RankingRowResponse`; + the three provenance fields on `ProvenanceResponse`. All optional. `tests/api/openapi_snapshot.json` is regenerated: 112 lines added, none removed |
| `tests/test_p5_contract.py` | `b4f2c81e6d37` registered in `POST_PHASE_5_REVISIONS` |

```diff
# ra2/domain/llm.py — ModelCatalog
+    async def parameters(self, tag: str) -> Mapping[str, tuple[str, ...]] | None: ...
+    async def context_length(self, tag: str) -> int | None: ...
```

Every implementation of the protocol is updated in this commit:
- `OllamaModelCatalog`;
- `OllamaConnection` (`infra/connection.py`), which delegates;
- `StaticModelCatalog` (`tests/fixtures/fake_llm.py`), with `parameters=` and
  `context_lengths=` constructor arguments and call counters.

## The migration

`20260930_0900_b4f2c81e6d37_pin_what_the_digest_does_not.py` is written by
hand, since `just revision` autogenerates against `./var`. It adds three
nullable columns with no backfill, for `9874691cc8eb`'s reason: a value
written for an earlier run would be a number nobody measured. Such a run
reads `unknown` on the card, and its at-limit count is *not recorded*, never
`0`.

## Behaviour changes worth naming

- **The launch asks for the Ollama version every time.** It used to ask only
  when a parallel-calls entry applied. That is one call per launch, not per
  record. `test_launch_gate.py::…without_a_gate…` asserted zero calls and now
  asserts one; the decision it guards (the run is not made parallel) is
  unchanged.
- **The launch asks `/api/show` once per selected model**, before the
  transaction, in a short read session of its own. A model refused inside the
  transaction costs one wasted call, which is cheaper than holding a
  transaction open across a socket.
- **The worker asks `/api/ps` once per run, after the first committed
  record**, and writes `run.context_length` only while it is `NULL`. A
  resumed run keeps its first reading. `RunService` takes an optional
  `model_catalog`, wired in `main.py`; without one nothing is asked.
- **The step-5 determinism note** changes from "Same inputs, same output" to
  "nearly always the same output … though GPU inference is not
  bit-identical". The design README changed first, marked as amended by
  `SD48`.

## Not frozen, changed

| Path | What |
|---|---|
| `ra2/infra/ollama_client.py` | `_NATIVE_SHOW_PATH`, `_OllamaShow`, `parse_parameters` (every value kept verbatim and in order, since `stop` repeats), `context_length` on `_OllamaTag` |
| `ra2/infra/connection.py` | Delegates the two new methods |
| `ra2/services/evaluation_service.py` | Pins the version and each model's options on the run; `ProvenanceView` carries them |
| `ra2/services/run_service.py` | `_pin_context_length` after the first record; `_RunPlan.context_pinned`; `_RecordLoop.context_asked` |
| `ra2/persistence/repositories/run_repo.py` | `pin_context_length` (only while `NULL`); `prompt_tokens` |
| `ra2/services/run_descriptor.py` | `reading_quality`, `model_column`: the one helper both boards use |
| `ra2/services/{results,ranking}_service.py` | Attach `ReadingQuality` |
| `ra2/api/v1/{results,ranking,evaluations}.py` | Map the fields: `quality_response` and `model_column_response`, shared |
| `ra2/ui/views/results/chrome.py` | `QUALITY_TITLE`, `CONTEXT_NOT_RECORDED`, `quality_text`, `DETERMINISM_CAVEAT` |
| `ra2/ui/views/results/extraction_tab.py` | A quality line under each model's header |
| `ra2/ui/views/results/ranking_tab.py` | An **Unreadable** column (120 px, so the table min-width goes 978 → 1098), and the caveat under the validity footer |
| `ra2/ui/views/evaluation_view.py` | `ollama`, `server options`, `context` on the provenance line; the caveat on the card; `DETERMINISM_NOTE` amended |
| `design/prompt-evaluation/README.md` | Step 5's note, amended (`SD48`) |
| `docs/evaluation-report-template.md` *(new)* | The report skeleton: what to copy from which screen, the reading-quality table, the caveat verbatim |
| `mvp-spec.md` | §9 (what a run stores, and that it is necessary not sufficient), §11.5 (unreadable and at-limit reported, never scored), §19 item 8 |
| `sw-design.md` | `SD48`; §15.8 names *who sets the context size* as still undecided |
| `README.md` | *At a glance* → Results; documentation map |

## Tests

| Layer | File | What |
|---|---|---|
| unit | `tests/unit/llm/test_context_limit.py` | 95 % boundary on both sides; an unknown is never flagged |
| backend | `tests/backend/infra/test_ollama_client.py` | `/api/show` parsed, `{}` against `None`, unreachable; `/api/ps` context read by tag, `None` when not loaded, not reported, zero or unreachable; `parse_parameters` |
| backend | `tests/backend/services/evaluation/test_launch.py` | Version and per-model options pinned; context not asked at launch; `ProvenanceView` carries all three |
| backend | `tests/backend/services/run/test_context_length.py` | Pinned after the first record and asked once; not reported stays `NULL`; a resumed run keeps its reading and does not ask; no catalogue, no call |
| backend | `tests/backend/services/ranking/test_reading_quality.py` | Two unreadable answers and three at-limit prompts per run counted on both boards, identically; an unrecorded context is `None`, never `0` |
| UI | `tests/ui/test_results_view.py`, `test_evaluation_view.py` | The header line, the ranking column, the caveat under the ranking, `quality_text`'s unknowns; the provenance line's `unknown`s and the card's caveat |
| root | `tests/test_report_template_caveat.py` | The template quotes `DETERMINISM_CAVEAT` verbatim |

`tests/fixtures/scored_corpus.py` gains `context_length`,
`unreadable_records` and `long_prompt_records`, all off by default. The
fixture's existing scores are unchanged.

## What I did instead of a shim

Nothing. The amendment is applied in this commit.
