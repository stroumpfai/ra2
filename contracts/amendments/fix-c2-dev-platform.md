# Amendment — `fix/c2-dev-platform` (risk C2, §8.7)

> **APPLIED in the same change**, the same way `fix-c2-agent-data-access` was.
> No wave is running.

`risk-assesment.md` §8.7: Claude Code's sandbox — the half of
`.claude/settings.json` that confines a shell command — does not run on native
Windows, where development was happening. An agent session read a file in a
sibling folder outside the checkout without a prompt or a block.

**The rule:** no sandbox on Windows — use Linux, macOS or WSL2. Therefore no
real data on a native-Windows machine where an AI agent runs. The operational
machine may still be Windows, provided no agent runs on it.

---

## 1. `sw-design.md` §12 — *On #13*

+ one paragraph after the backstop paragraph: **the backstop needs a platform
that runs it**. The sandbox runs on Linux, macOS and WSL2, not on native
Windows; Linux, macOS or WSL2 is the recommended development platform, and a
native-Windows machine on which an agent runs holds synthetic data only.
Windows stays a product target (N3) and CI keeps its Windows leg.

## 2. `CLAUDE.md`

- **The #13 paragraph** is extended: the rule covers every place outside the
  repository, not only `data/`; work inside the checkout and ask for any file
  from elsewhere; the deny list backs you up only where the sandbox runs; the
  full rulebook is `docs/rules.md`.
- **Working agreements** + *No sandbox on Windows, so no real data where agents
  run on Windows*, including the WSL2 condition (checkout on the Linux
  filesystem, `[automount] enabled=false`) and what an agent on native Windows
  does.

The Do-NOT list itself is **unchanged** — no item added, none reworded — so
`test_claude_md_carries_the_do_not_list` is unaffected.

## 3. New, not frozen

`docs/rules.md` — the rulebook for using and developing RA2. It restates rules
whose authority stays where it is (`sw-design.md` §12, `data-handling.md`,
`CLAUDE.md`) and says so beside each one; where it and a source disagree, the
source wins and `rules.md` is corrected.

## 4. Not changed

`vision.md` → Environment and `README.md`'s OS row describe where the
**product** runs, and stay as they are. `.github/workflows/ci.yml` keeps its
Windows leg.
