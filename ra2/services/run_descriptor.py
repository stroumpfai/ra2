"""The identity line every Results and Mismatches board carries.

`design/results/README.md` §2 draws it as a mono 11px descriptor —
`Corpus 2026-09-02 · 4 978 records · 3 models` — beside an "Evaluation run"
pill and a `cfg 4f9a2c1e` chip, and states the rule this module exists to
keep: **every tab must carry it**. `readmodels.RunDescriptorView`'s own
docstring puts it more sharply: *"a score without its config is not a
result"*.

**Why this is a module and not a function in one of the three services.** It
was a function in *each* of them — `results_service._descriptor`,
`ranking_service._ranking_descriptor` and `mismatch_service._descriptor`,
three byte-identical stubs returning `record_count=0`, the corpus **id** where
the label goes and the feature config **id** where the design asks for a hash.
So every board read `Corpus 01a0bebb-… · 0 records`, and a fix to any one of
them would have left the other two wrong. Triplication is why the stub
survived four phases; one owner is the fix, not three corrections.

The read had to grow a session because the honest values are not on
`evaluation`: the count and the label live on `corpus`, and the `cfg` hash is
taken over the `evaluation_feature` snapshot — the frozen per-feature
fingerprints, which is what makes the chip mean "these two boards asked the
same thing" rather than "these two rows have different ids".
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.fingerprint import compute_set_fingerprint
from ra2.domain.ids import EvaluationId
from ra2.persistence.models import Corpus, Evaluation, EvaluationFeature, Run
from ra2.services.readmodels import RunDescriptorView

__all__ = ["build_descriptor"]

#: What the label falls back to when the corpus row is gone.
#:
#: **Defensive, not live.** `Evaluation.corpus_id` is `ondelete=RESTRICT`, so
#: the database refuses to remove a corpus an evaluation still cites — which is
#: the guarantee that lets a board name its corpus at all. The branch exists
#: because `session.get` returns `Corpus | None` and inventing a value for the
#: impossible case is worse than naming it; the day that FK is relaxed,
#: `test_the_corpus_cannot_be_removed_out_from_under_a_board` is what says so.
_MISSING_CORPUS = "(corpus removed)"


async def build_descriptor(
    session: AsyncSession, evaluation: Evaluation, runs: Sequence[Run]
) -> RunDescriptorView:
    """One descriptor, read through the caller's own session.

    Takes the session rather than a factory, for the reason every protocol in
    `services/protocols.py` does: the caller owns the transaction boundary, and
    these reads belong inside the same one that produced `evaluation` and
    `runs` — a board whose header came from a different snapshot than its
    numbers is the inconsistency `EvaluationView` exists to prevent.
    """
    corpus = await session.get(Corpus, evaluation.corpus_id)
    fingerprints = await session.scalars(
        select(EvaluationFeature.fingerprint).where(
            EvaluationFeature.evaluation_id == evaluation.id
        )
    )
    return RunDescriptorView(
        evaluation_id=EvaluationId(evaluation.id),
        corpus_label=_MISSING_CORPUS if corpus is None else corpus.name,
        # From the corpus row, which has carried it since phase 1. It was
        # hardcoded `0`, so every board said "0 records" over numbers computed
        # from thousands of them.
        record_count=0 if corpus is None else corpus.record_count,
        model_count=len(runs),
        config_fingerprint=compute_set_fingerprint(fingerprints.all()),
        is_dev=evaluation.is_dev,
        min_cell_count=evaluation.min_cell_count,
    )
