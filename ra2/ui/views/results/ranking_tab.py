# STUB — signature only at M27, body owned by V3 (feat/p4-results-ranking).
"""Tab 3 — Ranking (design/results/README.md §3).

The one question the other tabs do not answer, answered honestly: usually "two
models are tied, pick on cost".

**Tied models repeat their rank** — `1, 1, 3`, never `1, 2, 3`. mvp-spec.md
§11.5 renders overlapping intervals as a tie, not as an order, and a dense
enumeration would imply the order the spec refuses to claim.

**Every number here is derived from tab 1's rows** and arrives already computed
in `RankingTabView`; this file computes nothing. J13 reads the macro off this
tab and the per-feature values off tab 1 and asserts the first is the mean of
the non-suppressed second — in the browser, which is where a user would see it
break.

The **presence rate column is reported, never scored** (`SD20`), sitting with
median latency and VRAM under the design's own rule 4: "the tie-breaker you
apply, not one the tool applies".

"How this ranking is computed" — the four numbered rules and the
`--warn-soft` validity footer — renders verbatim, with the **real** `cfg` hash
and corpus label interpolated. A ranking is valid for one config on one corpus
and must be re-run if either moves.

**M27 freezes the signature. V3 writes the body.**
"""

from ra2.services.readmodels import RankingTabView

__all__ = ["render_ranking_tab"]


def render_ranking_tab(*, view: RankingTabView) -> None:
    raise NotImplementedError
