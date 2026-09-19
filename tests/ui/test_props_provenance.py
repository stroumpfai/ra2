r"""Layer 3 — a prop whose value is data goes through the props *mapping*.

`SD31` stated the rule and fixed one call site, the header's data-directory
chip. This file is the rest of the class, and the reason it is a file of its
own rather than three more cases in `test_components.py` is that the bug is
**not** about one component: it is about the seam between NiceGUI's
`.props("k=v")` and everything the app knows.

`Props.parse` matches each `key="value"` pair with a regex and hands the
quoted run to `ast.literal_eval`, so an interpolated value is read as **Python
source**. Reproduced against the pinned NiceGUI, with the props string
`type="text" value="{name}" data-testid="rename-input"`:

    'draft\\'            -> {'type': 'text', 'data-testid': 'rename-input'}
    'Unfall\\next.csv'   -> value == 'Unfall<LF>ext.csv'
    'colA\\tname'        -> value == 'colA<TAB>name'
    'C:\\Users\\dev'     -> SyntaxError: truncated \UXXXXXXXX escape

The first line is the one worth staring at. There is no exception and no
warning: the trailing backslash escapes the closing quote, the regex resyncs
on the next pair, and the `value` prop is simply **not there**. A feature set
whose name ends in a backslash opens a rename box pre-filled *empty*, over a
name the analyst cannot see — so the next keystroke silently renames the set
to something else. `html.escape` changes none of the four (it handles `&`,
`<`, `>` and quotes; the parser cares about backslashes) and makes a fifth
case worse, turning `A & B` into `A &amp; B`.

The hazards below are therefore the real ones (CLAUDE.md, "Fixtures must
contain the real hazards"): a trailing backslash, an embedded newline and tab,
a Windows path, an ampersand. Every case asserts the prop **round-trips** —
`_props[key] == value`, byte for byte — because "the page did not crash" is
exactly the assertion that would have passed while the value vanished.
"""

import ast
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from nicegui import ui
from nicegui.testing.user import User

from ra2.domain.ids import FeatureConfigId
from ra2.services.readmodels import FeatureSetSummary, SortDir
from ra2.ui.components import ColumnSpec, data_table
from ra2.ui.components.feature_sets_table import feature_sets_table
from ra2.ui.state import TableState

pytestmark = pytest.mark.ui

#: `tests/ui/test_props_provenance.py` -> `tests/ui` -> `tests` -> repo root.
REPO_ROOT: Final = Path(__file__).resolve().parents[2]

#: The four shapes reproduced above, plus the one `html.escape` would corrupt
#: on its own. Every one is a name a person can legally type and — except the
#: Windows path — a name a POSIX filesystem will happily store.
TRAILING_BACKSLASH: Final = "draft\\"
CONTROL_CHARS: Final = "Unfall\\next.csv\\tv2"
WINDOWS_PATH: Final = r"C:\Users\dev\sets"
AMPERSAND: Final = "Weather & conditions <v3>"

HAZARD_NAMES: Final[tuple[str, ...]] = (
    TRAILING_BACKSLASH,
    CONTROL_CHARS,
    WINDOWS_PATH,
    AMPERSAND,
)


def _set(name: str) -> FeatureSetSummary:
    return FeatureSetSummary(
        feature_config_id=FeatureConfigId("fc-1"),
        name=name,
        version=3,
        description="Conditions + probes",
        created_at=datetime(2026, 9, 4, 14, 22, tzinfo=UTC),
        feature_count=14,
        frozen_at=None,
    )


def _page(path: str, build: Callable[[], object]) -> None:
    @ui.page(path)
    def _view() -> None:
        build()


def _sets_page(path: str, name: str) -> None:
    _page(
        path,
        lambda: feature_sets_table(
            sets=[_set(name)],
            selected_id=None,
            on_select=lambda _: None,
            on_rename=lambda _id, _name: None,
            on_delete=lambda _: None,
            on_new_set=lambda: None,
        ),
    )


# --- the values -------------------------------------------------------------


@pytest.mark.parametrize("name", HAZARD_NAMES)
async def test_a_hazardous_feature_set_name_reaches_the_rename_input(user: User, name: str) -> None:
    """The reproduced bug, asserted on the value rather than on the page.

    `draft\\` is the case that made this a data bug and not a cosmetic one:
    through the props string the `value` prop was *absent*, so the rename box
    opened empty. The others cover the two quieter halves — a valid escape
    sequence silently rewritten, and `html.escape` putting `&amp;` on screen.
    """
    _sets_page(f"/pp/value/{HAZARD_NAMES.index(name)}", name)
    await user.open(f"/pp/value/{HAZARD_NAMES.index(name)}")

    (rename_input,) = user.find(marker="rename-input").elements
    assert rename_input._props["value"] == name
    assert rename_input._props["aria-label"] == f"Rename {name}"


@pytest.mark.parametrize("name", HAZARD_NAMES)
async def test_a_hazardous_feature_set_name_reaches_the_row_buttons(user: User, name: str) -> None:
    """`icon_button` is in `primitives.py`, so it is every view's problem.

    The two controls here are the only way to rename or delete a set, and
    their `aria-label` is the only thing telling a screen reader *which* set
    the button acts on — which is precisely the question a destructive control
    must answer correctly.
    """
    index = HAZARD_NAMES.index(name)
    _sets_page(f"/pp/buttons/{index}", name)
    await user.open(f"/pp/buttons/{index}")

    (rename,) = user.find(marker="rename-button").elements
    (delete,) = user.find(marker="delete-button").elements
    assert rename._props["aria-label"] == f"Rename {name}"
    assert rename._props["title"] == f"Rename {name}"
    assert delete._props["aria-label"] == f"Delete {name}"


async def test_no_prop_is_double_escaped(user: User) -> None:
    """`html.escape` comes **off** these sites, it is not merely bypassed.

    The mapping is serialised as JSON and handed to `Vue.h` as the props of a
    native tag, which sets attributes through the DOM API — no HTML parser is
    involved anywhere on that path. Escaping on the way in would therefore
    reach the screen as a literal `&amp;`, which is the second half of the
    `SD31` argument and the half that is easy to reintroduce.
    """
    _sets_page("/pp/escape", AMPERSAND)
    await user.open("/pp/escape")

    (rename_input,) = user.find(marker="rename-input").elements
    assert "&amp;" not in rename_input._props["value"]
    assert "&lt;" not in rename_input._props["value"]
    assert rename_input._props["value"] == AMPERSAND


async def test_a_hazardous_column_label_reaches_the_sort_header(user: User) -> None:
    """`data_table` is the one table component every view is built from, and
    a column key is a **delivery** column name (Do-NOT #5: the data decides).

    Both halves are asserted: the `aria-label` a screen reader reads, and the
    `data-testid` the E2E selectors hang off — a `data-testid` mangled by the
    parser fails a test somewhere else entirely, which is the expensive way to
    find this.
    """
    column: ColumnSpec[object] = ColumnSpec(key=CONTROL_CHARS, label=WINDOWS_PATH, sortable=True)
    _page(
        "/pp/sort",
        lambda: data_table(
            columns=(column,),
            rows=(),
            state=TableState(CONTROL_CHARS, SortDir.ASC),
            on_sort=lambda _: None,
        ),
    )
    await user.open("/pp/sort")

    (header,) = [e for e in user.find(kind=ui.element).elements if e.tag == "th"]
    assert header._props["data-column"] == CONTROL_CHARS
    (button,) = [e for e in user.find(kind=ui.element).elements if e.tag == "button"]
    assert button._props["aria-label"] == f"Sort by {WINDOWS_PATH}"
    assert button._props["data-testid"] == f"sort-{CONTROL_CHARS}"


# --- the floor --------------------------------------------------------------
#
# This is the third time the class has been found (the chip, then this sweep),
# so the rule gets a mechanical floor rather than a note in a review.
#
# It is deliberately a *floor* and not the whole rule. Provenance is a
# semantic property — whether the string in this variable came from a delivery
# or from the line above it — and nothing static can decide it. A check that
# tried would either miss the harmful cases (`data-testid="sort-{column.key}"`
# is data in a structural-looking key) or reject the ~50 legitimate `colspan=
# "{len(columns)}"`-shaped sites and be turned off within a month.
#
# So it checks the one thing that *is* decidable and that no legitimate site
# needs: a **text-carrying** attribute — the ones whose value is, by
# definition, something a person reads or types — never has an interpolation
# in its props string. Those are also the sites where corruption is silent:
# a mangled `data-testid` fails an E2E selector, a mangled `aria-label` fails
# nothing and lies to a screen reader.
#
# The cost to a future call site is one mapping entry. `data_props` takes it.

TEXT_PROPS: Final[frozenset[str]] = frozenset(
    {
        "alt",
        "aria-description",
        "aria-label",
        "aria-placeholder",
        "aria-valuetext",
        "label",
        "placeholder",
        "title",
        "value",
    }
)

#: What an interpolation is replaced by while the skeleton is scanned. `\x00`
#: cannot occur in a source literal that reached this point.
_HOLE: Final = "\x00"
_PAIR: Final = re.compile(r"(?P<key>[A-Za-z_:][-\w:.]*)\s*=\s*\"(?P<value>[^\"]*)\"")


def _skeleton(node: ast.expr) -> str:
    """The props string with every interpolation replaced by `_HOLE`."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else _HOLE
    if isinstance(node, ast.JoinedStr):
        return "".join(_skeleton(part) for part in node.values)
    if isinstance(node, ast.FormattedValue):
        return _HOLE
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _skeleton(node.left) + _skeleton(node.right)
    if isinstance(node, ast.IfExp):
        return _skeleton(node.body)
    return _HOLE


def _offenders() -> list[str]:
    found: list[str] = []
    for path in sorted((REPO_ROOT / "ra2" / "ui").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "props"
                and node.args
            ):
                continue
            for match in _PAIR.finditer(_skeleton(node.args[0])):
                if _HOLE in match["value"] and match["key"] in TEXT_PROPS:
                    relative = path.relative_to(REPO_ROOT).as_posix()
                    found.append(f"{relative}:{node.lineno}: {match['key']}=")
    return found


def test_no_text_prop_is_interpolated_into_a_props_string() -> None:
    """`ra2/ui/` assigns every human-readable prop through the mapping.

    `Path.as_posix()` rather than `str()` in the message, for the reason
    `SD33` gives: this test reports the same path on both CI legs.
    """
    assert _offenders() == []


def test_the_floor_actually_catches_the_shape_it_is_meant_to() -> None:
    """A test that can only pass is not a gate (this one had to be checked
    against the bug it exists for, which is `feature_sets_table`'s own
    pre-`SD34` line)."""
    source = (
        'e.props(f\'type="text" value="{escaped_name}" '
        'aria-label="Rename {escaped_name}" data-testid="rename-input"\')'
    )
    call = ast.parse(source).body[0].value  # type: ignore[attr-defined]
    keys = {m["key"] for m in _PAIR.finditer(_skeleton(call.args[0])) if _HOLE in m["value"]}
    assert keys == {"value", "aria-label"}
    assert keys <= TEXT_PROPS

    safe = 'e.props(f\'colspan="{len(columns)}" data-testid="empty"\')'
    safe_call = ast.parse(safe).body[0].value  # type: ignore[attr-defined]
    hit = {
        m["key"]
        for m in _PAIR.finditer(_skeleton(safe_call.args[0]))
        if _HOLE in m["value"] and m["key"] in TEXT_PROPS
    }
    assert hit == set()
