# Amendment — `fix/c2-agent-data-access` (risk C2)

> **APPLIED in the same commit**, the same way `fix-c1-real-data-guard` was.
> No wave is running.

Two frozen files, plus one this amendment **retroactively covers** — see §4.

`risk-assesment.md` C2: *AI-assisted development on the machine that holds the
real corpus*, severity Medium–High. The project is built with an AI coding
assistant by explicit design (`vision.md` → Environment), on the machine that
holds `data/` (real samples) and `var/ra2.sqlite` (2 695 real records). Agent
transcripts are processed off the host by construction. **Do-NOT #11 forbids
committing real data; nothing forbade reading it.**

---

## 1. `sw-design.md` §12 — a thirteenth invariant

```diff
 12. **Never** add a branch to production code that exists only for tests.
+13. **Never** open, query, print or paste the contents of `data/` or
+    `RA2_DATA_DIR`. Reproduce the hazard in a fixture instead.
```

**Why it is worded as an act, not as a path.** An agent that reads a real
narrative to debug an import has exported that record as surely as an upload
would. The wording names the four ways it happens — open, query, print, paste —
because "do not access" reads as a filesystem rule and the database is the
easier mistake.

§12 gains a paragraph explaining why #13 is the only invariant addressed to the
people and agents building RA2 rather than to the code, and why the *sentence*
is the invariant while the configuration is the backstop: `RA2_DATA_DIR` is
configurable, a deny rule can only name a literal path, and no glob covers a
path it has not been told about.

---

## 2. `CLAUDE.md` — the same item, verbatim, plus one paragraph

CLAUDE.md carries §12 verbatim, so #13 lands identically. It also gains a short
note under the list, because CLAUDE.md is the file an agent actually reads:

> **#13 is addressed to you.** The rest constrain the code; that one constrains
> the agent reading this. Your transcript leaves this machine […]

---

## 3. `.claude/settings.json`, and `.gitignore` — the deny rules

New file, committed:

```json
{
  "permissions": {
    "deny": ["Read(./data/**)", "Read(./var/**)", "Bash(sqlite3 *)"]
  },
  "sandbox": { "filesystem": { "denyRead": ["./data", "./var"] } }
}
```

A `Read(...)` deny rule is merged into `sandbox.filesystem.denyRead`, so it
covers a sandboxed `cat` and `grep` as well as the Read tool. Both are written
out anyway: the duplication costs nothing and the intent should be legible to
someone who reads only one of the two keys.

`Bash(sqlite3 *)` is a **speed bump, not a control**, and is recorded as such.
The app reaches SQLite through SQLAlchemy, so nothing legitimate is lost, but
`python -c "import sqlite3"` walks around it. It is there because the database
is the easier mistake and the CLI is the obvious way to make it.

`.gitignore` changes so the file ships:

```diff
-.claude/
+.claude/*
+!.claude/settings.json
```

**This is the load-bearing half of §3.** A deny rule in an ignored directory
protects the machine it was written on. C2 is about the development practice,
not about one workstation, so the rule has to reach everyone who clones.
`.claude/worktrees/` and the session state stay ignored.

---

## 4. `tests/test_m0_contract.py` — the count becomes a comparison

`test_claude_md_carries_the_do_not_list` asserted `== 12` against a literal.

```diff
-    # The twelve Do-NOT items of sw-design.md §12, numbered.
-    assert len(re.findall(r"^\d+\. \*\*Never\*\*", text, flags=re.MULTILINE)) == 12
+    design = (REPO_ROOT / "sw-design.md").read_text(encoding="utf-8")
+    section = design.split("## 12. Invariants")[1].split("\n## ")[0]
+    expected = len(re.findall(r"^\d+\. \*\*Never\*\*", section, flags=re.MULTILINE))
+    assert expected >= 13, "sw-design.md §12 lost an invariant"
+    assert len(re.findall(...", text, ...)) == expected
```

Bumping `12` to `13` would have worked and would have left the same trap: a
magic number in this file is one that gets bumped here without anyone opening
the other document, which is the drift the assertion exists to catch. Counting
against §12 itself means adding an invariant to one document and not the other
is a red test, and this assertion never needs touching again. Verified by
removing #13 from CLAUDE.md alone — the test fails.

---

## 5. Retroactive — `CLAUDE.md`'s loopback edit in `39c72e0`

`CLAUDE.md` is frozen (`CONTRACTS.md`, *The contract — owner: M0*). The A1
commit edited its *Loopback only* agreement to state the transport half of the
rule **without an amendment file**, and `CONTRACTS.md` listed it under *Not
frozen, and changed*, which is wrong. Both are corrected here: the edit is
named in this amendment and the row moves to the amended table. No content
changes — only the record of it.

---

## What this does not do

**C2's second recommendation is untouched**: *keep real data off the
development checkout entirely — real delivery files and the real corpus on the
target machine, synthetic hazards everywhere else.* That is the control that
would make the rule unnecessary rather than merely stated, and it is a project
decision. `data/` and `var/ra2.sqlite` are on this machine today. Recorded as
open in `risk-assesment.md` §8.3.

**And the honest limit of a deny rule.** It is a guard rail on one tool on one
configured path. It does not survive `RA2_DATA_DIR` pointing elsewhere, it does
not reach a subprocess that reads a file itself, and a Playwright trace taken
against a real corpus would sit in `test-results/`, which is not denied — the
E2E suite runs on synthetic data today, and denying it would block debugging a
hazard that does not yet exist. #13 is the control. The deny list is what
catches the lapse.
