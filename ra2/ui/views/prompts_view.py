# STUB — bodies owned by L1 (feat/p3-prompts-view, phase 3 Wave 4).
"""Prompts view — the wording around the feature descriptions, versioned.

`design/prompt-evaluation/README.md` §1 (`PromptTemplate - A source.dc.html`):
master/detail, identical in structure to Codelists and Features. The version
list is capped at **10 rows / 530px** with the standard pagination row, then
two reference strips ("Slots available" and the slot table); the editor
carries the fingerprint block, the Source card with inline slot highlighting
and its `--warn-soft` copy-on-write footer, and the Resolved card capped at
**210px**.

The three rules that shape every view here are unchanged:

1. **No business logic** (CLAUDE.md #7) — every version, count, fingerprint
   and validation message arrives from `PromptService`.
2. **No module-level mutable state** (#8) — the selected version and the page
   live in `app.storage.client`.
3. **Services in-process as Python** — no HTTP call to this app's own API, and
   no session or ORM object crosses into this file.

L1 also flips this view's own `built` flag in `ui/shell.py` and adds its own
line to `views/register_all` — **those two lines and nothing else** in either
file (plan-phase-3.md §6.1).
"""

from ra2.services.container import Services

__all__ = ["register"]


def register(services: Services) -> None:
    """Register `/prompts`."""
    raise NotImplementedError
