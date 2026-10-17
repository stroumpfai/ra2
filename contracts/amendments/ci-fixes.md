# Amendment: `ci-fixes`

> **APPLIED in the same commit**, as the other post-phase slices were. No
> wave is running. **No schema change, no migration, no API change, no
> dependency change.**

Reported from CI. Three things, none of them in the code under test:

1. `requires-python = ">=3.14"` named no exact interpreter, so `setup-uv`
   built every job on the newest one on the runner. That became 3.15, for
   which `lingua-language-detector` 2.2.0 ships no wheel, and every
   `uv sync --frozen` failed. A new `.python-version` pins the 3.14 that
   `pyproject.toml`'s contract line names, without touching either frozen
   file.
2. `test_a_replaced_file_is_reported` failed on `windows-latest` with
   `WinError 32`: Windows refuses to unlink a file with an open handle. The
   hazard is POSIX-only for the same reason, since a reset under a live app
   fails on the lock instead of splitting the database. Skipped on `win32`,
   with the reason; the check itself is unchanged.
3. GitHub forces actions that declare Node 20 onto Node 24 and warns on every
   run. Each action moves to its first major that declares `node24`.

---

## Frozen files changed

| File | Change |
|---|---|
| `.github/workflows/ci.yml` | `actions/checkout` v4 → v5, `actions/setup-python` v5 → v6, `astral-sh/setup-uv` v5 → v7, `actions/upload-artifact` v4 → v6. No job, step or input changes: the inputs used (`python-version`, `enable-cache`, `name`, `path`, `if-no-files-found`) are unchanged across those majors |

```diff
# .github/workflows/ci.yml — every occurrence
-      - uses: actions/checkout@v4
+      - uses: actions/checkout@v5
-      - uses: actions/setup-python@v5
+      - uses: actions/setup-python@v6
-      - uses: astral-sh/setup-uv@v5
+      - uses: astral-sh/setup-uv@v7
-      - uses: actions/upload-artifact@v4
+      - uses: actions/upload-artifact@v6
```
