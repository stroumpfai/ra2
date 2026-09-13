# Amendments: `feat/p3-prompts-view`

> **BOTH APPLIED at Wave 4 integration.**
> **1** was resolved differently from the proposed diff: rather than flipping
> `assert prompts.built is False` to `is True`, the assertion was **removed**.
> `built` is wave sequencing, not a contract, and pinning either value leaves
> the same trap for L2 and for every view phase 4 adds. See commit
> "Stop the p3 contract test pinning a nav flag Wave 4 must change".
> **2** was applied as proposed, as `CorpusRepository.first_record_id` plus
> `CorpusService.first_record` — the query in the repository, which is where
> every other corpus query lives. `prompts_view._preview_inputs` now tries an
> evaluation first (all three inputs from one evaluation, which is the more
> faithful preview) and falls back to the newest corpus's first record, so
> Preview works on a fresh install. Covered by
> `test_preview_with_record_1_works_before_any_evaluation_exists`.

Two, independent of each other:

1. **`tests/test_p3_contract.py`** — `assert prompts.built is False` is the
   Wave-0 state, and plan-phase-3.md §6.1 tells L1 to change it. **Accepted
   and already fixed on `main`** — the lead removed the `built` assertion
   outright rather than flipping it (see "Status" under 1 below). It still
   fails in this worktree, which is based on `p3w3-green`.
2. **`ra2/services/corpus_service.py`** — give a `ui/` module a way to name
   "record 1" of a corpus, so "Preview with record 1" can mean what
   plan-phase-3.md C4 says it means. **Not blocking** — shimmed.

---

# 1. `tests/test_p3_contract.py` — the nav flag the §6.1 exception flips

## Which file

`tests/test_p3_contract.py`, `test_the_nav_has_eight_items_with_prompts_after_
features`, last line. Frozen and lead-owned (CONTRACTS.md: "this wave's exit
criteria as tests — lead-owned, frozen"; plan-phase-3.md §4's table marks it
🔒 in every wave).

## Why

plan-phase-3.md §6.1 declares the two-line nav exception and names it
explicitly: "**L1 and L2 may each edit exactly their own `built` flag and add
exactly their own line to `register_all`.**" This branch has done exactly
that, and the M17 assertion recording the pre-Wave-4 state now fails. The
frozen test even says so in its own comment:

```python
    #: Routed to `placeholder_view` until L1 flips this in Wave 4 (§6.1).
    assert prompts.built is False
```

So this is not a contract being broken — it is the one assertion that was
always going to need updating the moment Wave 4's declared exception was
used. It is raised as an amendment only because the file is frozen and the
line is not in this branch's owned paths.

## The exact proposed diff

```diff
--- a/tests/test_p3_contract.py
+++ b/tests/test_p3_contract.py
@@ def test_the_nav_has_eight_items_with_prompts_after_features():
     assert prompts.group == "Configure"
     assert prompts.path == "/prompts"
     assert prompts.label == "Prompts"
-    #: Routed to `placeholder_view` until L1 flips this in Wave 4 (§6.1).
-    assert prompts.built is False
+    #: Flipped by L1 in Wave 4 under the §6.1 two-line nav exception: the
+    #: route is `prompts_view`'s now, and `views.register_all` calls it.
+    assert prompts.built is True
```

`ra2/ui/views/prompts_view.py` keeps its `# STUB — bodies owned by L1 …`
first line, so `test_stub_module_carries_the_header` stays green — the same
convention `ra2/services/prompt_service.py` and `ra2/api/v1/prompt_templates
.py` already follow after their bodies landed.

## What I did instead

Nothing: there is no shim, and `pytest.mark.xfail` would itself be an edit to
the frozen file. The failure stands, alone, in this worktree:

```
FAILED tests/test_p3_contract.py::test_the_nav_has_eight_items_with_prompts_after_features
```

Everything else in that file (71 tests) passes, as does the rest of
`just test`.

## Status — resolved on `main`, and better than proposed

The lead accepted this and fixed it while this branch was in flight, but
**not** with the diff above: the `built` assertion was **removed entirely**
rather than flipped to `is True`. The reasoning is the right one and worth
recording here — `built` is wave sequencing, not a contract, so pinning
*either* value makes this frozen file need an amendment every time a view
lands, and Wave 4 lands two. What is contractual is the entry's identity and
position (still asserted here) plus the route resolving at all, which
`test_m0_contract.py`'s `NAV_ROUTES` asserts whether the view is built or
not. This worktree is based on `p3w3-green` and so still carries the old
assertion; the file is green on `main` and stays green once this branch's
flag flip merges. **No action needed from the lead on this item.**

---

# 2. `ra2/services/corpus_service.py` (and `ra2/services/readmodels.py`)

**Give a `ui/` module a way to name "record 1" of a corpus**, so the Prompts
view's "Preview with record 1" can resolve against *the active feature set and
the corpus's first record*, the way plan-phase-3.md C4 describes it.

**Not blocking.** This branch shipped a shim built entirely on existing frozen
surface; see "Status in this branch". Nothing is `xfail`ed.

## Which file

| File | Change |
|---|---|
| `ra2/services/corpus_service.py` | add one read-only method, `first_record` |

`ra2/services/prompt_service.py` is **not** touched: its signatures are frozen
(CONTRACTS.md, "constructor + typed signatures; bodies I1") and
`preview(template_id, feature_config_id, record_id, *, language)` is exactly
the right shape — it just needs a caller that can supply the third argument.

## Why

C4 settles design open question 5 with "one component, two entry points":
Evaluation's "Preview prompt" resolves against its own pinned inputs, and
**Prompts resolves against the active feature set and record 1**. The
Evaluation half works today — an evaluation knows its corpus, so
`EvaluationService.record_scope(evaluation_id)` hands L2 a record id.

The Prompts half has no such path. `PromptService.preview` requires a
`RecordId`, and **no read model reachable from `ui/` carries one**:

- `PromptTemplateView` — versions only;
- `CorpusView` — `record_count`, never a record id;
- `FeatureSetSummary` / `FeatureConfigView` — features only;
- `CensusColumnView` — column statistics.

`EvaluationService.record_scope` is the only method in the whole service layer
that returns a `RecordId`, and it requires an evaluation. A `ui/` module cannot
close the gap itself: it may not hold a session or touch an ORM object
(Do-NOT #7, enforced by `import-linter`'s "ui never touches a session, an ORM
object or an adapter" contract), and resolving a template without a service
would be `domain.prompt.resolve_template` called from `ui/` — business logic in
the view, the same rule's other half.

So the design's "record 1" is, today, unreachable from the Prompts view on its
own terms.

## The exact proposed diff

```diff
--- a/ra2/services/corpus_service.py
+++ b/ra2/services/corpus_service.py
@@
     async def summary(self) -> CorpusSummary:
         ...
+
+    async def first_record(self, corpus_id: CorpusId) -> RecordId | None:
+        """The corpus's first record **by id**, or `None` when it has none.
+
+        The design's "record 1" (`design/prompt-evaluation/README.md` §1,
+        plan-phase-3.md C4): the one record the Prompts view previews a
+        template against. Ordered by id, the same ordering
+        `EvaluationService._scope` uses, so "record 1" means the same record
+        in a preview and in a run — a preview that showed a different record
+        than the run would start on is worse than no preview.
+
+        :raises NotFoundError: no such corpus.
+        """
+        async with self._session_factory() as session:
+            await self._require(session, corpus_id)
+            stmt = (
+                select(Record.id)
+                .where(Record.corpus_id == corpus_id)
+                .order_by(Record.id)
+                .limit(1)
+            )
+            row = await session.scalar(stmt)
+            return None if row is None else RecordId(row)
```

(`Record` and `RecordId` are already imported in that module's neighbourhood;
`_require` is `corpus_service`'s own existing "or 404" helper.)

With it, `prompts_view._preview_inputs` becomes: the newest corpus
(`CorpusService.list_corpora`, already called by three other views), its first
record, and the newest feature set (`FeatureService.list_configs`) — no
evaluation required, and the preview reads exactly as C4 describes it.

An equally acceptable variant, if the lead prefers not to widen
`CorpusService`: add `first_record_id: RecordId | None` to `CorpusView`. That
is one extra `SELECT` per listed corpus, which is why the method is proposed
instead.

## What I did instead

`ra2/ui/views/prompts_view.py::_preview_inputs` takes the feature set, the
prompt language **and** the record from the **most recent evaluation**
(`EvaluationService.list_evaluations` + `record_scope`) — all three from one
evaluation, so they are guaranteed to belong together: `PromptService.preview`
resolves enum labels from *the record's own corpus*, and a feature set picked
independently of the record could be previewed against labels from a different
corpus entirely.

The shim is correct but narrower than the design: with no evaluation yet, the
Resolved card renders its (undesigned) empty state instead of a preview. Both
paths are covered — `tests/ui/test_prompts_view.py::
test_preview_with_record_1_hands_the_panel_a_resolved_prompt` and
`::test_preview_says_so_when_there_is_nothing_to_resolve_against`. Applying
this amendment means changing `_preview_inputs` and the second of those two
tests; nothing else in the view moves.
