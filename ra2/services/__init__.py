"""Use cases, transactions, task orchestration.

May import `domain`, `persistence` and the `infra` protocols (sw-design.md
§1.1). **No service reaches for a global** — every seam arrives through the
constructor (§3).

Services return the frozen read models in `readmodels.py`, never ORM objects:
`ra2/ui/` must never touch a session or an ORM object (§12.7), and no ORM
object crosses the API boundary either.
"""
