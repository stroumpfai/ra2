# Amendment — `feat/reset-cli` (R3)

> **APPLIED at integration**, with the whole slice, in one commit. See
> `feat-reset-discard-service.md`'s note on why no shim was written.

One frozen file. `justfile`'s recipe list is described in `CONTRACTS.md` as
**final**, so two new recipes need saying out loud.

---

## 1. `justfile` — `reset`, `reset-seed`

**Why.** `just` is the entire command surface (ra2.md). A wipe that is not a
recipe is a wipe someone runs as a raw `python scripts/…` with the wrong
`RA2_DATA_DIR` — which is the failure the script itself is built to prevent.

```diff
+# Show what a wipe of RA2_DATA_DIR would remove. `just reset yes` carries it out.
+reset token="":
+    uv run python scripts/reset_data.py {{token}}
+
+# Wipe, then seed a working state. Needs the same token: `just reset-seed yes`.
+reset-seed token="":
+    uv run python scripts/reset_data.py {{token}}
+    uv run python scripts/seed_dev.py
```

**The token is a positional argument with an empty default**, so the bare
recipe prints the plan and removes nothing. A destructive default is how the
wrong database gets deleted at the end of a long day.

`reset-seed` **composes the two scripts in the recipe** rather than importing
one from the other: `scripts/` is not a package, and a cross-script import
would be the only one in the repo.

Both run identically on Windows and Linux — no shell-out, no `rm`, nothing
platform-specific (N3).

---

## 2. The header chip is not contained in `ra2/ui/shell.py`

`plan-reset-and-discard.md` §6 gives R3 "the header data-dir chip in
`ra2/ui/shell.py`", which reads as one file. It cannot be:

- the data directory is a `Settings` value;
- `ra2/ui/` may not import `ra2/infra/` (§1.1);
- Do-NOT #8 forbids parking it in a module global.

So `shell()` takes `data_dir: str | None`, and **each of the seven built views
passes `services.lifecycle.data_dir().data_dir`** — one line per view, the same
way every other value reaches a view. `placeholder_view` passes nothing and
renders no chip: it has no services to ask, and a header that lies about which
database it is looking at would be worse than one that says nothing.

The plan's §6 table was corrected in the same commit.

---

## 3. `scripts/seed_dev.py` writes its own delivery

The plan says "register one fixture delivery". The committed fixtures live
under `tests/fixtures/deliveries/hazards/`, and a shipped script reaching into
the test tree would make `tests/` a runtime dependency of a developer command.

So the seed **synthesises its own**, importing only the column *names* from
`ra2.domain.parsing.headers` — exactly what `generate_hazards.py` does, and
sanctioned for the same reason (a 67-column file stays 67 columns without
anyone counting). Every value is invented in the script.

It is deliberately **not clean**: a declared-count mismatch, an all-empty
column, and a French record the upstream cp1252 conversion has already
damaged. All three are non-blocking and all three show up in the import
report. A spotless seed would hide the things this app exists to surface
(mvp-spec.md §15).

The codelist import is **skipped with a printed reason** when
`data/Codes/codes-2018.json` is absent, since `data/` is gitignored and a
fresh clone has none. A seed that failed there would be a seed nobody could
run.
