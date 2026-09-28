"""Settings an analyst changes from the product (sw-design.md SD43).

Two, and only two: the LLM endpoint and the per-call timeout — what the Models
card's settings dialog draws. Every other setting stays an environment variable
(`infra/config.py`) or a column on the row it belongs to (`SD36`, `SD42`).

**The vocabulary lives here** because three packages need it and `domain` is
the one they may all read: the service validates a save against it, the
repository keys rows by it, and `ui/` renders a refusal from it without
reaching `infra` — the move `is_loopback_url` and `REASONING_EFFORTS` made.

**A refusal is a code, not a sentence** (CLAUDE.md: findings, not prose). The
wording lives in one rendering table in `ui/`; tests assert on the code.
"""

from enum import StrEnum

from ra2.domain.llm import ProbeCode, classify_endpoint

__all__ = ["SettingKey", "SettingRefusal", "endpoint_refusal", "timeout_refusal"]


class SettingKey(StrEnum):
    """The closed set of keys `app_setting` may hold.

    A key this build does not know is **ignored** on read, never an error: a
    database written by a newer build must still open (`SettingsService`).
    """

    LLM_BASE_URL = "llm_base_url"
    LLM_TIMEOUT_S = "llm_timeout_s"


class SettingRefusal(StrEnum):
    """Why a value may not be stored — or, read back, may not be used."""

    #: N1. A host outside `LOOPBACK_HOSTS`, compared literally, no DNS —
    #: `classify_endpoint`'s rule, and the same one `require_loopback` applies
    #: at construction. **No opt-out** (mvp-spec.md §19.10).
    ENDPOINT_NOT_LOOPBACK = "endpoint_not_loopback"
    #: Not a URL that parses at all. Refused as firmly as a LAN address:
    #: neither is an endpoint this code can promise stays on the host.
    ENDPOINT_MALFORMED = "endpoint_malformed"
    #: A per-call bound below one second is not a bound; it is every call
    #: timing out.
    TIMEOUT_NOT_POSITIVE = "timeout_not_positive"


def endpoint_refusal(endpoint: str) -> SettingRefusal | None:
    """Why `endpoint` may not be stored, or `None` when it may.

    Delegates to `classify_endpoint`, **the one statement of the rule**: the
    dialog's inline check, the connection test, the client's construction and
    this refusal must never disagree about what loopback is.
    """
    code = classify_endpoint(endpoint)
    if code is None:
        return None
    if code is ProbeCode.MALFORMED_URL:
        return SettingRefusal.ENDPOINT_MALFORMED
    return SettingRefusal.ENDPOINT_NOT_LOOPBACK


def timeout_refusal(timeout_s: int) -> SettingRefusal | None:
    """Why `timeout_s` may not be stored, or `None` when it may."""
    return None if timeout_s >= 1 else SettingRefusal.TIMEOUT_NOT_POSITIVE
