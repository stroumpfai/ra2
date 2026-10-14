# Amendment: `fix-evaluation-model-tick` (SD56)

> **APPLIED in the same commit**, as the other post-phase slices were. No
> wave is running. **No schema change, no migration, no API change.**

Reported from `just dev` on a CPU-only host, right after `SD55`: the model list
was slow to react to a tick or an untick, and the Ollama connection looked
unstable. The endpoint was healthy. `/api/tags` answers in 1.3–1.9 s there and
`/api/show` in 0.7–1.4 s, during a CPU generation too, all well inside
`PROBE_TIMEOUT_S`. The view asked it three times per tick (the VRAM judgement,
then the reload's catalogue and every `/api/show`) and rebuilt the setup column
twice, the second time 2–3 s after the first. And because the view sent the
whole selection worked out from its last read, an older read could put back a
model the analyst had just changed.

Decided with the project owner: recommendations 1 and 2 of the diagnosis. The
endpoint is asked only when its answer can change, and a tick sends one model
and its state, written under a lock. `sw-design.md` `SD56` has the reasoning
and what was rejected.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/services/evaluation_service.py` | + `select_model(evaluation_id, tag, *, selected) -> EvaluationDraftView`. Additive: no existing signature changes. The constructor's signature is unchanged; its body adds `_draft_lock`, which `update_draft` takes too. `update_draft` now judges `selected_models` **before** its transaction opens rather than inside it (§15.3). `_reject_infeasible` asks NVML first and returns when no VRAM is known |
| `ra2/ui/views/evaluation_view.py` | + `redraw()`, `_PROMPT_FIELDS`, `_persist`, `_ask`. `_toggle_model(choice)` calls `select_model`. `_load_seq` becomes `_local_seq` (database reads, the progress timer's included) and `_endpoint_seq` (asks), plus `_asking` and `_full_pending`. `_read_local` reads into locals and paints only if it still owns the screen. An endpoint answer equal to what the setup column was painted from (`_painted`) rebuilds nothing, so a click is not dropped by a column being replaced under it. `refresh_progress`'s fallback is `redraw`, never a read that asks |

```diff
# ra2/services/evaluation_service.py
+    async def select_model(
+        self, evaluation_id: EvaluationId, tag: str, *, selected: bool
+    ) -> EvaluationDraftView:
```

The API keeps `update_draft(selected_models=...)`: a client that sends a whole
list means the whole list. `select_model` is not exposed over HTTP, and the
OpenAPI snapshot is unchanged.

## Not frozen, changed

| Path | What |
|---|---|
| `sw-design.md` | `SD56` |
| `CONTRACTS.md` | Two rows beside `SD55`'s |
| `tests/e2e/test_j10_evaluation.py` | `_redrawn`'s comment: a redraw paints once and leaves `data-loading` `false`. The wait itself is unchanged and holds for both. `_select_model` waits for `data-loading="false"` before it clicks: the tick after *New evaluation* failed one run in two **on the previous view too**, a click dropped by the endpoint half's repaint. Now 5 of 5 |

## Tests

| Layer | File | What |
|---|---|---|
| backend | `tests/backend/services/evaluation/test_select_model.py` *(new)* | Adds one and keeps the rest in order; removes one; sets the state rather than flipping it; two clicks in flight both land (**fails without `_draft_lock`**, which loses a model); an untick asks the endpoint nothing; with no VRAM known, neither a tick nor `update_draft` asks anything (**hangs on the held gate without the NVML-first check**); an oversized model is refused and nothing changes; a launched evaluation refuses both |
| ui | `tests/ui/test_evaluation_view.py` | `test_a_tick_asks_the_endpoint_only_to_judge_it`, `test_only_a_step_that_moves_the_longest_prompt_asks_the_endpoint_again`, `test_a_tick_on_a_stale_screen_keeps_the_model_another_tab_ticked`. **All three fail against the previous view**: a load left out after the tick, a held read that never answered, and "Launch 1 run" where two were selected |

Not covered by a dedicated test: the progress timer dropping a read that a
newer one overtook. The user-visible consequence (an older read undoing a tick)
is covered by the stale-screen test through `select_model`. Driving the timer
into that window would need a gate inside a database read.
