# Amendments to the frozen contract

A frozen file (see [`CONTRACTS.md`](../../CONTRACTS.md)) is changed by
amendment, never by editing it in a parallel branch.

**One file per branch**, named for the branch, so amendments never conflict
with each other: `contracts/amendments/feat-m1-parsing.md`.

Each one says:

1. **Which file** needs changing.
2. **Why** — the thing you cannot build without it.
3. **The exact proposed diff.**
4. **What you did instead** — the local shim, or the one
   `pytest.mark.xfail(reason="amendment: <branch>")` you left behind.

Then keep going. Do not edit the frozen file, and name the amendment in your
final report. The lead applies accepted amendments at integration and rebases
the branches that have not merged yet.

A schema amendment after Wave 1 costs a migration, so `models.py` amendments
are the ones to raise loudly and early.
