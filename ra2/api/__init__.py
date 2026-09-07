"""FastAPI adapter. May import `services` and `domain` (sw-design.md §1.1).

The API exists so scripts, tests and Playwright can drive the same use cases
without a browser (SD10). `api` never imports `ui`.
"""
