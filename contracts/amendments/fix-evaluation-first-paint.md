# Amendment: `fix-evaluation-first-paint` (SD55)

> **APPLIED in the same commit**, as the other post-phase slices were. No
> wave is running. **No schema change, no migration.**

The Evaluation screen crashed under `just dev` with NiceGUI's *"The page took
longer than the response_timeout of 3.0 seconds to build"* whenever Ollama
was not running on Windows. Windows takes 2.02 s to refuse a connect to a
closed loopback port, and the page asked `/api/tags` twice in a row before
the page function returned, which took about 4 s. `plan-settings-in-the-app.md`
Stage 5 measured this first and recorded it as found but not fixed.

Decided with the project owner: all three of the proposed remedies, together.

1. The page function awaits `client.connected()` before anything reads.
2. A load paints its database half first and its endpoint half second.
3. What is asked is asked once and concurrently, under a short bound.

`sw-design.md` `SD55` has the reasoning and what was rejected.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/domain/llm.py` | + `EndpointStatus.UNCHECKED` ("not asked yet"). `ModelCatalog.reachable()` never returns it, it carries no reason, and it does not enable Launch. `tests/api/openapi_snapshot.json` regenerated: one enum value added to `EndpointStatus`, nothing removed. The API never returns it, because every API read probes |
| `ra2/services/evaluation_service.py` | Three **defaulted** keywords, so no caller changes: `get(..., probe=True)`, `connection_status(*, probe=True)`, `catalogue(evaluation_id=None)`. `probe=False` asks neither the endpoint nor the GPU. `catalogue(evaluation_id)` adds the context fit (SD53). Bodies: reachability and the catalogue are gathered (`_endpoint_state`), each model's `/api/show` is gathered in `_with_context_fit` and `_server_parameters`, and NVML runs in `asyncio.to_thread`. `_NO_REASON` replaces the `is REACHABLE` test |
| `ra2/ui/views/evaluation_view.py` | `frame()` (sync) + `await client.connected()` + `build()`. `reload()` = `_read_local()` then `_read_endpoint(seq)`. `_load_seq` drops an overtaken answer. `data-testid="evaluation-page"` with `data-loading`. `data-status` on the endpoint line. `ENDPOINT_WORDS[UNCHECKED] = "checking…"`, `NO_MODELS_CHECKING_MESSAGE`. `_forget_endpoint()` on Save and refresh. `refresh_progress` reads with `probe=False` and no longer falls back to a full reload for want of a connection |
| `tests/fixtures/fake_llm.py` | + `GatedModelCatalog`: a `StaticModelCatalog` whose `reachable`, `models` and `parameters` wait on per-method gates (`hold`/`answer`; not `release`, the protocol's unload verb), and which counts the calls waiting. Open by default |

```diff
# ra2/domain/llm.py — EndpointStatus
     REFUSED_NOT_LOOPBACK = "refused_not_loopback"
+    UNCHECKED = "unchecked"

# ra2/services/evaluation_service.py
-    async def get(self, evaluation_id, *, connection=None, models=None) -> EvaluationView:
+    async def get(self, evaluation_id, *, connection=None, models=None, probe=True) -> EvaluationView:
-    async def catalogue(self) -> CatalogueView:
+    async def catalogue(self, evaluation_id: EvaluationId | None = None) -> CatalogueView:
-    async def connection_status(self) -> ConnectionView:
+    async def connection_status(self, *, probe: bool = True) -> ConnectionView:
```

## Not frozen, changed

| Path | What |
|---|---|
| `ra2/infra/ollama_client.py` | `OllamaModelCatalog`'s client is built with `min(timeout_s, PROBE_TIMEOUT_S)`. `release` passes the configured timeout per request. `_fetch_tags` joins an `/api/tags` request already in flight (`asyncio.shield`, so a cancelled caller does not cancel it for the others), and the next call after it settles asks again |
| `sw-design.md` | `SD55` |
| `plan-settings-in-the-app.md` | Stage 5's *Found on the way* points at `SD55` |
| `tests/e2e/test_j10_evaluation.py` | `_open_evaluation` waits for `data-loading="false"`, and `_redrawn` waits for the endpoint half too. A reload now paints twice, so the first fresh element is not the last |

## Tests

| Layer | File | What |
|---|---|---|
| backend | `tests/backend/services/evaluation/test_first_paint.py` *(new)* | `probe=False` asks nothing and says `UNCHECKED` (with every read held, a read that asked would hang); paint-then-ask ends where one `get()` does; reachability and the catalogue are asked at once; every `/api/show` is asked at once |
| backend | `tests/backend/infra/test_ollama_client.py` | one `/api/tags` for a concurrent pair; a settled request is never reused; a cancelled caller does not cancel the shared request; reads are bounded by `PROBE_TIMEOUT_S`, `release` by the configured timeout; a configured timeout below the bound still wins |
| backend | `tests/backend/services/evaluation/test_models_and_connection.py` | `_CONNECTION_REASONS` covers every status but `REACHABLE` and `UNCHECKED` |
| ui | `tests/ui/test_evaluation_view.py` | `test_the_page_paints_before_the_endpoint_answers`, `test_a_fresh_install_paints_before_the_endpoint_answers`: with `/api/tags` held, the page opens and shows the database half with the endpoint unchecked and Launch shut, then completes having asked once. **Both fail against the previous view with `Expected status code 200, got 500`**, NiceGUI's timeout page, the reported crash. `_open_evaluation` replaces the bare `user.open`, and `_quiesce` also waits for a load in flight, which is the same connection-leak hazard as a poll tick |
| ui | `tests/ui/test_evaluation_results_link.py` | `_open_evaluation`, for the same reason |
