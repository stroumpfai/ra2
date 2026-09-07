# STUB — bodies owned by A4 (feat/m2-infra). Not frozen.
"""`LanguageDetector` implementations (D9, mvp-spec.md §4.5).

`lingua-py`: pure Python, no model download, strong on short text. Low
confidence is stored as `mixed`, **never forced to a winner**.
"""

from ra2.domain.language import DEFAULT_MIN_CONFIDENCE, LanguageGuess

__all__ = ["LinguaDetector", "StubDetector"]


class LinguaDetector:
    """The production detector. A4 wires `lingua` in behind this class."""

    def __init__(self, *, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> None:
        self._min_confidence = min_confidence

    def detect(self, text: str) -> LanguageGuess:
        raise NotImplementedError


class StubDetector:
    """Deterministic stand-in for tests that do not exercise detection."""

    def __init__(self, guess: LanguageGuess) -> None:
        self._guess = guess

    def detect(self, text: str) -> LanguageGuess:
        return self._guess
