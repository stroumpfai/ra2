# Amendment — `fix/c1-real-data-guard` (risk C1)

> **APPLIED in the same commit.** No wave is running, so there is nobody to
> collide with, and the alternative — a proposal with no gate behind it —
> leaves a High finding open for the sake of the procedure that exists to
> protect parallel work.

Four frozen files, all M0's "Packaging and gates" row, all for one finding:
**the barrier against committing real data is name-shaped, opt-in and not in
CI** (`risk-assesment.md` C1, severity High, verified).

The shape of the hole: `.gitignore` and `scripts/check_no_real_data.py` both
list `vum_*.txt` and `AstranaExport*`. The Astrana delivery's real filenames
are `Unfall.csv`, `Objekt.csv` and `Mitfahrende.csv` (mvp-spec.md §4.1) and
match **no pattern outside `data/`**. Two copies of one pattern list, and both
were wrong in the same way — which is itself the argument for what replaces
them.

---

## 1. `scripts/check_no_real_data.py` — content-shaped, not name-shaped

**Why.** A name check is a check against typos. The scenario C1 describes is a
delivery file copied into the tree while debugging an import on real data — the
single most natural thing to do when a parser fails — and it arrives under its
own correct name.

The guard now reads the file. It keeps the name patterns as defence one (they
are cheap, they are what `.gitignore` says, and they catch a `.zip` it cannot
see into) and adds a content check that decides what a file **is**:

```diff
+from ra2.domain.delivery import FileKind
+from ra2.domain.parsing.headers import ColumnSet, classify_header, column_index
```

**It calls the application's own classifier.** `classify_header` is the
function the importer uses to decide what a file is, delimiter and column
vocabulary and all. The guard keeping its own copy of that vocabulary is
exactly the duplication that made the name check wrong in two places at once,
so it keeps none.

`ra2.domain.parsing.headers` is pure domain — the stdlib and this repository,
no third-party package — so the guard still runs on an interpreter with nothing
installed. That is not a nicety: CI's new job depends on it (§3).

**A delivery-shaped file is refused unless both hold:**

| Condition | Catches |
|---|---|
| it is under `tests/fixtures/deliveries/` | C1's scenario — a delivery file anywhere a person actually puts one |
| its keys were **invented**, not delivered | real rows sampled into a fixture, which CLAUDE.md forbids in prose and nothing checked |

The second rule is exact rather than heuristic, and that is worth saying
plainly. `generate_hazards.uid()` builds a key as a short hex tag plus a
zero-padded decimal counter, so a synthetic key holds three to five distinct
characters out of thirty-two (`aa000000000000000000000000000001`). A real
32-hex key drawn from sixteen symbols holds about thirteen.
`MAX_INVENTED_DISTINCT_CHARS = 8` sits in the empty space between the two
populations, and `test_the_two_key_populations_do_not_overlap` asserts the gap
rather than the threshold.

**A limit, stated rather than hidden.** The headerless detector keys on the
*first* field, so a RADIS tail is caught and an Astrana tail — whose key sits
at column 2, after `Jahr` and `Datum` (§4.1) — is not. Both are caught the
moment the header line is present, which is how a delivery arrives.

**`--all`** was added for CI: every tracked file, from `git ls-files`.

**`.gitignore` is deliberately NOT changed.** Adding `Unfall.csv` to it would
be the name-shaped fix again, and worse: the committed hazard fixtures are
named `Unfall.csv`, `Objekt.csv` and `Mitfahrende.csv`, so the pattern that
blocked the delivery would block the fixtures the parsing suite is built on.
The content check distinguishes them; a filename cannot.

---

## 2. `.pre-commit-config.yaml` — the hook description, and `uv run`

```diff
       - id: no-real-data
-        name: no real data (the .gitignore delivery patterns)
+        name: no real data (name and content)
         description: >
           The VUM delivery is classified sensitive and must stay on the host
           (§12.11). This refuses any staged file matching the real-data
-          patterns in .gitignore, whatever its path.
-        entry: python scripts/check_no_real_data.py
+          patterns in .gitignore, and any file that *looks* like a delivery —
+          read from its header and its keys, so `Unfall.csv` is caught whatever
+          it is called and wherever it sits (risk C1).
+        entry: uv run python scripts/check_no_real_data.py
```

**`uv run python` rather than `python`.** The old entry assumed the developer's
`python` was the project's. The guard is a 3.14 source file — `ruff format`
writes `py314` syntax into it, as it does everywhere — and a hook that dies with
a `SyntaxError` on a machine whose `python` is 3.12 is a hook that fails open.
The two hooks above it already run through `uv run` for the same reason.

This does **not** reintroduce a dependency on `uv sync`: the guard imports no
third-party package, CI runs it on a bare interpreter with no virtualenv at
all, and `test_the_guard_needs_no_third_party_package` holds that property with
`python -S -E`.

---

## 3. `.github/workflows/ci.yml` — a job that runs first and needs nothing

C1's third defence gap: **CI did not run the guard at all.** The `lint` job
runs ruff, mypy and `lint-imports` only, so the hook — installed by hand once
per clone, bypassed by `git commit --no-verify` — was the whole of it.

```diff
 jobs:
+  no-real-data:
+    name: no real data (content-shaped, every tracked file)
+    runs-on: ubuntu-latest
+    steps:
+      - uses: actions/checkout@v4
+      - uses: actions/setup-python@v5
+        with:
+          python-version: "3.14"
+      - run: python scripts/check_no_real_data.py --all
+
   lint:
```

**No `uv sync`, no cache, no dependency on another job.** This is the one gate
whose failure cannot be fixed by a later commit — the repository is public
(`"private": false`, confirmed via the GitHub API), so content should be
assumed mirrored the moment it is pushed. A gate like that should not be able
to be skipped because an unrelated install step broke.

**`--all` rather than the pull request's changed files**, which is what the risk
file recommends. It is a superset, it needs no `base_ref` plumbing or
`fetch-depth` bump, and it answers the question that actually matters in CI:
not "what did this branch add" but "is any of this in the repository at all".

---

## 4. `justfile` — `check-data`

```diff
+# Refuse any tracked file that looks like a real delivery (risk C1). The same
+# check the pre-commit hook runs per file, over the whole tree — which is what
+# CI runs.
+check-data:
+    uv run python scripts/check_no_real_data.py --all
```

`just` is the entire command surface (ra2.md). A gate a developer cannot run
by name is a gate they meet for the first time in CI.

---

## What this does not do

**The repository is still public.** C1's third recommendation is a decision,
not a diff: *reconsider public visibility for the duration*. There is no data
in the repository today — `--all` is green over every tracked file, which this
amendment is in a position to state — but a public repository makes the one
mistake in this class unrecoverable, and no guard closes that. It is recorded
as open in `risk-assesment.md` §8.2.
