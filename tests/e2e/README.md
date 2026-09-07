# Layer 4 — E2E / journeys

`pytest-playwright`, **Chromium**, Python. A session fixture starts a real
server on a random port with a temp `RA2_DATA_DIR` and a `FrozenClock` +
`SeededFactory` injected through `create_app()`. Seeding beyond the journey
under test goes through `/api/v1`. Traces and screenshots on failure.

| # | Journey |
|---|---|
| J1 | Delivery to census |
| J2 | Blocking validation — no corpus row survives |
| J3 | Immutability — `LOCKED · 1 eval`, `DELETE` returns 409 |
| J4 | Layout invariants at 1024 / 1440 / 1920 px |
| J5 | Navigation, keyboard-reachable, visible focus ring |
| J6 | **No egress** — any request to another host fails the test (N1) |

Screenshot comparison is optional and non-gating (`@pytest.mark.visual`,
Linux/Chromium only).

Owner: **A5** for `conftest.py`, `test_j4_layout.py`, `test_j5_nav.py`,
`test_j6_egress.py`; J1-J3 land with the views that make them pass.
