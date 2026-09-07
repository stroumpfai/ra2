"""NiceGUI adapter. May import `services` and `domain` only (sw-design.md §1.1).

The UI holds **no business logic**: sorting, filtering, paging, derived counts
and validation are service calls or domain functions. A view function that
computes a rate is a bug (§8.1).

It calls services **in-process as Python**, never over HTTP to its own API.
"""
