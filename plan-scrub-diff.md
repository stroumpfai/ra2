# Show what the scrubbing preview would replace

A feature request, not a defect. Status: **built, in review** on `worktree-feat-scrub-diff`, from `543eb0f`.
**No migration and no API change** — the examples live in memory, in the
service's read model, and never reach the wire or the database.

---

## 1. What was asked

> Out of the Import view, the scrubbing preview gives a summary on what will
> happen. Further it would be useful to have the details of the changes as
> sometimes they are not expected. Can we add a diff for each placeholder if
> the user wants more details? The list of changes could be null, a few or
> very long depending on the input file.

Settled with the project owner before this was written:

| # | Question | Answer |
|---|---|---|
| 1 | The diff has to show original text. May the dry-run dialog show originals? | **Only the matched span.** The context around it is the *scrubbed* text |
| 2 | Keep the examples in memory, or store them to reopen later? | **In memory** — nothing stored |
| 3 | Purpose: find false positives, verify correctness, or both? | **Both** |
| 4 | An "Add to whitelist" action on a value? | **No** — the analyst edits the list by hand; keep it simple |
| 5 | Show what was *not* replaced (misses)? | **No** |
| 6 | A cap on the examples kept per placeholder? | **Fine** — counts stay exact |

## 2. What exists

| # | Finding | Anchor |
|---|---|---|
| F1 | The scrubber already returns every replacement as a `ScrubHit` with rule, tag, number and the span in the **original** text | `domain/scrub.py` `ScrubHit` |
| F2 | The dry run feeds each result to `ScrubCounter.add`, which keeps counts and discards the hits. The matched text is never read | `domain/scrub.py` `ScrubCounter` |
| F3 | The scrubbed text is built in one pass by `_replace`, which knows each placeholder's position in the **output**, and then forgets it | `domain/scrub.py` `_replace` |
| F4 | `ScrubPreviewView` is the dry run's read model; the API maps it field by field, so a new defaulted field changes neither the response nor the OpenAPI snapshot | `readmodels.py` `ScrubPreviewView`, `api/v1/scrub.py` `_preview_response` |
| F5 | The dialog is `_render_scrub_preview`: one row per rule, a most-hit line. No row is interactive | `import_view.py` |
| F6 | `scrub_preview` runs in a thread (`_dry_run`) over every narrative of the delivery: the example collection rides on that walk and adds no pass | `corpus_service.py` |
| F7 | SD62: the original text lives in the delivery files and nowhere else. A stored example would put a name into the database, which is why answer 2 is "in memory" | `sw-design.md` SD62 |

## 3. Design

**One read model, kept per rule, built during the walk that already exists.**

*What an example is.* A `ScrubExample`: the record key, the rule id and tag, the
placeholder (`<Lastname_1>`), the **matched span** as in the original, and a
window of about 40 characters either side taken from the **scrubbed** text.
So the row reads `…was driven by [Müller] → <Lastname_1> on the A1 near…` where
only the bracketed span is original, and everything else is already
replaced. The window comes from output coordinates (`ScrubHit.out_start`,
F3), not from the original text, which is what keeps a neighbouring name out of
the context.

*Per rule, two tiers:*

1. **Values.** Every distinct matched value, casefolded, with its exact count
   and the number of records. Held for every rule, up to **2 000 distinct
   values per rule**; past that, further new values are counted in a single
   `other_hits` count and not listed. Memory is bounded and the
   dialog says so (*"showing 2 000 of 31 540 values"*), never silently.
2. **Snippets.** Up to **3 snippets per value**, the first met. That is the
   "few examples" a reader needs to judge whether `Rose` is a name or a flower.

Totals per rule (`hits`, `records`) stay exact and keep coming from the
existing tally, so the table and the examples cannot disagree on a count. The
examples add to the tally; they do not replace it.

*The view.* `ScrubPreviewView.examples: tuple[ScrubRuleExamples, …]`, defaulted
`()`, each with `rule_id`, `values: tuple[ScrubValueExamples, …]` (sorted by
count, then value) and `other_hits`. Frozen dataclasses, no
behaviour. **Not on the API** (F4): `ScrubPreviewResponse` is unchanged, because
the examples are personal data and the only reader is the dialog.

*The dialog.* Each placeholder row in the existing table becomes expandable.

| State | What shows |
|---|---|
| 0 hits | Not expandable, no chevron. The `0` already says it |
| 1–20 values | Expanded inline: one line per value, `Müller → <Lastname_n> · 14× · 9 records`, then its snippets under it |
| More | The first 25 values, and **Show more** (adds 100 at a time). A text box filters the values by substring, so a suspicion ("is `Bern` replaced?") is one keystroke |
| Over the 2 000 cap | The honest line above the list |

A value row is a *group*, the snippets are its evidence: the group answers "what
is being replaced", the snippet answers "why, and in what sentence". Sorting by
count puts the unexpected common word (`Rose`, `Post`) at the top, which is the
false-positive case; the filter and the snippets serve verification.

*Where the work is done.* `ScrubCounter` collects the examples (it already sees
each `ScrubResult`), so it stays the one place that adds up a dry run. A freeze
**does not** collect them: `_scrub_record` takes the counter, and a freeze
builds one with `collect_examples=False`, so the stored corpus path pays
nothing and the freeze's counts are byte-for-byte what they were.

*Rejected:* a full side-by-side record view (heavy; answer 3 is met by the
snippet); storing examples so the preview can be reopened (F7, answer 2);
sampling the first N hits of the file, which shows only the first canton; an
"Add to whitelist" action (answer 4); an "export all" CSV (it would write
originals to disk, which answer 1 declines to do); showing misses (answer 5).

## 4. Stages

### Stage 1 — domain: the scrubber keeps where the placeholder landed

`ScrubHit.out_start` (defaulted `0`, so existing constructions stand), set by
`_replace`. `ScrubCounter(scrubber, *, collect_examples=False)` collects a
`ScrubExample` per hit when asked. `ScrubTally` gains `examples`, defaulted `()`.

**Done when:** `tests/unit/scrub` shows (a) the context is cut from the
scrubbed text, so a second name beside the first appears as its placeholder,
never as itself; (b) the matched span is the original, including a
transliterated one (`MUELLER` for `Müller`); (c) three snippets per value and a
fourth is counted but not kept; (d) at 2 001 distinct values the 2 001st lands
in `other_*`; (e) with collection off the tally is identical to today's; (f) a
hit at the very start and end of a text gives a window with no crash and no
padding.

### Stage 2 — service: the view carries them

`ScrubPreviewView.examples`; `_dry_run` builds its counter with collection on;
`freeze` does not.

**Done when:** `tests/backend` has the preview over a synthetic delivery with
the hazards (mixed encoding, an embedded newline, an orphan key) showing
examples whose total equals `counts` for every rule; and the same delivery
frozen, asserting the `TEXT_SCRUBBED` findings are unchanged (Do-NOT #2 holds:
nothing is written either way).

### Stage 3 — the API does not move

No code. A test pins `ScrubPreviewResponse` as it is and the OpenAPI snapshot
as it is.

**Done when:** `tests/api` is green with no snapshot regeneration. This is a
guard that a later "just add it to the response" has to break on purpose.

### Stage 4 — the dialog

Expandable rows, the value list with paging and the filter, the cap line.
Snippet text is user data, so props go through `data_props` (SD34). The
snippet's matched span is rendered as its own element, not by string surgery on
HTML, so a record containing `<` or `&` cannot break the row (the placeholders
themselves are `<…>`).

**Done when:** `tests/ui` shows (a) a zero-hit row has no toggle; (b) a rule
with 3 values is expanded and lists all of them; (c) with 60 values it lists 25,
**Show more** lists 100 more, and the filter narrows to the matching value;
(d) the cap line shows when the view says `other_hits > 0`, and a filter that finds nothing then says the value may be unlisted; (e) a snippet with
`<`, `&` and a newline renders as text; (f) the dialog still has its single
**Create corpus with these rules** button and the freeze reads the same
name/description state (SD68).

### Stage 5 — end to end, and the design note

One Playwright journey: preview a delivery that has a plate and a name, expand
`<LicensePlate_n>`, see the plate in the list with its snippet. `sw-design.md`
gets `SD70` and a line in §19.7 in the same commit as Stage 4.

**Done when:** it is green in `just e2e`, and `just lint` and `just test` pass.

### Stage 6 — code review

Before the branch is offered for merge, `/code-review` runs on the whole diff
against `543eb0f`, at least at `high`, and its findings are dealt with here:
fixed, or answered in §7 with the reason they stand. The review is asked
specifically about: (a) any path by which an original span or a snippet reaches
a log, a `Finding.detail`, the API or the database (§6); (b) the layer rule and
Do-NOT #7/#8 in the dialog; (c) whether the freeze's counts and stored findings
are unchanged; (d) the ownership rule, from `git diff --name-only`.

**Done when:** the review has been run, every finding is fixed or answered in
§7, and `just lint` and `just test` pass after the fixes.

## 5. Contracts and amendments

None frozen is touched: `ScrubPreviewView` and `ScrubHit` are not in
`CONTRACTS.md`'s frozen lists, and every new field is defaulted. `ScrubTally`
and `ScrubCounter` are `feat-text-scrubbing`'s; the changes are additive and
named in the commit.

`sw-design.md`: **SD70**, *the scrubbing preview shows what it replaced, from
memory: the matched span original, its context scrubbed, per rule a bounded
list of values with up to three snippets, and none of it on the API or in the
database.*

## 6. Risks worth stating

- **The span on screen is personal data.** That is what answer 1 accepts: names,
  plates, phone numbers and e-mails, in the analyst's own browser, on the
  loopback host, for the length of the dialog. Nothing is logged: the examples
  never enter a `Finding.detail` and the dialog must not `print`. A test greps
  the preview's log output for a planted value.
- **The context can still contain what the scrubber missed.** The window is the
  *scrubbed* text, so it is exactly as clean as the corpus would be, no cleaner.
  That is the raw preview's existing property (§8.3), and is arguably a feature
  here: a missed name next to a hit is visible.
- **Memory.** Worst case is 2 000 values × (3 snippets × ~120 characters) per
  rule, a few MB, released when the dialog closes. A page holds one preview, in
  `app.storage.client` (Do-NOT #8), and a new preview replaces it.
- **Dry run time.** Collection adds a dict update per hit to a walk that is
  already seconds of CPU; measured in Stage 2 against the existing preview
  test's delivery, and the number goes in §7.

## 7. Where reality differed

- **Worktree base.** `EnterWorktree` branched from `origin`'s default, which
  was behind local `main` and lacked this plan's neighbours; the branch was
  reset to `main` before any change.
- **The span is not on the hit.** `ScrubHit` got only `out_start`. `matched`
  was first added to it too and the review caught that a freeze, which never
  collects, would then copy every personal span onto every hit; the counter now
  slices it from the original the caller passes to `add`.
- **Examples ride the view as domain types.** `ScrubPreviewView.examples` holds
  `ScrubRuleExamples` directly instead of a parallel set of view classes; the
  view layer may import `domain`, and a copy would add a mapping with nothing in it.
- **Value key.** The scrubber's own: a list entry's key, or the match without
  its separators, so what shares a `<Phone_1>` shares a row. First spelling met
  is the one shown.
- **Stage 3 is a test line**, not a stage of work: `assert "examples" not in`
  the preview response, beside the existing agreement test; the OpenAPI
  snapshot did not move.
- **New component.** `ui/components/scrub_examples.py`, so `import_view.py`
  grows by the toggle and detail row only. The filter field sits outside the
  part that is redrawn, or each keystroke would replace the field being typed in.
- **E2E.** Added to `test_scrubbing.py` rather than a new journey: the plate's
  detail is visible, collapses and reopens.
- **Dry-run time.** Not separately measured: the example collection is a dict
  update per hit inside a walk whose cost is parsing and matching; the existing
  `tests/unit/scrub/test_performance.py` and the backend suite show no change.


## 8. Code review (Stage 6)

`/code-review high` over the diff against `543eb0f`; ten findings.

| Finding | Outcome |
|---|---|
| Overflow tracked in an unbounded set | **Fixed.** `other_values` is gone; overflow is a hit count |
| First-come admission can hide the most-hit value past 2 000 | **Stands, stated.** Making it top-by-hits needs exact records for values first seen late, which is a set per value for every value. The note now says *the first N values met*, and a filter that finds nothing says the value may be unlisted. Real deliveries rarely have 2 000 distinct values in the *regex* rules; the lastnames rule can. If that proves to matter, the next step is a second, count-only pass, not a bigger cap |
| Filter "No value matches" when the value was capped out | **Fixed**, with its own sentence |
| Toggle cell chosen by `text.startswith("<")` | **Fixed**: the first cell is built explicitly |
| No `aria-expanded`, detail row has no identity | **Fixed**: `aria-expanded` follows the toggle, `scrub-detail` on the row |
| Every `ScrubHit` copied the original span, freeze included | **Fixed**: see §7 |
| Grouping key differs from the scrubber's identity | **Fixed**: see §7 |
| `_one_line` twice, `placeholder` recomputed | **Fixed** |
| Backend "no context carries a matched value" assertion near-vacuous | **Fixed**: dropped; the unit test now asserts the exact `before` (`Herr <Lastname_1> rief`) |
| Filter redraws on every keystroke | **Fixed**: `debounce=300` |
