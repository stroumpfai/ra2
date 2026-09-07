# FROZEN — see CONTRACTS.md
"""Per-record language detection seam (mvp-spec.md §4.5, D9).

Language is detected **per record, from the narrative**, and stored with a
confidence score. It is **never** inferred from the source file (sw-design.md
§12.5). Low confidence is stored as `mixed`, not forced to a winner.

`lingua-py` is the phase-1 implementation (`ra2.infra.lingua_detector`), behind
this one-function seam so it can be swapped without touching the import.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

__all__ = ["DEFAULT_MIN_CONFIDENCE", "Language", "LanguageDetector", "LanguageGuess"]


class Language(StrEnum):
    """The vocabulary stored in `record.language`.

    Stored as its string value. The column is a plain string, not a database
    enum, so a fourth language in a future delivery is a value, not a migration.
    """

    DE = "de"
    FR = "fr"
    IT = "it"
    RM = "rm"
    EN = "en"
    #: Confidence below the detector's floor — mvp-spec.md §4.5 is explicit that
    #: this is stored rather than forced to a winner.
    MIXED = "mixed"
    #: No narrative to detect from (an `unfall` row with no text).
    UNKNOWN = "und"


#: Below this, the detector returns `Language.MIXED`.
DEFAULT_MIN_CONFIDENCE: Final = 0.5


@dataclass(frozen=True, slots=True)
class LanguageGuess:
    """One detection result, stored on `record` as `(language, confidence)`."""

    language: Language
    #: In [0, 1]. Stored verbatim even when `language` is `MIXED`, so the
    #: threshold can be revisited without a re-run.
    confidence: float


@runtime_checkable
class LanguageDetector(Protocol):
    """Injected into `CorpusService`; never constructed at a call site."""

    def detect(self, text: str) -> LanguageGuess:
        """Guess the language of one narrative.

        Must return `Language.UNKNOWN` for empty text and `Language.MIXED`
        rather than a forced winner when confidence is low. Pure and
        deterministic: the same text always gives the same guess.
        """
        ...
