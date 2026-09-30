# NEW — fix-e4-d8-f6-real-or-synthetic. Not frozen.
"""Whether a corpus's keys were invented here rather than delivered (risk D8).

The synthetic deliveries this project writes share one key shape.
`generate_hazards.uid()` and `seed_dev._uid()` both build a key as a short hex
tag followed by a zero-padded decimal number: `a1` + `000…0017`. A delivered
key is 32 random hex characters.

The shape is decisive, not a heuristic, because of the padding. A key with at
most four tag characters and then **ten zeros in a row** has about one chance
in 10^12 of being random hex. Every record of a corpus has to match before the
corpus counts as invented, so a real corpus of any size stays real.

This is **not** the same test as `scripts/check_no_real_data.py`'s
`_was_invented`. That one screens files about to be committed, where a false
"invented" lets a real delivery into git, and it counts distinct characters
over a sample. This one reads every key of a corpus at freeze, and a false
"invented" would hide a real ranking's verdict. Both err towards *real*.
"""

import re
from collections.abc import Iterable
from typing import Final

__all__ = ["INVENTED_KEY", "all_invented", "is_invented_key"]

#: A short hex tag, ten zeros, then the rest of a decimal number: 32 in all.
INVENTED_KEY: Final = re.compile(r"[0-9a-f]{1,4}0{10}[0-9]{0,21}", re.IGNORECASE)


def is_invented_key(key: str) -> bool:
    """Could this project's own fixture or seed code have written `key`?"""
    return len(key) == 32 and INVENTED_KEY.fullmatch(key) is not None


def all_invented(keys: Iterable[str]) -> bool:
    """Every key invented, and at least one key. An empty corpus proves nothing."""
    seen = False
    for key in keys:
        if not is_invented_key(key):
            return False
        seen = True
    return seen
