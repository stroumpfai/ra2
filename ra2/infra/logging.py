"""The one place RA2 configures logging — stderr, and nothing else.

`data-handling.md` §5 records the constraint this module is bounded by: RA2
keeps **no audit trail**, and the reason given is the right one — *"keeping
narrative text out of log files"*. That reason is about **content**, not about
the existence of a log, and the distinction is what this module exists to hold.

So the rule is narrow and it is the rule, not a preference:

    A log record may carry generated ids, counts, statuses, model tags and
    durations. It may **never** carry narrative, prompt text, model output, a
    column value, a file name, or `unfall_uid` — anything that came out of a
    delivery.

Three things follow, and each is a reason the rule is worth more than a note:

- **Nothing is persisted.** stderr only. There is no log file, so there is
  nothing for `just reset` to wipe, nothing new under `RA2_DATA_DIR`, and
  nothing a discard leaves behind. A closed terminal is the retention policy.
- **An agent may read it.** CLAUDE.md #13 forbids opening `data/` or
  `RA2_DATA_DIR` because a transcript leaves this machine. A log that carries
  only ids and counts is safe to paste into a bug report, and that is precisely
  what a twenty-six-minute run needed and did not have.
- **It is testable.** `tests/backend/services/run/test_run_log_carries_no_data.py`
  drives a real run against a fixture whose narrative and keys it knows, and
  fails if either reaches a log record. A line that carries content is a defect
  with a test behind it, not a review comment.

`OLLAMA_DEBUG` remains forbidden (`data-handling.md` §5): the model server
writes *prompt content* to its own log, outside all of this, and nothing here
changes that.
"""

import logging
import sys
from typing import Final

__all__ = ["LOGGER_NAME", "configure_logging"]

#: The package logger every module logs through, via
#: `logging.getLogger(__name__)`. Configuring this one and not the root is
#: deliberate: uvicorn owns its own loggers and RA2 has no business changing
#: what they do.
LOGGER_NAME: Final = "ra2"

#: Time, level, module, message. No process id and no thread name — one
#: process, one worker (§15 F7), so both would be a constant column.
_FORMAT: Final = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT: Final = "%H:%M:%S"

#: Marks the handler as ours, so a second call replaces it rather than
#: stacking a duplicate. `create_app()` runs once per process in production
#: and once per fixture in the E2E suite.
_HANDLER_NAME: Final = "ra2-stderr"


def configure_logging(level: str = "INFO") -> None:
    """Send the `ra2` logger to stderr at `level`. Idempotent.

    Called from the composition root and nowhere else. `propagate` is turned
    off so that a root handler installed by anything else — a test runner, an
    embedding process — cannot produce every line twice.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level.upper())
    logger.propagate = False
    for existing in list(logger.handlers):
        if existing.name == _HANDLER_NAME:
            logger.removeHandler(existing)
    handler = logging.StreamHandler(sys.stderr)
    handler.name = _HANDLER_NAME
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(handler)
