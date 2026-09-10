"""Do the canonical column sets still match the real sample headers?

`@pytest.mark.realdata`: reads `data/RADIS-Export/samples/` and
`data/ASTRANA-Export/samples/` when present on the host and **skips when
absent** (sw-design.md §11.4). These tests are never required to pass in CI,
and CI never has the files — `data/` is gitignored because the VUM delivery
is classified, is not anonymised, and must stay on the host (§12.11).

What this checks, and what it deliberately does not:

- It reads **header lines only**. No data row is opened, decoded, asserted on,
  printed or written anywhere. The whole point of the canonical sets living in
  `headers.py` is that the *names* are schema and the *values* never leave the
  host.
- It never reads a filename for meaning. Which kind a sample is comes from
  `classify_header`, exactly as production does (SD5, §12.5) — so the test also
  proves the matcher works on the genuine article, not only on fixtures.
"""

import csv
from pathlib import Path

import pytest

from ra2.domain.delivery import Encoding, FileKind
from ra2.domain.parsing.dialect import detect_dialect
from ra2.domain.parsing.encoding import decode_strict
from ra2.domain.parsing.headers import CANONICAL_COLUMN_SETS, classify_header, normalise_header

pytestmark = pytest.mark.realdata

RADIS_SAMPLES = Path(__file__).resolve().parents[3] / "data" / "RADIS-Export" / "samples"
ASTRANA_SAMPLES = Path(__file__).resolve().parents[3] / "data" / "ASTRANA-Export" / "samples"


def _header_of(path: Path) -> tuple[str, ...]:
    """The first line of `path`, decoded and split. Nothing below line one."""
    with path.open("rb") as handle:
        raw = handle.readline()
    for encoding in (Encoding.UTF_8, Encoding.CP1252):
        text = decode_strict(raw, encoding)
        if text is not None:
            break
    else:  # pragma: no cover - a sample that decodes as neither is its own bug
        pytest.fail(f"{path.name} decodes under neither UTF-8 nor Windows-1252")
    dialect = detect_dialect(text, FileKind.UNKNOWN)
    row = next(csv.reader([text], delimiter=dialect.delimiter, quotechar=dialect.quote_char))
    return tuple(row)


def _sample_paths(samples_dir: Path) -> list[Path]:
    if not samples_dir.is_dir():
        pytest.skip(f"no samples at {samples_dir} — real data stays on the host")
    return sorted(p for p in samples_dir.iterdir() if p.is_file() and not p.name.startswith("."))


# --- RADIS -------------------------------------------------------------


def test_every_radis_sample_header_matches_a_canonical_set_exactly():
    """If a delivery ever changes shape, this is where it is noticed."""
    for path in _sample_paths(RADIS_SAMPLES):
        match = classify_header(_header_of(path))
        assert match.kind is not FileKind.UNKNOWN, path.name
        assert match.ok, (path.name, match.kind, match.missing, match.extra)


def test_the_radis_samples_between_them_cover_all_four_kinds():
    """Nothing is asserted from a filename: the kinds come from the headers."""
    kinds = {classify_header(_header_of(path)).kind for path in _sample_paths(RADIS_SAMPLES)}
    assert kinds == set(CANONICAL_COLUMN_SETS)


def test_the_radis_canonical_names_are_the_sample_names_in_the_sample_order():
    """Order is part of the contract — the rows are positional."""
    for path in _sample_paths(RADIS_SAMPLES):
        header = _header_of(path)
        match = classify_header(header)
        assert match.column_set is not None, path.name
        assert normalise_header(header) == normalise_header(match.column_set.columns), path.name


def test_the_radis_sample_widths_are_the_documented_67_77_18_and_2():
    widths = {
        classify_header(_header_of(p)).kind: len(_header_of(p))
        for p in _sample_paths(RADIS_SAMPLES)
    }
    assert widths == {
        FileKind.UNFALL: 67,
        FileKind.OBJEKT: 77,
        FileKind.PERSON: 18,
        FileKind.TEXT: 2,
    }


# --- Astrana -------------------------------------------------------------


def test_every_astrana_sample_header_matches_a_canonical_set_exactly():
    for path in _sample_paths(ASTRANA_SAMPLES):
        match = classify_header(_header_of(path))
        assert match.kind is not FileKind.UNKNOWN, path.name
        assert match.ok, (path.name, match.kind, match.missing, match.extra)


def test_the_astrana_samples_between_them_cover_unfall_objekt_and_person():
    """No separate Astrana text file exists — the narrative file is shared
    and unchanged across formats (confirmed product decision)."""
    kinds = {classify_header(_header_of(path)).kind for path in _sample_paths(ASTRANA_SAMPLES)}
    assert kinds == {FileKind.UNFALL, FileKind.OBJEKT, FileKind.PERSON}


def test_the_astrana_canonical_names_are_the_sample_names_in_the_sample_order():
    for path in _sample_paths(ASTRANA_SAMPLES):
        header = _header_of(path)
        match = classify_header(header)
        assert match.column_set is not None, path.name
        assert normalise_header(header) == normalise_header(match.column_set.columns), path.name


def test_the_astrana_sample_widths_are_67_76_and_21():
    widths = {
        classify_header(_header_of(p)).kind: len(_header_of(p))
        for p in _sample_paths(ASTRANA_SAMPLES)
    }
    assert widths == {
        FileKind.UNFALL: 67,
        FileKind.OBJEKT: 76,
        FileKind.PERSON: 21,
    }
