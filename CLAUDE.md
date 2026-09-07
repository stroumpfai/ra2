# CLAUDE.md — RA2

**Read [`sw-design.md`](sw-design.md) first.** It is the architecture contract
and implementing agents must stay inside it. Where it is silent, follow the
nearest existing pattern; where it is wrong, raise it and change *that file
first*, in the same commit.

**Document authority.** `vision.md` (why) → `ra2.md` (stack, process) →
`mvp-spec.md` (what) → **`sw-design.md` (how)**. On a *what* question
`mvp-spec.md` wins. On a *how* question `sw-design.md` wins.
[`plan-m0-m5.md`](plan-m0-m5.md) says who builds what and what they may touch;
`sw-design.md` wins over it, `mvp-spec.md` over both.

---

## The Do-NOT list

sw-design.md §12, verbatim. These are invariants, not preferences. Each one has
a test, a lint rule or a CI gate behind it.

1. **Never** import `openai` or `ollama` outside the `LLMClient` implementation.
2. **Never** mutate an `extraction`, `record` or `corpus` row. A re-run adds rows.
3. **Never** edit an applied Alembic migration. Add a new one.
4. **Never** open a file without an explicit `encoding=`, and never with
   `errors="replace"`.
5. **Never** read canton, language or table kind from a filename. All three come from
   the data.
6. **Never** silently repair or drop a row. Every one produces a `Finding` carrying
   its key.
7. **Never** put business logic in `ui/`, and never let `ui/` touch a session or an
   ORM object.
8. **Never** hold UI state in module globals; use `app.storage.client`.
9. **Never** fetch anything over the network from the UI — no CDN, no fonts, no
   telemetry.
10. **Never** use `metadata.create_all()`, in the app or in tests.
11. **Never** commit anything matching the real-data patterns in `.gitignore`.
12. **Never** add a branch to production code that exists only for tests.

---

## The layer rule

Enforced by `import-linter` (`.importlinter`). A violation fails the build; it
is not a review comment.

| Package | May import |
|---|---|
| `ra2/domain/` | stdlib, `pydantic`. **Nothing else in `ra2/`.** |
| `ra2/persistence/` | `domain`, SQLAlchemy, Alembic |
| `ra2/services/` | `domain`, `persistence`, `infra` protocols |
| `ra2/api/` | `services`, `domain` |
| `ra2/ui/` | `services`, `domain` |
| `ra2/infra/` | `domain` |

- `domain` imports **no** SQLAlchemy, **no** FastAPI, **no** NiceGUI, no filesystem.
- `api` never imports `ui`. `ui` never imports `api` or `persistence`.
- `ra2/main.py` and `ra2/cli.py` are composition roots and see everything. They
  contain **wiring only**.
- The UI calls services **in-process as Python**, never over HTTP to its own API.

---

## The ownership rule

Every path has exactly one owner per wave
([`plan-m0-m5.md` §4](plan-m0-m5.md)). **Writing outside your owned paths is a
defect**, and the integration check catches it mechanically
(`git diff --name-only`).

Files listed in [`CONTRACTS.md`](CONTRACTS.md) are **frozen**. If you need one
changed:

1. write `contracts/amendments/<your-branch>.md` — the file, why, and the exact
   proposed diff (one file per branch, so amendments never conflict);
2. do **not** edit the frozen file;
3. keep going — shim inside your own paths if you can, otherwise
   `pytest.mark.xfail(reason="amendment: <branch>")` on that one test and
   finish everything else;
4. name every amendment in your final report.

A schema amendment after Wave 1 costs a migration. Catch those at the M0 review
gate.

---

## Working agreements

- **Toolchain.** `uv` for everything Python (`uv sync --frozen`, `uv run …`);
  `just` for every command. Never bare `pip`, never `python -m venv`.
- **Tests are the handshake.** You are done when your named tests are green in
  your own worktree *and* `just lint` and `just test` pass there. A pull
  request that adds behaviour without a test at the right layer is not
  complete.
- **Test layers** (sw-design.md §11): `tests/unit` pure domain ·
  `tests/backend` services, repositories and the API on temp file SQLite ·
  `tests/ui` NiceGUI `User` fixture · `tests/e2e` Playwright · `tests/eval`
  phase 3. `tests/conftest.py` is frozen; per-layer conftests belong to
  whoever owns that layer in the current wave.
- **One migration author, ever, in phase 1** (A3). Nobody else runs
  `alembic revision`. No parallel heads.
- **Fixtures must contain the real hazards** — mixed encodings, a stray `|`, an
  embedded newline, an orphan key, a key duplicated across two cantonal sets,
  an all-empty column, French already lossy. Clean fixtures are not acceptable
  (mvp-spec.md §15). Real data is gitignored and must never reach a test, so
  the hazards are synthesised byte-exactly and committed.
- **Findings, not prose.** `FindingCode` values are stable identifiers; assert
  on the code, never on message text. Wording lives in one rendering table in
  `ui/`.
- **No egress at all in phase 1.** There is no LLM endpoint to talk to yet, and
  J6 fails the build on any request to a host other than the server under test.
- **Design fidelity is a requirement, not a suggestion** (sw-design.md §8.2):
  the tokens, fixed sizes and layout rules in
  `design/nav-import-census/README.md` are asserted in E2E. Fonts are vendored
  in `ra2/ui/static/fonts/` — the design README says Google Fonts, N1 forbids
  it, and N1 wins (SD3).
