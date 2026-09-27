"""`SD42` — every `Settings` field has a reader in `ra2/`, or it does not exist.

`docs/risk-assesment.md` G3 named the category and this test: `host`, `port`,
the deleted `exports_dir` and `dev_agent.py`'s `RA2_PORT` were each **a setting
that implies a control nobody implemented**, and `min_cell_count` was a fifth.
Each sat in sw-design.md §10 and the README with a sentence saying what it did,
and a reader believes the table.

**A static scan of the source, deliberately.** The defect is a name read by no
code, and neither an import graph nor a runtime probe can see that. It is an
**AST** scan and not a text search, for two reasons found in this tree:

- `domain/llm.py` has `_ = parts.port` — a URL's port, not the setting. A
  search for `.port` would have passed `Settings.port` for as long as it was
  read by nothing, which is the whole history of the defect.
- Docstrings and comments describe settings constantly, including the ones
  that were never read. A mention is not a reader.

So only an attribute read **on a settings object** counts: `settings.x`,
`self._settings.x`, `Settings().x`.

**A property is a second lookup, not an exemption.** `db_path` is consumed as
`database_path` and `max_upload_mb` as `max_upload_bytes`; such a field passes
only if the property that reads it is itself read, transitively. There is no
list of names with a reason beside them, so there is nothing to widen.
"""

import ast
import inspect
import textwrap
from collections.abc import Iterable
from pathlib import Path

from ra2.infra.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "ra2" / "infra" / "config.py"


def _is_settings_object(node: ast.expr) -> bool:
    """`settings`, `_settings`, `self._settings`, `Settings()`."""
    if isinstance(node, ast.Name):
        return node.id in {"settings", "_settings"}
    if isinstance(node, ast.Attribute):
        return node.attr == "_settings"
    if isinstance(node, ast.Call):
        return isinstance(node.func, ast.Name) and node.func.id == "Settings"
    return False


def _names_read_on_settings(source: str) -> set[str]:
    return {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and _is_settings_object(node.value)
    }


def _properties(cls: type[Settings]) -> dict[str, set[str]]:
    """Each property on `cls` (and its `Settings` ancestors), mapped to the
    names its own body reads off `self`."""
    found: dict[str, set[str]] = {}
    for klass in reversed(cls.__mro__):
        if not (isinstance(klass, type) and issubclass(klass, Settings)):
            continue
        for name, attr in vars(klass).items():
            if isinstance(attr, property) and attr.fget is not None:
                body = ast.parse(textwrap.dedent(inspect.getsource(attr.fget)))
                found[name] = {
                    node.attr
                    for node in ast.walk(body)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                }
    return found


def unread_fields(cls: type[Settings], sources: Iterable[str]) -> list[str]:
    """The fields of `cls` that no source reads, directly or through a property
    that is itself read."""
    read: set[str] = set()
    for source in sources:
        read |= _names_read_on_settings(source)
    properties = _properties(cls)
    frontier = [name for name in read if name in properties]
    while frontier:
        for name in properties[frontier.pop()]:
            if name not in read:
                read.add(name)
                if name in properties:
                    frontier.append(name)
    return sorted(set(cls.model_fields) - read)


def _ra2_sources() -> list[str]:
    """Every module in `ra2/` except the one that declares the fields."""
    return [
        path.read_text(encoding="utf-8")
        for path in sorted((REPO_ROOT / "ra2").rglob("*.py"))
        if path.resolve() != CONFIG.resolve()
    ]


def test_every_settings_field_has_a_reader() -> None:
    unread = unread_fields(Settings, _ra2_sources())

    assert unread == [], (
        f"Settings fields with no reader in ra2/: {unread}. sw-design.md SD42: every "
        "Settings field has a reader, or it does not exist. Give it one, or do not "
        "add it — a documented knob that does nothing is documentation that lies."
    )


# --- the gate's own properties ---------------------------------------------


class _Unread(Settings):
    never_read_anywhere: int = 0


class _ThroughAProperty(Settings):
    only_through_a_property: int = 0

    @property
    def the_property(self) -> int:
        return self.only_through_a_property


def test_a_settings_field_with_no_reader_fails_the_gate() -> None:
    """The gate can fail. Without this it could rot into a tautology — a
    scanner that found nothing would pass every tree."""
    assert unread_fields(_Unread, _ra2_sources()) == ["never_read_anywhere"]


def test_a_mention_in_a_docstring_or_a_comment_is_not_a_reader() -> None:
    """The blind spot a text search has, closed: this tree's docstrings name
    settings that were read by nothing for phases at a time."""
    source = (
        '"""`settings.never_read_anywhere` is described here."""\n# settings.never_read_anywhere\n'
    )

    assert "never_read_anywhere" in unread_fields(_Unread, [source])


def test_the_same_name_read_off_another_object_is_not_a_reader() -> None:
    """`domain/llm.py`'s `parts.port` is a URL's port. A search for `.port`
    would have passed `Settings.port` while it was read by nothing."""
    assert "never_read_anywhere" in unread_fields(_Unread, ["x = parts.never_read_anywhere\n"])


def test_a_field_read_through_a_property_passes_only_if_the_property_is_read() -> None:
    """Case 2 is a second lookup that must also pass, not a free-text
    exemption: the field is live exactly when its property is."""
    fields = set(_ThroughAProperty.model_fields) - {"only_through_a_property"}
    read_everything_else = "".join(f"settings.{name}\n" for name in fields)

    read = read_everything_else + "x = self._settings.the_property\n"
    assert unread_fields(_ThroughAProperty, [read]) == []
    assert unread_fields(_ThroughAProperty, [read_everything_else]) == ["only_through_a_property"]
