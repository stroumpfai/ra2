# Amendment — `fix/windows-paths-and-eol`

> **APPLIED in the same commit**, like the other `fix-*` amendments. No wave
> is running.

One frozen file, plus a new `.gitattributes`. Nothing here is a feature or a
risk finding: this is the repository failing on the **one platform it is meant
to be deployed on**. Found while verifying `fix/b3-deletion-path` — `just test`
could not be made green on Windows for reasons that had nothing to do with that
change, and each was reproduced at `HEAD` with that work stashed.

| Symptom on Windows at `HEAD` | Cause | Fixed by |
|---|---|---|
| Most of `tests/ui` fails with `SyntaxError: truncated \UXXXXXXXX escape` | `_data_dir_chip` pastes `RA2_DATA_DIR` into a NiceGUI **props string** | **`fix-ui-windows-data-dir`** — see below. **Not this amendment** |
| Four byte-exact fixture comparisons fail | No `.gitattributes`; `core.autocrlf=true` rewrites every LF file to CRLF on checkout | §2 |
| The `openai` and `pynvml` seam gates fail | `str(path.relative_to(...))` yields `ra2\infra\…`, compared against `ra2/infra/…` | §1 |

---

## 0. The chip is somebody else's fix, and theirs is the one to keep

`ra2/ui/shell.py`'s data-dir chip was diagnosed and fixed **independently and
first** on branch `fix-ui-windows-data-dir` (commit `8665563`, *The data-dir
chip stops reading its own value as Python*), which also adds **`SD31`** — a
prop whose value did not come from the source file is assigned through the
props *mapping*, never through the props *string*.

This branch reached the same fix while verifying B3 and **dropped it on
finding the other one**, rather than commit a second copy that would conflict
line for line. Theirs is the better of the two and is the reason why: it names
the *provenance* rule rather than the Windows symptom, and it tests the
**silent** half — `C:\tmp\the\new\report` is entirely valid Python, so
`ast.literal_eval` would not have raised, it would have returned
`C:<TAB>mp<TAB>he<LF>ew<CR>eport` and the chip would have named a directory
that does not exist. A chip whose whole job is to say which database you are
looking at, answering confidently and wrongly, is worse than the crash.

**Consequence for anyone reading this:** `tests/ui` is red on Windows until
`fix-ui-windows-data-dir` lands. The 303-passing figure recorded in
`risk-assesment.md` §8.6 was measured with that fix applied. `SD29` and `SD30`
(B3) and `SD31` (the chip) do not collide.

---

## 1. `tests/test_p3_contract.py` — `as_posix()`, three times

```diff
-                offenders.append(str(path.relative_to(REPO_ROOT)))
+                offenders.append(path.relative_to(REPO_ROOT).as_posix())
```

`test_openai_is_imported_in_exactly_one_module` and its `pynvml` twin compare
the offender list against `["ra2/infra/ollama_client.py"]` and
`["ra2/infra/gpu.py"]`. On Windows `str()` of a relative `Path` uses `\`, so
both gates fail **when the seam is intact** — a false positive on the one
contract `import-linter`'s `one-llm-seam` and `CLAUDE.md`'s Do-NOT #1 exist to
protect. A gate that is permanently red on a platform is a gate that gets
ignored on that platform, and this one guards whether `openai` can be imported
outside the adapter.

`test_nothing_shells_out` takes the same change one line up. It only builds a
message, so it was not failing; it is changed so the file has one idiom rather
than two, and so the next person copies the right one.

**The idiom already exists in this repository** —
`tests/backend/infra/test_gpu_probe.py:292` and
`tests/backend/infra/test_ollama_client.py:795` both write
`path.relative_to(REPO_ROOT).as_posix()`. This file is the one that did not.

---

## 2. `.gitattributes` *(new)* — `* -text`

`CLAUDE.md` requires the hazard fixtures to be synthesised **byte-exactly** and
committed; four tests compare committed bytes against generator output or a
golden report. With Git for Windows' installer default (`core.autocrlf=true`)
and no `.gitattributes`, every file stored with LF is checked out with CRLF,
and those four comparisons fail on Windows and pass everywhere else — green on
CI, red on the target platform, with nothing in the repository explaining why.

**`* -text`, not the usual `* text=auto eol=lf`.** The usual line normalises on
commit, which would rewrite the delivery hazards: **twenty fixtures are stored
*with* CRLF on purpose** (`git ls-files --eol` names them), because a real
delivery uses CRLF and `FindingCode.DOUBLED_CRLF` exists to describe what some
Astrana exports do with it. `-text` disables conversion in both directions, so
each file is checked out exactly as committed — LF where LF was committed, CRLF
where CRLF was, bytes where bytes were. That is the same rule the fixtures are
written under.

**The working tree was normalised with it.** `.gitattributes` governs future
checkouts; the 436 files already CRLF in the tree were rewritten to LF in
place, which made them byte-identical to what the object store already held.
`git diff` therefore reports only the files this work actually edits — line
endings moved, content did not.

> **One local artefact worth knowing about.** Rewriting those files changed
> their mtimes, so git's index cache is stale and `git status` may list them as
> modified until it can refresh. `git diff` is empty for every one of them and
> `git ls-files --eol` reads `i/lf w/lf`; a `git status` in a normal shell
> refreshes the index and the noise disappears.

---

## 3. Not frozen, and changed

| Path | What |
|---|---|
| `README.md` | *Fixtures contain the real hazards* now says what `.gitattributes` is for and why it is `-text` rather than the usual `text=auto eol=lf` — the next person to tidy that file is the risk |
| `CONTRACTS.md` | Two rows |

**Unchanged, deliberately:** `core.autocrlf` is left alone. It is a *user's*
global setting, `.gitattributes` overrides it for this repository, and a fix
that only works on a machine someone remembered to configure is not a fix.

---

## 4. Evidence

| Check | Result |
|---|---|
| The four byte-exact fixture tests, after the `.gitattributes` normalisation | Pass |
| `tests/test_p3_contract.py`, after | 72 passed |
| `git diff --numstat` after normalising 436 files | Only the files this work edits |
| `tests/ui`, with `fix-ui-windows-data-dir` applied | 303 passed, 1 skipped — from 13 failed / 8 passed over the two modules sampled before |
