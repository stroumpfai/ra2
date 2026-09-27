"""What may be stored as a setting, as pure domain (sw-design.md SD43).

`endpoint_refusal` must agree with `classify_endpoint` — the one statement of
the loopback rule — on every input, because the settings save is its fourth
caller beside the startup guard, the Test button and the dialog's Save gate. A
fourth caller with its own idea of loopback is how the rule would drift.

**There is deliberately no opt-out**, so there is deliberately no test for one.
"""

import pytest

from ra2.domain.llm import ProbeCode, classify_endpoint
from ra2.domain.settings import SettingKey, SettingRefusal, endpoint_refusal, timeout_refusal

LOOPBACK = [
    "http://127.0.0.1:11434/v1",
    "http://localhost:11434/v1",
    "http://[::1]:11434/v1",
    "http://LOCALHOST:8000/v1",
]
OFF_HOST = [
    "http://0.0.0.0:11434/v1",
    "http://192.168.1.10:11434/v1",
    "http://ollama.internal:11434/v1",
    # Resolves to 127.0.0.1 through public DNS today; compared literally, so
    # refused — it resolves wherever its owner points it tomorrow.
    "http://127.0.0.1.nip.io:11434/v1",
]
MALFORMED = ["", "not a url", "http://127.0.0.1:notaport/v1", "ftp://127.0.0.1/v1"]


@pytest.mark.parametrize("endpoint", LOOPBACK)
def test_a_loopback_endpoint_may_be_stored(endpoint: str) -> None:
    assert endpoint_refusal(endpoint) is None


@pytest.mark.parametrize("endpoint", OFF_HOST)
def test_an_off_host_endpoint_is_refused_as_not_loopback(endpoint: str) -> None:
    assert endpoint_refusal(endpoint) is SettingRefusal.ENDPOINT_NOT_LOOPBACK


@pytest.mark.parametrize("endpoint", MALFORMED)
def test_a_malformed_endpoint_is_refused_as_malformed(endpoint: str) -> None:
    assert endpoint_refusal(endpoint) is SettingRefusal.ENDPOINT_MALFORMED


@pytest.mark.parametrize("endpoint", LOOPBACK + OFF_HOST + MALFORMED)
def test_the_refusal_agrees_with_the_one_statement_of_the_rule(endpoint: str) -> None:
    """Stored exactly when `classify_endpoint` would let RA2 dial it, and the
    malformed case kept apart only as a diagnosis — both are refusals."""
    code = classify_endpoint(endpoint)
    refusal = endpoint_refusal(endpoint)
    assert (refusal is None) == (code is None)
    assert (refusal is SettingRefusal.ENDPOINT_MALFORMED) == (code is ProbeCode.MALFORMED_URL)


@pytest.mark.parametrize("timeout_s", [1, 45, 600, 3600])
def test_a_timeout_of_a_second_or_more_may_be_stored(timeout_s: int) -> None:
    assert timeout_refusal(timeout_s) is None


@pytest.mark.parametrize("timeout_s", [0, -1, -600])
def test_a_timeout_below_a_second_is_refused(timeout_s: int) -> None:
    assert timeout_refusal(timeout_s) is SettingRefusal.TIMEOUT_NOT_POSITIVE


def test_the_keys_are_the_two_the_dialog_draws() -> None:
    """Two, and only two (SD43). A third is a decision, recorded in the design,
    not a line added here."""
    assert {key.value for key in SettingKey} == {"llm_base_url", "llm_timeout_s"}
