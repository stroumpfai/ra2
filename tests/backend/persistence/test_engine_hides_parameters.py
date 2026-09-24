"""A database error must not publish the row it failed on (risk-assesment.md A5).

`create_engine` passes `hide_parameters=True`. SQLAlchemy's default is `False`,
which puts the bound parameters of the failing statement into `str(exc)` — and
for an insert over `record` those parameters are `text_raw` and `unfall_uid`,
both named on `data-handling.md` §5.1's *"may never appear"* list.

That string is not private. `run_service._error_text` is
`f"{type(exc).__name__}: {exc}"` for every exception that is not a
`FeatureValidationError`; it is persisted as `run.error`, rendered by the runs
table's log action, and **written to stderr**. So a constraint violation put
the narrative into the one artefact `infra/logging.py` exists to keep safe to
paste into a bug report — at exactly the moment somebody is asked to look.

**Why this is a separate test rather than a case in
`test_run_log_carries_no_data.py`.** That file drives a *successful* run and
inspects what the log said. It is correct and complete for what it inspects,
and this defect lived one layer below it: the channel that can carry content is
the one channel a passing run never opens. The companion case there provokes a
failure through the service; this one pins the engine flag that makes it safe,
against the real migrated schema.

**The control is the point.** An assertion that a string is absent passes just
as well when nothing was planted, when the statement never failed, or when the
error text came back empty. `test_the_parameters_would_otherwise_be_exposed`
runs the same insert through an engine built the way SQLAlchemy defaults, and
fails if the narrative is *not* there — so the search is proven able to find
what the other test is proving absent (§8.1, §8.6; the idiom
`test_discard_erasure.py` established).
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ra2.infra.config import Settings
from ra2.persistence.session import create_engine

pytestmark = pytest.mark.backend

#: Synthesised, never real (CLAUDE.md #13). Distinctive enough that finding it
#: in the error text is unambiguous, and shaped like what `record` actually
#: holds: a narrative and a delivery key.
NARRATIVE = "SYNTHETIC-NARRATIVE Lenker A kollidierte mit Fussgaenger B."
UNFALL_UID = "SYNTHETICUID0000000000000000abcd"

#: `language` is NOT NULL and is omitted, so this fails inside SQLite with the
#: narrative and the key already bound. A NOT NULL violation is used rather
#: than the unique constraint on `(corpus_id, unfall_uid)` because it needs no
#: pre-existing row and therefore no valid `corpus` behind it: one statement,
#: one failure, and the same `IntegrityError` either way. What is under test is
#: what the exception *says*, not which constraint said it.
_INSERT = sa.text(
    "INSERT INTO record (id, corpus_id, unfall_uid, text_raw, "
    " language_confidence, text_anonymised_flag) "
    "VALUES (:id, :corpus_id, :unfall_uid, :text_raw, 1.0, 0)"
)
_PARAMS = {
    "id": "SYNTHETIC-RECORD-1",
    "corpus_id": "SYNTHETIC-CORPUS-1",
    "unfall_uid": UNFALL_UID,
    "text_raw": NARRATIVE,
}


async def _error_text_of_failed_insert(engine: AsyncEngine) -> str:
    """Exactly what `run_service._error_text` would record for this exception."""
    async with engine.connect() as conn:
        with pytest.raises(IntegrityError) as caught:
            await conn.execute(_INSERT, _PARAMS)
    return f"{type(caught.value).__name__}: {caught.value}"


async def test_a_failed_insert_does_not_expose_the_row_it_failed_on(
    migrated_engine: AsyncEngine,
) -> None:
    """The project's own engine, the real schema, the real `IntegrityError`."""
    text = await _error_text_of_failed_insert(migrated_engine)

    # The error must still be worth reading — a suppressed exception string
    # would pass the two assertions below for the wrong reason.
    assert "IntegrityError" in text
    assert "record" in text
    assert NARRATIVE not in text, f"narrative reached run.error: {text}"
    assert UNFALL_UID not in text, f"a delivery key reached run.error: {text}"


async def test_the_parameters_would_otherwise_be_exposed(
    run_upgrade_head: Settings,
) -> None:
    """The positive control: the same insert, through an engine built the way
    SQLAlchemy defaults. Both values are present, which is what makes the
    absence asserted above a result rather than a tautology.

    This is also the regression guard with teeth. If `hide_parameters=True` is
    ever dropped from `create_engine`, the test above starts failing — and this
    one says why in one line.
    """
    engine = create_async_engine(run_upgrade_head.database_url, future=True)
    try:
        text = await _error_text_of_failed_insert(engine)
    finally:
        await engine.dispose()

    assert NARRATIVE in text
    assert UNFALL_UID in text


async def test_the_flag_is_set_on_the_engine_the_app_builds(
    run_upgrade_head: Settings,
) -> None:
    """Read back off `create_engine` itself, so the property is pinned to the
    factory rather than to the fixture that happens to call it."""
    engine = create_engine(run_upgrade_head.database_url)
    try:
        assert engine.sync_engine.hide_parameters is True
    finally:
        await engine.dispose()
