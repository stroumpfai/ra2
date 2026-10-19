# Say what a refusal is, not how many

A defect with one UI-side fix. Status: **building** on `main`, from `47acfef`.
**No migration, no amendment, no contract change** — `FeatureValidationError`
already carries the sentences; the UI was not reading them.

---

## 1. What was reported

> Starting an evaluation, I got a "feature validation error" … we should
> improve this and give the user more details about what is going on and, if
> possible, a clear indication what to fix.

## 2. What exists

| # | Finding | Anchor |
|---|---|---|
| F1 | `FeatureValidationError.__str__` is `"N feature validation error(s)"`; the sentences are in `.validation_errors` | `services/errors.py:128-139` |
| F2 | Launch (and every other view handler) catches `ServiceError` and toasts `str(exc)` — the count, not the cause | `evaluation_view._launch`, 13 sites there, 36 across `ui/views/` |
| F3 | `_persist` already fixed this for draft edits and says why in a comment; the fix was local and never generalised | `evaluation_view.py:1979` |
| F4 | A launch can fail on several things at once (`_launch_models` collects one sentence per model; enum checks one per feature). A 4-second toast of joined sentences is unreadable | `evaluation_service.py:1209-1239`, `:1395-1411` |
| F5 | The service sentences are already written to name the repair ("no models are selected; a launch needs at least one.") | `evaluation_service.py:160-230` |

## 3. Design

**D1. One renderer.** `ui/components/refusal.py::refusal_text(exc)` returns the
sentences of a `FeatureValidationError` joined, and `str(exc)` for anything
else. Every `ui.notify(str(exc), …)` in `ui/views/` becomes
`ui.notify(refusal_text(exc), …)`.

**D2. A refusal with reasons is a dialog, not a toast.** `refusal_dialog(title,
reasons)` lists each reason on its own row and stays until dismissed. Launch
uses it for `FeatureValidationError`; a single-cause `ServiceError` (e.g. a
conflict) stays a toast. Parented to `_root`, opened with `.value = True`, like
the discard dialog.

**D3. A gate.** `tests/ui/test_no_bare_refusal_toast.py` parses `ra2/ui/` and
fails on any `ui.notify(str(<name>))`, so the next handler cannot reintroduce F2.

**Not here.** Stable codes with a "go to step N" target (needs a
`contracts/amendments/` file — `validation_errors` is frozen as `Sequence[str]`)
and a `launch_blockers` read model so most refusals never occur. Both are
follow-ups.

## 4. Stages

1. **Renderer + sweep + gate.** *Done when* no view toasts `str(exc)` and the
   gate is green.
2. **Launch dialog.** *Done when* a launch refused with two reasons shows both,
   on separate rows, in a dialog that is still there after the toast would have
   gone, and never contains "feature validation error".
3. `SD69` in `sw-design.md`; `just lint` and `just test`.
