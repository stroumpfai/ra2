# Testing — RA2

**What is tested, how well, what is not, and how to run it.**

This page is for someone who needs to judge the state of testing on this
project and reproduce the results themselves. It assumes no knowledge of the
codebase.

**This page is not authority.** `mvp-spec.md` decides *what* the product must
do, `sw-design.md` decides *how* it is built and tested, and where either
disagrees with this page, this page is wrong. Every number below was measured,
not remembered — re-measure rather than edit them.

**Last reviewed:** 2026-09-22 · against commit `06d1650` · Linux, 28 cores.

---

## 1. The short version

| | |
|---|---|
| Automated tests | **2 592** |
| Commit gate (`just test`) | 2 501 tests · **~32 s** · currently **green** |
| PR gate (`just e2e`) | 91 tests · ~1 min 45 s · currently **1 failing** — see §7.1 |
| Coverage | **96 %**, measured on business logic only — see §5 |
| Manual test effort | none required to run either gate |
| Nightly / scheduled | none |

The two gates are independent: `just test` never starts a browser, `just e2e`
is the only thing that does.

---

## 2. How the tests are organised

Five layers, chosen so that each failure points at one place. A test belongs
to the **lowest** layer that can express it; this is enforced in review, not by
a tool.

| Layer | Directory | Tests | What it exercises | Speed |
|---|---|---|---|---|
| 1 · unit | `tests/unit/` | 720 | Business rules alone — parsing, validation, census maths, scoring, ranking statistics. No database, no network, no server. | ~7 s |
| 2 · backend | `tests/backend/` | 947 | Services, database repositories and the HTTP API, against a real temporary SQLite file and an in-process HTTP client. | ~57 s |
| 3 · UI | `tests/ui/` | 364 | Every screen, driven through a simulated browser in the same process. No real browser. | ~5 min |
| 4 · E2E | `tests/e2e/` | 91 | Fourteen end-to-end journeys in a real Chromium against a real server. | ~1 min 45 s |
| 5 · eval | `tests/eval/` | **0** | Model accuracy against a labelled baseline. **Not built** — see §7.4. |

Plus 469 contract tests at `tests/` root, which assert that frozen
architectural decisions have not been edited away, and 1 that the HTTP API's
public schema has not changed without being noticed.

Layers 1–3 are the commit gate. Layer 4 is the pull-request gate. Layer 5 is a
placeholder.

### 2.1 What the E2E journeys cover

These are the fourteen paths a user actually walks. They are the best single
answer to "is the product working".

| | Journey |
|---|---|
| J1 | Import a delivery of files → analyse → fix an encoding → drop a file → create a corpus → read the census → export CSV |
| J2 | A delivery with duplicate record keys is **refused**, the error names the key, and nothing is half-written |
| J3 | A corpus in use cannot be deleted; the API refuses it too |
| J4 | Layout holds at 1024, 1440 and 1920 px — no wrapping, no horizontal scroll |
| J5 | Every navigation item routes, with the specified headings |
| J6 | **No network egress**: the test fails if the browser contacts any host but the server under test |
| J7 | Code lists: import, map to the corpus, report coverage |
| J8 | Build and freeze a feature set through the UI |
| J9 | Edit a prompt template (copy-on-write) |
| J10 | Launch a model evaluation and watch it finish |
| J11–J13 | The results boards: rankings, per-model detail, and the validity footer |
| J14 | Mismatch review — where an analyst judges what a model got wrong |
| — | Discard a run from the browser |

---

## 3. Running the tests

Everything runs through `just`. There is no other supported entry point. Install
once:

```
uv sync --frozen          # dependencies, pinned
just setup-e2e            # Chromium, for layer 4 only
```

Then:

| Command | Runs | Takes |
|---|---|---|
| `just test` | layers 1–3 + coverage — **the commit gate** | ~32 s |
| `just e2e` | layer 4, real browser — **the PR gate** | ~1 min 45 s |
| `just lint` | formatting, type checking, architecture rules | ~15 s first run, <1 s after |
| `just check-data` | refuses any real production data in the repository | ~2 s |
| `just eval` | layer 5 — currently collects nothing | — |

`just test` uses every CPU core. On a 2-core machine expect roughly 3 minutes
rather than 32 seconds; the work is the same.

To run one area only, e.g. while investigating a failure:

```
uv run pytest tests/ui                                  # one layer
uv run pytest tests/ui/test_census_view.py              # one file
uv run pytest tests/ui/test_census_view.py::test_name   # one test
uv run pytest -m e2e -k J6                              # by name
```

These run single-process and print a full traceback, which is what you want
when reading a failure rather than counting them.

---

## 4. Reading the results

### 4.1 On your own machine

Output is a terminal report. The last line is the verdict:

```
2501 passed, 1 skipped in 32.08s
Required test coverage of 85.0% reached. Total coverage: 96.17%
```

A failure prints the test's name, the assertion that failed and the values
involved. `FAILED` means an assertion in the test; `ERROR` means the setup or
cleanup around it broke, which usually points at a different test than the one
named.

**Browser failures leave evidence.** `just e2e` writes a screenshot at the
moment of failure and a full trace to `test-results/<test-name>/`. Open the
trace with:

```
uv run playwright show-trace test-results/<test-name>/trace.zip
```

That gives a frame-by-frame replay of the browser — the DOM, the network, and
what was on screen. It is the fastest way to decide whether a journey failure
is a product bug or a stale expectation. `test-results/` is ignored by version
control and is safe to delete.

### 4.2 In CI

Every push and pull request runs five jobs on GitHub Actions:

| Job | Platform | What fails it |
|---|---|---|
| no real data | Linux | any tracked file that looks like real production data |
| lint | Linux | formatting, type errors, architecture-rule violations |
| layers 1–3 | Linux **and** Windows | any test in the commit gate |
| layer 4 | Linux only | any journey |
| alembic check | Linux | the database schema and the code disagreeing |

Layers 1–3 run on **both** Linux and Windows, because the product must run on
Windows and file encodings and line endings behave differently there. That
matrix has caught real defects and is not decoration.

Machine-readable results (JUnit XML) are uploaded as the `test-results-*`
artifacts on each run; browser traces and screenshots as `playwright-traces`.
Both are downloadable from the run's summary page and are what to attach to a
defect report.

---

## 5. Coverage — and what the number does not mean

**96 %** (`fail_under = 85`, so the build fails below 85 %).

Read that number carefully. It is measured over **two packages only** —
`ra2/domain/` (business rules) and `ra2/services/` (application logic) — which
is roughly 4 600 statements. It deliberately excludes the user interface, the
HTTP layer, the database mapping and the external adapters.

This is a considered choice, not an oversight. Line coverage of a UI measures
whether a screen was drawn, not whether it was drawn correctly, and chasing it
produces tests that assert nothing. Those layers are covered by **behaviour**
instead — 364 UI tests and 91 journeys — which is not expressible as a
percentage.

The practical consequence for a test manager: **96 % is a statement about the
business rules, and says nothing about the screens.** If you want assurance
about the screens, read §2.1 and the UI test names, not this number.

Lowest-covered modules, as somewhere to look first:

| Module | Coverage |
|---|---|
| `domain/matching.py` | 87 % |
| `services/results_service.py` | 86 % |
| `domain/parsing/analysis.py` | 90 % |
| `services/scoring_service.py` | 91 % |

---

## 6. How the test data is built, and why it is not real data

**No production data is used in testing, ever, and none may enter the
repository.** A CI job (`just check-data`) refuses any tracked file that looks
like a real delivery, and a pre-commit hook refuses it per file.

That constraint is the reason for the project's most unusual testing decision:
the awkward cases are **synthesised byte by byte** and committed as fixtures,
rather than sampled from real deliveries. There are 26 of them — 14 malformed
deliveries, 5 malformed code lists, 7 malformed prompt templates — each
carrying exactly one defect a real file has been seen to have:

- text in a legacy Windows encoding, and text in no valid encoding at all
- a stray field separator inside a row, and line breaks inside a field
- a child record whose parent is missing; a record key duplicated across two
  cantons
- a column that is empty in every row
- French text whose accents were already destroyed upstream
- a stated count that disagrees with the actual number of rows

Each has a named test asserting the specific defect code raised **and** that
the offending record key appears in the report — because the product's promise
is that nothing is silently repaired or dropped. Clean fixtures are explicitly
not acceptable (`mvp-spec.md` §15).

Two consequences worth knowing:

- **Failures are stable and reproducible.** There is no flakiness from data,
  no test that passes only on the machine holding a particular file.
- **The fixtures are only as good as the defects someone thought of.** A defect
  class nobody has seen in real data is a defect class not tested. This is the
  most likely source of an escape into production, and the right response to
  one is to add a fixture, not a special case in the code.

---

## 7. Limitations — read this section before relying on the suite

### 7.1 The PR gate is currently failing

`just e2e` is **red**: 1 failed, 89 passed, 1 skipped.

```
FAILED test_j13_the_validity_footer_names_the_real_cfg_and_corpus
  expected the footer to contain 'corpus-j11'
  actual: "...on corpus scored corpus j11 only..."
```

This is a **stale expectation, not a product defect**. The results boards were
deliberately changed to name a corpus by its human-readable name rather than
its internal identifier; J13 still asserts the identifier. It predates the
current work — it has been failing since the commit that made that change
(`6bae3a3`) — and it is a one-line fix to the test. It is recorded here rather
than quietly fixed because a gate that is known-red and left red stops being a
gate.

### 7.2 `just lint` is failing on Linux

`uv run mypy` reports one error, `tests/e2e/conftest.py:97: Statement is
unreachable`. It is a platform artefact: the code after a Windows-only guard is
genuinely unreachable when the type checker runs on Linux. It affects no test
and no product code, and it means the lint job is red on Linux. Also
long-standing.

### 7.3 What is not covered by any automated test

- **Anything a real language model does.** Every test in layers 1–4 runs
  against a substitute model that returns fixed answers. This is deliberate —
  the suite must pass on a machine with no GPU and nothing installed — but it
  means **model quality is entirely untested** by the gates. See §7.4.
- **Real production data.** By design (§6). The first contact between this
  product and a real delivery is a manual act.
- **Performance and volume.** There is no load test, no timing assertion, and
  no test over a corpus larger than the fixtures. A run over real volumes takes
  hours; nothing measures whether it still finishes.
- **Concurrency beyond one user.** The product is designed for a single analyst
  on one machine; nothing tests two people using it at once.
- **Accessibility — nothing at all.** `sw-design.md` §11.5 specifies it: *"An
  axe-core smoke pass runs on Import and Census; critical violations fail."*
  No such check exists anywhere in the repository, and no accessibility tool is
  installed. This is a specified gate that was never built, which is worse than
  a known gap, because the design document reads as though it is covered.
- **Visual appearance.** Screenshot comparison exists as a marker but has no
  tests behind it and is explicitly never a gate — anti-aliasing differences
  make it too unreliable to block a merge.
- **Upgrade from a previous version.** Database migrations are tested forwards
  from empty; no test upgrades a database containing realistic prior data.

### 7.4 Layer 5 does not exist yet

The directory, the marker and `just eval` are in place, and collect **zero
tests**. The intent is 30–100 hand-labelled records scored against a committed
baseline, failing if accuracy drops. Until it exists, **no automated check
tells you whether the product's answers are getting better or worse** — the
question the product exists to answer. This is the largest single gap in the
strategy and it is a known, scheduled one, not an oversight.

### 7.5 Eight tests skip silently

Tests marked `realdata` read sample files if they are present and skip if they
are not. In CI they always skip. They are never required to pass, so a green
run does not mean they ran.

### 7.6 Stability

The commit gate was measured over 20 consecutive runs at the current commit
with **no failures**. That is a recent state: two tests in the evaluation
screen failed roughly one run in four until 2026-09-22, which turned out to be
a genuine product defect rather than test flakiness — a finished run could be
left displayed as still running, permanently. The account is in
[`plan-fix-poll-stop-race.md`](../plan-fix-poll-stop-race.md), and it is the
argument for investigating an intermittent failure rather than re-running it.

There is no quarantine mechanism and no automatic retry. A test that fails
intermittently fails the build, which is intentional.

---

## 8. Conventions worth knowing before reading a failure

- **Assert on codes, never on wording.** Defects raised by the product carry
  stable identifiers; the user-facing wording lives in one place and can change
  without touching a test. If a test asserts a sentence, that sentence is
  itself the requirement.
- **A re-run adds records, it never edits them.** Nothing in the product
  overwrites an extraction or a corpus, so no test needs to clean up after
  another. Each gets its own temporary database.
- **There is no test-only branch in the product code.** Substitutes are passed
  in from outside. What runs under test is the same code that ships.
- **Tests are named as sentences** describing the behaviour
  (`test_a_deselected_file_is_still_listed_but_takes_part_in_no_check`). The
  list of test names is a readable specification, and `--collect-only -q` will
  print it.

---

## 9. Where to look next

| Question | Document |
|---|---|
| What must the product do? | `mvp-spec.md` |
| How is it built, and why is the test strategy this shape? | `sw-design.md` §11 |
| What does the sample data contain? | [`docs/seed.md`](seed.md) |
| What is deliberately frozen and must not change? | `CONTRACTS.md` |
| Why is the suite fast? | `contracts/amendments/perf-test-suite.md` |
