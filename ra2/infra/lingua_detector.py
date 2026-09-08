# STUB — bodies owned by A4 (feat/m2-infra). Not frozen.
"""`LanguageDetector` implementations (D9, mvp-spec.md §4.5).

`lingua-py`: pure Python, no model download, strong on short text. Low
confidence is stored as `mixed`, **never forced to a winner**.
"""

import lingua

from ra2.domain.language import DEFAULT_MIN_CONFIDENCE, Language, LanguageGuess

__all__ = ["LinguaDetector", "StubDetector"]

#: The four languages mvp-spec.md §4.5 needs a real guess for. `lingua` has
#: no Romansh model, so `Language.RM` is never returned by this detector —
#: only the stored vocabulary has to be able to hold it.
_LINGUA_TO_LANGUAGE: dict[lingua.Language, Language] = {
    lingua.Language.GERMAN: Language.DE,
    lingua.Language.FRENCH: Language.FR,
    lingua.Language.ITALIAN: Language.IT,
    lingua.Language.ENGLISH: Language.EN,
}


class LinguaDetector:
    """The production detector, behind the `LanguageDetector` seam.

    Confidence below `min_confidence` is reported as `Language.MIXED`,
    **never** forced to the top-ranked language (mvp-spec.md §4.5, D9) — the
    raw confidence is still returned so the threshold can be revisited later
    without a re-run.
    """

    def __init__(self, *, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> None:
        self._min_confidence = min_confidence
        self._detector = lingua.LanguageDetectorBuilder.from_languages(*_LINGUA_TO_LANGUAGE).build()

    def detect(self, text: str) -> LanguageGuess:
        stripped = text.strip()
        if not stripped:
            return LanguageGuess(language=Language.UNKNOWN, confidence=0.0)

        values = self._detector.compute_language_confidence_values(stripped)
        top = values[0]
        if top.value < self._min_confidence:
            return LanguageGuess(language=Language.MIXED, confidence=top.value)
        return LanguageGuess(language=_LINGUA_TO_LANGUAGE[top.language], confidence=top.value)


class StubDetector:
    """Deterministic stand-in for tests that do not exercise detection."""

    def __init__(self, guess: LanguageGuess) -> None:
        self._guess = guess

    def detect(self, text: str) -> LanguageGuess:
        return self._guess
