"""J14 — mismatch review, as a browser sees it (Z1, plan-phase-5.md §10).

One journey, and it is the last one the MVP needs: **arrive from Results,
tag three rows with three different values, reload, and export.** At the end
of it `mvp-spec.md` §19's criterion 7 — "the mismatch list is browsable,
taggable and exportable, with evidence spans" — has been exercised end to end
by a real browser against a real server.

Three things it proves that no lower layer can:

- **C2's link works from both ends.** `design/results/README.md` asks for a
  mismatch drill-down on the Results feature row; phase 4 had nowhere to point
  it, and this follows it.
- **A tag is written, not held in the page.** The reload is the assertion: the
  three tags come back from the database, through the service, into the DOM.
- **The export carries the review.** The three columns no re-run can reproduce
  are in the file an analyst keeps.

**The corpus is seeded directly into the session server's database**, for the
reason `test_results_j11_to_j13.py` sets out at length: a scored evaluation
needs `extraction`, `score` and `mismatch` rows, and nothing in the product
writes those except the run worker and the scoring pass. The file is named
`test_results_*` for the same reason — it sorts after every `test_j*` file, so
the seeded rows appear once the journeys that create their own database have
finished with it.

**It seeds its own corpus rather than reusing J11-J13's**, which is where this
departs from plan-phase-5.md §10's stated preference. This journey *writes* —
it tags rows and then asserts a tally of exactly three — and a count that
exact cannot depend on what another file did or did not do to a shared corpus.
The suffix and the template version are its own, so the rows stay inert for
every other journey.
"""

import asyncio
import csv
import io
import threading
from itertools import count
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.domain.mismatch import MismatchTag
from ra2.infra.config import Settings
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.persistence.session import create_engine
from ra2.services.export_service import CSV_BOM, CSV_DELIMITER
from ra2.services.scoring_service import ScoringService
from ra2.ui.views.mismatches_view import TAG_LABELS

pytestmark = pytest.mark.e2e

TABLE = '[data-testid="table-mismatches"]'


class _Ids:
    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"j14-mismatch-{next(self._counter):04d}"


@pytest.fixture(scope="session")
def review_evaluation(e2e_settings: Settings, server_url: str) -> ScoredCorpus:
    """One seeded, scored evaluation of this journey's own.

    Same shape as `test_results_j11_to_j13.py`'s, including the thread with its
    own loop — `asyncio.run` cannot re-enter the loop pytest already has
    running, the reason `tests/ui/conftest.py`'s `migrated_db` is synchronous
    too.
    """

    async def _seed() -> ScoredCorpus:
        engine = create_engine(e2e_settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            corpus = await seed_scored_corpus(
                session, suffix="j14", records=40, template_version=9141
            )
            await session.commit()
        scoring = ScoringService(
            session_factory=factory,
            ground_truth=GroundTruthRepository(),
            task_runner=None,  # type: ignore[arg-type]
            clock=None,  # type: ignore[arg-type]
            id_factory=_Ids(),
        )
        for run_id in corpus.run_ids:
            await scoring.score_run(run_id)
        await engine.dispose()
        return corpus

    result: list[ScoredCorpus] = []
    error: list[BaseException] = []

    def _run() -> None:
        try:
            result.append(asyncio.run(_seed()))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join(timeout=120)
    if error:
        raise error[0]
    if not result:
        raise RuntimeError("seeding the review corpus did not finish")
    return result[0]


def _rows(page: Page) -> int:
    return page.locator(f'{TABLE} [data-testid="mismatch-feature"]').count()


def _tag_row(page: Page, index: int, tag: MismatchTag) -> None:
    """Tag one row **from the row**, the way an analyst scanning the list does
    (`Q2`, `P3-D22`) — not through a panel, and not through the API."""
    row = page.locator(f"{TABLE} tbody tr").nth(index)
    row.locator(f'[data-testid="seg-option"]:has-text("{TAG_LABELS[tag]}")').click()
    expect(row.locator('[data-testid="seg-option"][aria-pressed="true"]')).to_have_count(1)


def test_j14_review_a_run_from_results_to_an_exported_csv(
    page: Page, server_url: str, review_evaluation: ScoredCorpus, tmp_path: Path
) -> None:
    """The whole journey, in one test, because it is one workflow."""
    evaluation_id = review_evaluation.evaluation_id

    # --- arrive from Results, by the link the design asks for (C2) -----------
    page.goto(f"{server_url}/results?evaluation={evaluation_id}")
    expect(page.locator('[data-testid="results-tabs"]')).to_be_visible()
    link = page.locator('[data-testid="mismatch-link"]').first
    expect(link).to_be_visible()
    href = link.get_attribute("href") or ""
    assert "run=" in href and "feature=" in href, href
    link.click()

    # --- the list is there, filtered to that run × feature -------------------
    expect(page.locator(TABLE)).to_be_visible()
    expect(page.locator('[data-chip="run"]')).to_contain_text("run 1 · ")
    features = page.locator(f'{TABLE} [data-testid="mismatch-feature"]')
    expect(features).not_to_have_count(0)
    assert len(set(features.all_inner_texts())) == 1, "the deep link filtered to one feature"

    # **The evidence span is on screen** — §19's criterion 7 names it, and Q6
    # settles that it is shown rather than hidden behind a hover.
    expect(page.locator(f'{TABLE} [data-testid="mismatch-span"]').first).to_be_visible()
    # **The anonymisation marking**, on every row that shows that text (§13).
    assert page.locator(f'{TABLE} [data-testid="anonymised-chip"]').count() == _rows(page)

    # --- clear the feature filter, so there is a list to review --------------
    page.click('[data-chip="feature"]')
    page.click('[data-testid="option-feature"][data-option=""]')
    expect(page.locator('[data-chip="feature"]')).to_contain_text("feature · all")
    total = _rows(page)
    assert total >= 3, "this journey tags three rows"

    # --- tag three rows with three different values --------------------------
    for index, tag in enumerate(MismatchTag):
        _tag_row(page, index, tag)

    expect(page.locator(f'{TABLE} [data-testid="seg-option"][aria-pressed="true"]')).to_have_count(
        3
    )

    # --- reload: the tags were written, not held in the page -----------------
    #
    # To the plain route rather than `page.reload()`: the URL is the source of
    # truth on load, so reloading the *deep link* would restore its `feature=`
    # filter and show one feature's rows again. That is the right behaviour — a
    # link is a bookmark — and it is why this step navigates to the address an
    # analyst reviewing the whole run would have.
    page.goto(f"{server_url}/mismatches?evaluation={evaluation_id}")
    expect(page.locator(TABLE)).to_be_visible()
    expect(page.locator(f'{TABLE} [data-testid="seg-option"][aria-pressed="true"]')).to_have_count(
        3
    )
    assert _rows(page) == total, "tagging added or removed a row"

    # --- the tally reads "3 reviewed" ---------------------------------------
    sentences = page.locator('[data-testid="tally-sentence"]').all_inner_texts()
    joined = " · ".join(sentences)
    assert sum(int(s.split()[1]) for s in sentences if s.startswith("of ")) == 3, joined
    # mvp-spec.md §12's own words, not the enum's identifier (C4).
    assert "record error" in joined
    assert "structured_data_error" not in joined

    # --- export: the file carries the review --------------------------------
    with page.expect_download() as downloading:
        page.click('[data-testid="export-csv"]')
    saved = tmp_path / "mismatches.csv"
    downloading.value.save_as(saved)
    raw = saved.read_bytes()

    # UTF-8 **with BOM** — Excel on Windows reads UTF-8 no other way (N3).
    assert raw.startswith(CSV_BOM)
    text = raw.decode("utf-8-sig")
    comment, _, body = text.partition("\r\n")
    assert comment.startswith("# evaluation ")
    assert "3 reviewed" in comment

    reader = csv.reader(io.StringIO(body), delimiter=CSV_DELIMITER)
    header = next(reader)
    assert header[:4] == ["mismatch_id", "record_id", "anonymised", "feature_key"]
    assert header[-3:] == ["analyst_tag", "tagged_at", "note"]
    rows = [row for row in reader if row]

    # The export is the **currently filtered** table, whole — no paging.
    assert len(rows) == total
    tagged = [row for row in rows if row[header.index("analyst_tag")]]
    assert len(tagged) == 3
    assert {row[header.index("analyst_tag")] for row in tagged} == {t.value for t in MismatchTag}
    # And the timestamp travelled with the tag, for every one of them.
    assert all(row[header.index("tagged_at")] for row in tagged)


def test_j14_a_tag_can_be_cleared_and_the_tally_follows(
    page: Page, server_url: str, review_evaluation: ScoredCorpus
) -> None:
    """`Q4`: a judgement made on the wrong row must be correctable, or the
    first mis-click is permanent in the one table a human writes to.

    Runs after the journey above and clears what it wrote, so the two together
    exercise the whole of the review verb.
    """
    page.goto(f"{server_url}/mismatches?evaluation={review_evaluation.evaluation_id}")
    expect(page.locator(TABLE)).to_be_visible()
    pressed = page.locator(f'{TABLE} [data-testid="seg-option"][aria-pressed="true"]')
    expect(pressed).to_have_count(3)

    for _ in range(3):
        page.locator(f'{TABLE} [data-testid="seg-clear"]:not([disabled])').first.click()
        page.wait_for_timeout(200)

    expect(pressed).to_have_count(0)
    sentences = page.locator('[data-testid="tally-sentence"]').all_inner_texts()
    assert all(not s.startswith("of ") for s in sentences), sentences
