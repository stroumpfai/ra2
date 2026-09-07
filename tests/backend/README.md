# Layer 2 — backend

Services and repositories against a **real temporary file SQLite** — not
`:memory:`, because WAL and cross-connection behaviour must be exercised —
plus the API through `httpx.ASGITransport` with no network.

- The schema fixture runs **`alembic upgrade head`**, never
  `metadata.create_all` (sw-design.md §12.10). Every migration therefore runs
  on every backend run.
- A dedicated test runs `alembic check` and fails when models and migrations
  have drifted.

Owners: `persistence/` → **A3**, `infra/` → **A4**,
`services/{delivery,corpus}/` → **B1**, `services/{census,export}/` → **B2**,
`api/{deliveries,corpora}/` → **C1**, `api/{census,tasks}/` → **C2**.
