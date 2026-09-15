"""The loopback rule, as pure domain (N1, mvp-spec.md §19.10).

`classify_endpoint` is the **one** statement of "may RA2 dial this?". It has
three callers that must never disagree: `require_loopback` (the startup guard),
`OllamaEndpointProber` (the settings dialog's Test button) and
`is_loopback_url` (the same dialog's Save gate). This layer pins the rule
itself; the socket-never-opened claim is pinned one layer out, in
`tests/backend/infra/test_ollama_client.py`.

**There is deliberately no opt-out**, so there is deliberately no test for one:
an opt-out is how "no data leaves the host" becomes "no data leaves the host by
default".
"""

import pytest

from ra2.domain.llm import (
    EndpointStatus,
    LlmEndpointError,
    ProbeCode,
    classify_endpoint,
    is_loopback_url,
    require_loopback,
)

#: Every one of these must be dialable. `[::1]` bracketed and `LOCALHOST`
#: shouting are here because `urlsplit` normalises both and a hand-rolled
#: string comparison would not.
ACCEPTED = [
    "http://127.0.0.1:11434/v1",
    "http://127.0.0.1:11434",
    "http://localhost:11434/v1",
    "HTTP://LOCALHOST/v1",
    "https://127.0.0.1:11434/v1",
    "http://[::1]:11434/v1",
]

#: Why each is refused. The distinction is a **diagnosis** for the dialog, not
#: two policies — `require_loopback` refuses both identically.
REFUSED = [
    # Off-host: the case N1 exists for. A copied `.env` or a typo.
    ("http://192.168.1.5:11434/v1", ProbeCode.REFUSED_NOT_LOOPBACK),
    ("http://10.0.0.1/v1", ProbeCode.REFUSED_NOT_LOOPBACK),
    ("http://ollama.example.com/v1", ProbeCode.REFUSED_NOT_LOOPBACK),
    # `127.0.0.1.example.com` resolves wherever its owner points it. A prefix
    # match instead of a host comparison would wave this through.
    ("http://127.0.0.1.example.com/v1", ProbeCode.REFUSED_NOT_LOOPBACK),
    # Credentials in the authority do not move the host.
    ("http://127.0.0.1@evil.example.com/v1", ProbeCode.REFUSED_NOT_LOOPBACK),
    # Not http(s): refused rather than interpreted.
    ("ftp://127.0.0.1", ProbeCode.MALFORMED_URL),
    ("file:///etc/passwd", ProbeCode.MALFORMED_URL),
    # `urlsplit` reads a bare host:port as a scheme, so it has no host at all.
    ("127.0.0.1:11434", ProbeCode.MALFORMED_URL),
    ("", ProbeCode.MALFORMED_URL),
    # A port `.hostname` happily ignores and `.port` raises on.
    ("http://127.0.0.1:notaport/v1", ProbeCode.MALFORMED_URL),
    ("http://127.0.0.1:99999/v1", ProbeCode.MALFORMED_URL),
]


@pytest.mark.parametrize("url", ACCEPTED)
def test_loopback_urls_are_accepted(url: str) -> None:
    assert classify_endpoint(url) is None
    assert is_loopback_url(url) is True
    require_loopback(url)  # does not raise


@pytest.mark.parametrize(("url", "code"), REFUSED)
def test_refused_urls_are_classified_by_cause(url: str, code: ProbeCode) -> None:
    assert classify_endpoint(url) is code
    assert is_loopback_url(url) is False


@pytest.mark.parametrize("url", [url for url, _ in REFUSED])
def test_require_loopback_refuses_every_cause_identically(url: str) -> None:
    """Both diagnoses raise, and both raise `REFUSED_NOT_LOOPBACK`.

    This is what makes moving the rule down out of `infra/` a no-op at the
    startup guard: an unparseable URL was refused with that status before, and
    still is. The finer `MALFORMED_URL` exists for the dialog, which can act
    on it, not for the guard, which cannot.
    """
    with pytest.raises(LlmEndpointError) as caught:
        require_loopback(url)
    assert caught.value.status is EndpointStatus.REFUSED_NOT_LOOPBACK
    assert caught.value.base_url == url


def test_the_rule_never_resolves_a_name() -> None:
    """A hostname that resolves to loopback is still refused.

    The guarantee has to be readable from the configuration alone: a name
    resolving to 127.0.0.1 on this machine today resolves wherever its owner
    points it tomorrow. `localhost` is accepted because it is in the literal
    allowlist, not because anything looked it up.
    """
    assert classify_endpoint("http://localhost.localdomain:11434/v1") is (
        ProbeCode.REFUSED_NOT_LOOPBACK
    )
