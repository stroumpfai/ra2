# Amendment — `fix/ranking-token-format`

> **APPLIED in the same commit**, as `fix-b3-deletion-path` and its siblings
> were. No wave is running.

An audit of every performance metric the documents say is displayed against
what the code renders. One display defect, one false claim in a plan, one
stale sentence in `docs/performance.md`. **The fourth finding — the Ranking
tab's missing VRAM column — is not in this slice**; it needs a migration and
has its own plan, `plan-ranking-vram.md`.

| Planned | Rendered | Verdict |
|---|---|---|
| Progress card: done/total, elapsed, ETA, parse failures %, retries, median latency, prompt tok | all seven | ✓ |
| Models card third line: seed F1, s/rec, entities %, scope estimate, `parallel ×N`, three warn states | all six | ✓ |
| Reproducibility line: `parallel calls N` | ✓ | ✓ |
| Ranking: median latency with `×N`, time per record, presence rate | ✓ | ✓ |
| Ranking: prompt tokens as **"2.4 M tok"** (`design/results/README.md` §3b) | `f"{count}"` — `69000` | **§1** |
| `plan-model-choice.md` §9 Q4: the qualification's GPU name "shown on the card" | nowhere | **§2** |
| `docs/performance.md` §6: latency "comparable … while both ran serially, which today they always do" | SD38 shipped `×N` | **§3** |

---

## 1. `ra2/ui/components/primitives.py` — `+ format_tokens`

An **addition**, the mechanism the frozen list already sanctions for this file
(`primitives.py *(additions)*`, H5/S5/W2).

```diff
+def format_tokens(count: int) -> str:
+    """`2_100_000` -> `"2.1 M"`; `69_000` -> `"69 000"`. …"""
+    if count >= _TOKENS_PER_MILLION:
+        return f"{count / _TOKENS_PER_MILLION:.1f} M"
+    return format_count(count)
```

**Why it moves here rather than staying private.** The function already
existed, as `progress_card._format_tokens`, written to the design's
"2.1 M prompt tok". The Ranking tab's Prompt tokens column — added in phase 4
to the same design's "2.4 M tok" — rendered `f"{row.prompt_tokens}"` instead,
so the two places that print a token count printed it two ways, and the one on
the comparison table was the unformatted one. A 3 000-record run puts seven
unbroken digits in a 104px cell.

This is `format_duration_ms`'s precedent exactly (`feat-model-choice`, "so the
estimate and the ETA read alike"), one level further out: two *different*
components need it now, and `primitives` is where `format_count`,
`format_latency_ms` and `format_local` already state their one rule each. Both
call sites now import it; `progress_card`'s private copy is deleted, so there
is nothing left to drift.

**Why not `format_latency_ms`'s rule** (one unit down the whole column): that
rule exists because latencies on the Ranking tab are compared *against each
other*, and a unit switch mid-column would make them incommensurable. A token
count is a magnitude nobody subtracts, so the `M` switch costs a reader
nothing and saves them counting digits. The docstring says so, beside the
sentence in `format_latency_ms` that already draws the same line against
`format_duration_ms`.

## 2. `ra2/ui/components/progress_card.py` — one import, one deletion

```diff
-def _format_tokens(count: int) -> str:
-    ...
-            segments.append(f"{_format_tokens(progress.prompt_tokens)} prompt tok")
+            segments.append(f"{format_tokens(progress.prompt_tokens)} prompt tok")
```

No rendered output changes here. The metrics line reads as it did.

## 3. `ra2/ui/views/results/ranking_tab.py` — the cell uses it

```diff
-                        _td_mono(f"{row.prompt_tokens}")
+                        _td_mono(format_tokens(row.prompt_tokens), testid="prompt-tokens")
```

The `data-testid` is what lets the test assert the cell rather than scan every
descendant of the row for a string that happens to match, which is how the
latency assertion had to be written before there was one.

---

## 4. `plan-model-choice.md` §9 Q4 — a claim the code never made

The Q4 table's GPU-name row ended *"It's stored on the row and shown on the
card, and that's the right weight for it"*. It is stored on
`model_qualification`; **nothing renders it.** D7's own table of the card's
third line does not list it, `QualificationCardView` does not carry it, and
`sw-design.md` `SD40` says only "recorded, not compared" — so the plan is the
one document out of step, and the sentence is corrected rather than the code
extended. What the row argues (a name is not a calibration, an unknown name
cannot be compared) is untouched.

The card would be the wrong place for it anyway: it is the same value on every
row of one host, and the run's reproducibility line already carries the GPU an
evaluation actually ran on.

## 5. `docs/performance.md` §6 — a sentence SD38 made false

> **Latency is per call, not per run.** … It's comparable between runs only
> while both ran serially, **which today they always do**.

They do not: `RA2_LLM_PARALLEL_CALLS` plus a passing gate puts a run above 1,
which is what the `×N` mark and the Time / record column exist for — as §5.3
of the same page already describes. §6 now points at both instead of denying
the case. The header's revision note carries the date, per the page's own "re-
measure rather than edit" discipline; **no measured number changed.**

The VRAM bullet above it is left standing. It is still true, and
`plan-ranking-vram.md` is what closes it.

---

## Tests

| Test | Layer | What it pins |
|---|---|---|
| `test_the_ranking_token_column_groups_its_digits` | ui | The column renders `format_tokens` of the read model's own figure, and no cell holds a bare run of four digits. Fails on the old `f"{count}"` |

`tests/ui/test_components.py`'s progress-card cases already cover the
formatter's `M` branch (`prompt_tokens=1_500_000`) and are unchanged, which is
the check that moving the function changed no behaviour.
