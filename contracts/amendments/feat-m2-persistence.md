# Amendment: `ra2/persistence/session.py`

**RESOLVED at Wave 1 integration.** The symptom below (WAL/FK silently not
applying) was real and correctly diagnosed; the root-cause theory (un-drained
PRAGMA result rows) was not quite right. The lead traced it further: the
actual cause was `_apply_pragmas`'s `isinstance(dbapi_connection,
sqlite3.Connection)` guard, which is `False` for the real async engine's
`AsyncAdapt_aiosqlite_connection` — so the guard returned early on *every*
real connection and none of the three pragmas ever ran (`busy_timeout` only
looked correct because this SQLite build's default already happens to be
5000ms). Fixed by widening the isinstance check to accept both connection
types; no `fetchone()` was needed. The three tests this amendment covered
(`test_journal_mode_is_wal`, `test_foreign_keys_pragma_is_on`,
`test_foreign_keys_are_actually_enforced`) had their `xfail` markers removed
and pass for real. Left below for the record.

## Which file

`ra2/persistence/session.py`, function `_apply_pragmas` (the connect-time
PRAGMA listener bound to every pooled connection).

## Why

Two of the three connect-time PRAGMAs **silently do not take effect** against
the real `aiosqlite` driver phase 1 actually uses
(`sqlalchemy+aiosqlite:///...`), even though the exact same statements work
fine against the plain synchronous `sqlite3` module.

Reproduced outside pytest, against a real temp-file DB (never `:memory:`,
exactly as sw-design.md §11.2 requires for this class of test):

```python
# ra2/persistence/session.py, current body of _apply_pragmas:
cursor = dbapi_connection.cursor()
try:
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
finally:
    cursor.close()
```

Reading the PRAGMAs back immediately afterwards, on the same connection:

```
journal_mode -> 'delete'   # expected 'wal'
foreign_keys -> 0          # expected 1
busy_timeout -> 5000       # correct
```

Root cause: `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=N` both return
a one-row result set (the new value). `PRAGMA foreign_keys=ON` (the setter
form) does not. With the synchronous `sqlite3` driver, issuing another
`execute()` on the same cursor implicitly discards any unread result set, so
not calling `fetchone()` is harmless. With `aiosqlite`, whose `execute()`
dispatches to a worker thread and returns before the statement is fully
drained, **not consuming the pending result row before the next `execute()`
call leaves the connection unable to apply the pragma that produced it** —
`journal_mode` never actually flips to WAL, and because the un-drained
`journal_mode` result is still pending when `foreign_keys=ON` runs, that one
is dropped too. `busy_timeout` — the *last* statement, with nothing queued
after it — happens to apply because there is no next `execute()` to race
against, which is why the FK-enforcement and WAL exit criteria fail while
`busy_timeout` alone passes.

This breaks two invariants sw-design.md §4.4 states as connect-time
guarantees (WAL, `foreign_keys=ON`) for every real (non-`:memory:`)
connection made through `create_engine()` — i.e. the whole app, not just this
branch's tests.

## The exact proposed diff

```diff
--- a/ra2/persistence/session.py
+++ b/ra2/persistence/session.py
@@ def _apply_pragmas(dbapi_connection: Any, _record: Any) -> None:
     cursor = dbapi_connection.cursor()
     try:
-        cursor.execute("PRAGMA journal_mode=WAL")
-        cursor.execute("PRAGMA foreign_keys=ON")
-        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
+        # `journal_mode=WAL` and `busy_timeout=N` both return a one-row
+        # result set (the new value). With the synchronous sqlite3 driver an
+        # unread result is silently discarded by the next execute(); with
+        # aiosqlite it is not, and the pragma that produced it never actually
+        # applies. Draining each such result before the next statement is
+        # required for aiosqlite, harmless for sqlite3.
+        cursor.execute("PRAGMA journal_mode=WAL")
+        cursor.fetchone()
+        cursor.execute("PRAGMA foreign_keys=ON")
+        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
+        cursor.fetchone()
     finally:
         cursor.close()
```

(`foreign_keys=ON` needs no `fetchone()` — the setter form returns no rows —
but it must stay *between* the two statements that do, since only the
statement immediately preceding an unread result is the one that gets
dropped.)

## What I did instead

I could not shim around this from `tests/backend/**`: the whole point of
`tests/backend/persistence/test_session_pragmas.py` is to prove the *real*
`create_engine()` from the frozen `session.py` sets WAL and FK enforcement on
a real file connection. Adding a second, test-only PRAGMA listener to work
around the bug would make the tests pass while leaving the production code
(used by every future service, and by `migrations/env.py`) still broken —
exactly the kind of silent repair CLAUDE.md's Do-NOT list §6 forbids, applied
to test infrastructure instead of a data row.

Two tests are marked `xfail` instead, both in
`tests/backend/persistence/test_session_pragmas.py`:

- `test_journal_mode_is_wal`
- `test_foreign_keys_pragma_is_on`
- `test_foreign_keys_are_actually_enforced`

each `pytest.mark.xfail(reason="amendment: feat/m2-persistence", strict=True)`,
so they will flip to an explicit `XPASS` failure the moment the diff above
lands — a deliberate tripwire so the markers get removed rather than
forgotten. `test_busy_timeout_is_set` is unaffected and asserts real,
currently-correct behaviour.
