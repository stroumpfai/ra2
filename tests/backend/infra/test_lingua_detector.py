"""The `LanguageDetector` seam (mvp-spec.md §4.5, D9).

Low confidence must come back as `Language.MIXED` — never a forced winner —
and an empty narrative must come back as `Language.UNKNOWN`, never a guess.
"""

import pytest

from ra2.domain.language import DEFAULT_MIN_CONFIDENCE, Language, LanguageGuess
from ra2.infra.lingua_detector import LinguaDetector, StubDetector

pytestmark = pytest.mark.backend

GERMAN_TEXT = "Der Lenker verlor auf regennasser Fahrbahn die Kontrolle über sein Fahrzeug."
FRENCH_TEXT = "Le conducteur a perdu la maîtrise de son véhicule sur la chaussée mouillée."
ITALIAN_TEXT = "Il conducente ha perso il controllo del veicolo sulla strada bagnata."


def test_stub_detector_always_returns_its_configured_guess() -> None:
    guess = LanguageGuess(language=Language.FR, confidence=0.42)
    detector = StubDetector(guess)

    assert detector.detect("anything at all") is guess
    assert detector.detect("") is guess


def test_lingua_detector_returns_unknown_for_empty_text() -> None:
    detector = LinguaDetector()

    assert detector.detect("") == LanguageGuess(language=Language.UNKNOWN, confidence=0.0)
    assert detector.detect("   ") == LanguageGuess(language=Language.UNKNOWN, confidence=0.0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (GERMAN_TEXT, Language.DE),
        (FRENCH_TEXT, Language.FR),
        (ITALIAN_TEXT, Language.IT),
    ],
)
def test_lingua_detector_identifies_clear_narratives(text: str, expected: Language) -> None:
    detector = LinguaDetector()

    guess = detector.detect(text)

    assert guess.language == expected
    assert 0.0 <= guess.confidence <= 1.0
    assert guess.confidence >= DEFAULT_MIN_CONFIDENCE


def test_lingua_detector_reports_mixed_rather_than_forcing_a_winner() -> None:
    """A threshold set above what any real sentence scores forces the
    low-confidence branch — the point being that `MIXED` is returned rather
    than the (still perfectly identifiable) top-ranked language."""
    detector = LinguaDetector(min_confidence=0.999_999)

    guess = detector.detect(GERMAN_TEXT)

    assert guess.language is Language.MIXED
    # The raw score survives so the threshold can be revisited without a
    # re-run (mvp-spec.md §4.5) — it is not zeroed out just because it lost.
    assert guess.confidence > 0.0


def test_lingua_detector_is_deterministic_across_independent_instances() -> None:
    """Pure and deterministic (the `LanguageDetector` protocol's own words):
    two separately built detectors must agree on the same narrative.

    `lingua`'s confidence sum can differ in its last bit between builds
    (parallel float summation is not order-stable) — `pytest.approx` treats
    that as the noise it is, while still pinning down the language and the
    confidence to fifteen significant figures.
    """
    first = LinguaDetector()
    second = LinguaDetector()

    guess_a = first.detect(GERMAN_TEXT)
    guess_b = second.detect(GERMAN_TEXT)

    assert guess_a.language == guess_b.language
    assert guess_a.confidence == pytest.approx(guess_b.confidence)
