# Amendment: `fix-d1-launch-context-check` (risk D1, recommendation 2)

> **APPLIED in the same commit**, as the other risk slices were. No wave is
> running. **No schema change.**

`risk-assesment.md` D1's second recommendation, and §1's first-pass row 5:
*"Validate at evaluation setup: estimate the prompt for the corpus's longest
narrative and refuse to launch, or warn loudly, above a configured budget."*
Before this commit, `SD48` flagged truncation after a run and nothing checked
before one.

Decisions taken with the project owner before building:
- **Refuse the model, like VRAM.** It is marked on the Models card and
  refused at launch. An unknown context never refuses.
- **The context source:** measured on this host for the same tag and digest,
  else the Modelfile's `num_ctx`, else *cannot check*. Never the trained
  maximum.
- **The margin:** prompt + 1 024 answer tokens ≤ 90 % of the context.
- **The record:** the longest narrative in the run's scope.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/services/readmodels.py` | + `ModelChoiceView.context_fit: ContextFit \| None = None`, + `ModelChoiceView.context_too_small`. `disabled` now covers both refusals: `fits_vram is False or context_too_small`. Defaulted, so every constructor still builds |
| `ra2/api/schemas.py` | + `context_fits`, `context_length`, `context_source` and `context_needed_tokens` on `ModelChoiceResponse`, all optional. `tests/api/openapi_snapshot.json` is regenerated: 44 lines added, none removed |

```diff
# ra2/services/readmodels.py — ModelChoiceView
+    context_fit: ContextFit | None = None
+
+    @property
+    def context_too_small(self) -> bool:
+        return self.context_fit is not None and self.context_fit.fits is False
+
     @property
     def disabled(self) -> bool:
-        return self.fits_vram is False
+        return self.fits_vram is False or self.context_too_small
```

## Not frozen, changed

| Path | What |
|---|---|
| `ra2/domain/context_fit.py` *(new)* | `ContextFit` (with `needed_tokens` and `fits`, where `None` means *cannot check*), `ContextSource`, `ANSWER_RESERVE_TOKENS`, `LAUNCH_CONTEXT_SHARE`, `modelfile_context` |
| `ra2/services/evaluation_service.py` | A defaulted `prompt_preview` constructor argument (a private structural protocol, so the module never imports `prompt_service`). `_with_context_fit` runs on a fresh catalogue in `get()` and again in `launch()`, the latter from the launch's own `/api/show` answers. `_longest_prompt_estimate` covers the Dev scope or the whole corpus. `_measured_contexts` reads the latest run per tag and digest. `EVAL_ERROR_CONTEXT_TOO_SMALL` and `_exceeds_context` give the refusal |
| `ra2/main.py` | `prompt_preview=prompt_service` |
| `ra2/api/v1/evaluations.py` | Maps the four fields |
| `ra2/ui/views/evaluation_view.py` | **No extra line per row**: the design's 260px well holds four rows, and E2E J10 asserts it. A context refusal replaces the size line, as the VRAM refusal does (`context 512 (Modelfile) — too small for ≈ 1 400`). The row carries `data-context` (`fits`, `too-small`, `unknown` or `none`). One summary line under the card gives the estimate and how many models' contexts are known. `CONTEXT_TOOLTIP`, `CONTEXT_UNKNOWN` |
| `README.md` | *Context and the longest prompt* |
| `mvp-spec.md` | §19 item 9; a *what* change |
| `sw-design.md` | `SD53`, and §15.8's context bullet |
| `docs/risk-assesment.md` | §1 row 5, §5's Gate 1 note, §8.15 |

## Tests

| Layer | File | What |
|---|---|---|
| unit | `tests/unit/context_fit/test_context_fit.py` | The 90 % boundary on both sides; the answer reserve deciding a case the prompt alone would pass; an unknown side never refuses; `num_ctx` parsing (the last value wins, a non-integer or zero is no context) |
| backend | `tests/backend/services/evaluation/test_context_check.py` | A Modelfile context of 512: disabled, refused at launch with the exact message, no run written. 8192: fits and launches. Unknown: launches. A measured context beats the Modelfile. The progress-timer path asks `/api/show` nothing |
| UI | `tests/ui/test_evaluation_view.py` | A too-small row is disabled, its size line in `--warn` naming the context and its source and not saying VRAM; a roomy row stays live; the summary counts the known contexts; an unknown context reads *cannot check* and leaves the row live |
| E2E | `tests/e2e/test_j10_evaluation.py` (unchanged) | Still asserts four rows in the 260px well. A first version of this change added a line per row and failed it, which is why the refusal moved into the size line |

## What I did instead of a shim

Nothing. The amendment is applied in this commit.
