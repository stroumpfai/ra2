# Bodies owned by G2 (feat/p2-features-view, phase 2 Wave 4).
"""Features view — "what to extract, and how it is scored" (mvp-spec.md §8).

`design/code-feature/README.md`, Screen 2 · Features, implemented against the
five drawn boards (`FeatureConfig.dc.html` and its four variants) as **one**
view whose edit zone renders per feature (README: "these five files are ONE
view"). The same three rules that shape `census_view.py` shape every line
here:

1. **The UI holds no business logic** (CLAUDE.md #7). Every number, every
   validation message and every fingerprint arrives from `FeatureService` /
   `CodelistService` / `CorpusService`; this file only decides *how much of
   the already-fetched feature set fits on screen*.

   The one designed exception (README: "filter row... client-side filtering
   of the already-fetched list") is the flat feature list: unlike Census,
   `FeatureService.get()` returns a **whole** feature set in one call — there
   is no server-side page of features to ask for, because a config tops out
   at a few dozen rows (`EXPLORATORY_FEATURE_CAP` alone bounds a third of it).
   Filtering, sorting and paging that already-whole list for the screen is
   presentation over data already handed over, the same class of operation as
   `bar()`'s percentage clamp — not a second copy of a service's own logic.

2. **No module-level mutable state** (§12.8). The selected set, the selected
   feature, the two filter chips, the prompt language and the validation
   corpus all live in `app.storage.client` through this module's own keys —
   `ui/state.py` is frozen this milestone and, per `census_view.py`'s own
   reasoning, nothing outside this view has a feature filter. The one thing
   that does **not** go there is the in-progress edit buffer (`_FeatureDraft`,
   below): losing an unsaved edit on a hard refresh is an undesigned corner
   the source material leaves open (README, "Loading / empty / error"), and
   `app.storage.client` is for navigational state a service could always
   reconstruct, not a scratchpad for an edit nobody asked to persist yet.

3. **The UI calls services in-process as Python** (§1). No HTTP call to this
   app's own API anywhere in this file, and no session or ORM object crosses
   into it — every render reads a `FeatureView`/`FeatureConfigView`/
   `FeatureSetSummary`/`ColumnMappingView`/`CensusColumnView`/`CorpusView`.

Two components this view **places but does not implement** — `derivation_builder`
and `feature_sets_table` (`ra2/ui/components/derivation_builder.py`,
`feature_sets_table.py`) — are G3's, built in parallel this wave against a
frozen signature (plan-phase-2.md §3, M9). Their bodies are still
`raise NotImplementedError` stubs as this file is written; wiring against the
frozen signature is correct regardless of when the body lands (`tests/ui/
test_features_view.py`'s module docstring explains how the test suite copes
with that in the meantime).

**Judgment calls made in this file, documented at the point of decision and
repeated in the branch's final report:**

- *Save, not autosave.* Both new-feature and existing-feature editing use an
  explicit **Save** action. The design draws no autosave-on-keystroke behaviour
  anywhere and resolves the new-feature question only as far as "the intent is
  the same right-hand panel... not a modal" (README, Open question 2); an
  explicit action is the simpler, safer default and it is applied uniformly so
  the two modes behave identically.
- *"open codelist ↗".* There is no cross-navigation infrastructure yet (the
  same gap `census_view.py`'s "use as feature" hits from the other side) — so
  this renders as a disabled-looking, non-interactive label, exactly as
  `census_view._render_action` renders its own forward-reference.
- *The validate-against corpus picker* lives once, near the top of the edit
  zone's Source/Derivation section, rather than repeated per case — it feeds
  every case's `validate_against` argument alike (plan-phase-2.md C3), not
  only Case A's codelist display.
- *Grain/Value type/language/corpus selection* renders as a native `<select>`
  styled with the existing `.rof`/`.chip` classes rather than a bespoke
  dropdown-menu widget (`census_view._dropdown`) reimplemented a third time —
  the design's own fidelity note calls for "high-fidelity layout, *medium*-
  fidelity styling" on this screen, and a native control is exactly the
  `page-size` idiom `primitives.py` and `import_view.py` already use for a
  controlled value the analyst changes (as opposed to the toolbar chips, whose
  pixel fidelity the design does hold to strictly, and which keep the bespoke
  widget).
- *`FeatureService.get()` has no `validate_against` parameter* (only
  `add_feature`/`edit_feature`/`freeze`/`clone` do) — so the corpus-scoped
  enum-codelist validation tier only ever reflects in `validation_errors` right
  after a save, not on a bare reload. Case A's own "N of M codes labelled"
  display is unaffected: it reads `CodelistService.list_columns()` directly,
  which is always current.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from html import escape
from typing import Final, cast

from nicegui import app, ui
from nicegui.element import Element

from ra2.domain.feature import (
    EXPLORATORY_FEATURE_CAP,
    DerivationSpec,
    Grain,
    Kind,
    MatchingRule,
    MatchingRuleKind,
    ValueType,
)
from ra2.domain.ids import CorpusId, FeatureConfigId, FeatureId
from ra2.services.container import Services
from ra2.services.errors import ServiceError
from ra2.services.readmodels import (
    CensusColumnView,
    ColumnMappingView,
    CorpusView,
    FeatureConfigView,
    FeatureSetSummary,
    FeatureView,
    SortDir,
)
from ra2.ui.components import (
    ColumnSpec,
    bar,
    card,
    data_table,
    icon_button,
    pagination_row,
)
from ra2.ui.components.derivation_builder import derivation_builder
from ra2.ui.components.feature_sets_table import feature_sets_table
from ra2.ui.components.icons import ALERT_TRIANGLE, PLUS, svg
from ra2.ui.components.primitives import (
    fingerprint_badge,
    frozen_readout,
    master_detail_split,
    pill,
    segmented_control,
)
from ra2.ui.shell import NAV_ITEMS, shell
from ra2.ui.state import TableState, set_table_state, table_state

__all__ = [
    "CONTENT_GAP",
    "CONTENT_PADDING",
    "DEFAULT_LANGUAGE",
    "FEATURE_KEY",
    "FILTERS_KEY",
    "LANGUAGE_KEY",
    "NEW_FEATURE_SENTINEL",
    "PAGE_SIZE",
    "PROMPT_LANGUAGES",
    "SET_KEY",
    "STATE_OPTIONS",
    "TYPE_OPTIONS",
    "VALIDATE_KEY",
    "FeatureFilters",
    "feature_filters",
    "register",
]

_ITEM = next(i for i in NAV_ITEMS if i.key == "features")

#: Edge-to-edge (the toolbar, the split and the sets strip each carry their
#: own padding — README, "Layout"), unlike Census's padded-card content column.
CONTENT_PADDING = "0"
CONTENT_GAP = "0"

#: Per-client storage keys (§12.8) — this view's own, the same reasoning
#: `census_view.CensusFilters`'s docstring gives for not touching `ui/state.py`.
SET_KEY: Final = "ra2.features.set"
FEATURE_KEY: Final = "ra2.features.feature"
FILTERS_KEY: Final = "ra2.features.filters"
LANGUAGE_KEY: Final = "ra2.features.language"
VALIDATE_KEY: Final = "ra2.features.validate_against"

#: `FEATURE_KEY`'s value while the edit zone is in "Add feature" mode — never
#: a real `FeatureId`, so it can share the one storage key.
NEW_FEATURE_SENTINEL: Final = "__new__"

#: README, "Feature list": "pagination (10 per page)".
PAGE_SIZE: Final = 10
FEATURES_TABLE: Final = "features.list"
DEFAULT_SORT_KEY: Final = "ordinal"
DEFAULT_SORT_DIR: Final = SortDir.ASC

#: The filter row's two chips (README: "type · all ▾" / "state · all ▾"). The
#: design does not enumerate `state`'s options — this view's own choice,
#: the smallest ladder that answers "which rows are blocking" (mirrors
#: `census_view.POPULATED_THRESHOLDS`'s reasoning for an underspecified chip).
TYPE_OPTIONS: Final[tuple[str, ...]] = ("accident", "derived", "object", "person", "exploratory")
STATE_OPTIONS: Final[tuple[str, ...]] = ("ok", "error")

#: The Codelists screen shows three prompt-language chips; Features' own
#: toolbar chip names only "de" (README's own fixture), so this view assumes
#: the same three-language vocabulary rather than inventing a fourth ladder.
PROMPT_LANGUAGES: Final[tuple[str, ...]] = ("de", "fr", "it")
DEFAULT_LANGUAGE: Final = "de"

#: A corpus picker large enough to exhaust what Import/Census offer their own
#: pickers (`census_view.CORPUS_CHOICES`) — same bound, same reasoning.
CORPUS_CHOICES: Final = 100
#: Large enough to exhaust one corpus's enum columns / census columns in one
#: round trip, mirroring `codelist_service._CENSUS_PAGE_SIZE`'s reasoning.
COLUMN_PAGE_SIZE: Final = 1000

#: README, Case B: "± 15 min" is the fixture; this is the stepper's own
#: increment and the value a brand-new time feature starts from.
DEFAULT_TOLERANCE_MINUTES: Final = 15
TOLERANCE_STEP_MINUTES: Final = 5

_GRAIN_LABELS: Final[dict[Grain, str]] = {
    Grain.ACCIDENT: "Accident level",
    Grain.DERIVED: "Derived aggregate",
    Grain.OBJECT: "Object grain",
    Grain.PERSON: "Person grain",
}
_VALUE_TYPE_LABELS: Final[dict[ValueType, str]] = {
    ValueType.ENUM: "enum (code)",
    ValueType.INTEGER: "integer",
    ValueType.DECIMAL: "decimal",
    ValueType.DATE: "date",
    ValueType.TIME: "time",
    ValueType.BOOLEAN: "boolean",
    ValueType.FREE_TEXT: "free text",
}
#: README, "Type" column: "accident · derived · object · exploratory" — a
#: `Kind.EXPLORATORY` feature always reads "exploratory" regardless of the
#: `Grain` it happens to carry (mirrors `census_view.BUCKET_LABELS`: a small
#: rendering table, not a computation).
_TYPE_LABELS: Final[dict[Grain, str]] = {
    Grain.ACCIDENT: "accident",
    Grain.DERIVED: "derived",
    Grain.OBJECT: "object",
    Grain.PERSON: "person",
}

TOOLBAR_STYLE: Final = (
    "display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:11px 28px;"
    "background:var(--surface);border-bottom:1px solid var(--rule);flex:none;"
)
LEFT_GROUP_STYLE: Final = "display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0;"
RIGHT_GROUP_STYLE: Final = "display:flex;align-items:center;gap:10px;margin-left:auto;flex:none;"
FILTER_ROW_STYLE: Final = (
    "flex:none;padding:8px 16px;border-bottom:1px solid var(--rule2);"
    "background:var(--strip-tint);display:flex;gap:8px;"
)
GRID_STYLE: Final = (
    "display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;"
)
NOTE_WARN_STYLE: Final = (
    "padding:10px 12px;border-radius:3px;background:var(--warn-soft);"
    "color:var(--warn-ink);font-size:12px;line-height:1.5;"
)
NOTE_ACCENT_STYLE: Final = (
    "padding:10px 12px;border-radius:3px;background:var(--accent-soft);"
    "color:var(--note-ink);font-size:12px;line-height:1.5;"
)
DASHED_BOX_STYLE: Final = (
    "border:1px dashed var(--rule);border-radius:3px;padding:10px 12px;"
    "color:var(--ink3);font-size:12.5px;background:var(--field-tint);"
)
FIELD_BOX_STYLE: Final = (
    "border:1px solid var(--rule);border-radius:3px;padding:10px 12px;background:var(--surface);"
)

#: "open codelist ↗" — no cross-navigation exists yet (see module docstring).
OPEN_CODELIST_LABEL: Final = "open codelist ↗"
NO_SET_MESSAGE: Final = "No feature set yet — use “New set” below."
NO_FEATURES_MESSAGE: Final = "No features match this filter."
NO_FEATURE_SELECTED: Final = "Select a feature, or add one, to edit it here."


@dataclass(frozen=True, slots=True)
class FeatureFilters:
    """The feature list's two filter chips, per client.

    Lives here, not in `ui/state.py`, for the same reason
    `census_view.CensusFilters` does: `ui/state.py` is frozen this milestone
    and nothing outside this view has a feature-type or feature-state filter.
    """

    type_filter: str | None = None
    state_filter: str | None = None


def feature_filters() -> FeatureFilters:
    """This client's filter chips, created on first use."""
    filters: FeatureFilters = app.storage.client.setdefault(FILTERS_KEY, FeatureFilters())
    return filters


@dataclass(slots=True)
class _FeatureDraft:
    """A working copy of one feature's editable fields.

    Staged locally until **Save** is pressed (the module docstring's "save,
    not autosave" decision) — never written through `app.storage.client`
    (losing it on a hard refresh is an accepted, undesigned corner).
    `feature_id=None` marks a not-yet-saved, new-feature draft.
    """

    feature_id: FeatureId | None
    key: str
    kind: Kind
    description: str
    grain: Grain
    source_column: str | None
    derivation: DerivationSpec | None
    value_type: ValueType
    matching_rule: MatchingRule


def _new_draft() -> _FeatureDraft:
    """README, new-feature mode: "Kind defaulted to labelled, every other
    field empty/unset" (plan-phase-2.md C2)."""
    return _FeatureDraft(
        feature_id=None,
        key="",
        kind=Kind.LABELLED,
        description="",
        grain=Grain.ACCIDENT,
        source_column=None,
        derivation=None,
        value_type=ValueType.ENUM,
        matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
    )


def _draft_from(feature: FeatureView) -> _FeatureDraft:
    return _FeatureDraft(
        feature_id=feature.feature_id,
        key=feature.key,
        kind=feature.kind,
        description=feature.description,
        grain=feature.grain,
        source_column=feature.source_column,
        derivation=feature.derivation,
        value_type=feature.value_type,
        matching_rule=feature.matching_rule,
    )


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    async def _page() -> None:
        page = _FeaturesPage(services)
        await page.build()


class _FeaturesPage:
    """One client's Features view — built inside the page function, one
    instance per browser tab (§12.8), the same shape as `_CensusPage`."""

    def __init__(self, services: Services) -> None:
        self._services = services
        self._sets: tuple[FeatureSetSummary, ...] = ()
        self._config: FeatureConfigView | None = None
        self._corpora: tuple[CorpusView, ...] = ()
        self._enum_columns: tuple[ColumnMappingView, ...] = ()
        self._census_columns: tuple[CensusColumnView, ...] = ()
        #: The in-progress edit buffer. `None` = no feature open for editing.
        self._draft: _FeatureDraft | None = None
        self._open_menu: str | None = None
        self._toolbar: Element | None = None
        self._list_slot: Element | None = None
        self._detail_slot: Element | None = None
        self._sets_slot: Element | None = None

    # --- lifecycle -----------------------------------------------------------

    async def build(self) -> None:
        with shell(
            title=_ITEM.title,
            description=_ITEM.description,
            active=_ITEM.key,
            content_padding=CONTENT_PADDING,
            content_gap=CONTENT_GAP,
        ):
            root = ui.element("div").style(
                "display:flex;flex-direction:column;flex:1;min-height:0;min-width:0;"
            )
            with root:
                self._toolbar = (
                    ui.element("div").props('data-testid="features-toolbar"').style(TOOLBAR_STYLE)
                )
                self._list_slot, self._detail_slot = master_detail_split()
                self._sets_slot = (
                    ui.element("div")
                    .props('data-testid="feature-sets-slot"')
                    .style(
                        "flex:none;margin-top:16px;border-top:1px solid var(--rule);"
                        "background:var(--surface);max-height:302px;overflow:auto;"
                    )
                )
        await self.reload()

    async def reload(self) -> None:
        """Re-read every service this view shows, then redraw — the same
        single-entry-point shape as `_CensusPage.reload`. Never touches
        `self._draft`: an in-progress edit survives a corpus/language pick."""
        self._sets = tuple(await self._services.feature.list_configs())
        self._config = await self._load_selected_config()
        set_id = self._config.feature_config_id if self._config is not None else None
        app.storage.client[SET_KEY] = str(set_id) if set_id is not None else None
        self._corpora = (
            await self._services.corpus.list_corpora(
                sort_key="imported_at", sort_dir=SortDir.DESC, page=1, page_size=CORPUS_CHOICES
            )
        ).items
        await self._reload_corpus_scoped_columns()
        self._sync_selection()
        self._render()

    async def _load_selected_config(self) -> FeatureConfigView | None:
        remembered = app.storage.client.get(SET_KEY)
        candidate = next((s for s in self._sets if str(s.feature_config_id) == remembered), None)
        if candidate is None:
            candidate = max(
                self._sets, key=lambda s: (s.created_at, s.feature_config_id), default=None
            )
        if candidate is None:
            return None
        return await self._services.feature.get(candidate.feature_config_id)

    async def _reload_corpus_scoped_columns(self) -> None:
        corpus_id = self._validate_against()
        if corpus_id is None:
            self._enum_columns = ()
            self._census_columns = ()
            return
        self._enum_columns = tuple(
            await self._services.codelist.list_columns(corpus_id, language=self._prompt_language())
        )
        page = await self._services.census.columns(corpus_id, page_size=COLUMN_PAGE_SIZE)
        self._census_columns = page.items

    def _sync_selection(self) -> None:
        """Drop a selected feature that no longer exists (deleted, or the set
        changed under it). Never rebuilds `self._draft` for a survivor."""
        if self._config is None:
            app.storage.client[FEATURE_KEY] = None
            self._draft = None
            return
        selected = app.storage.client.get(FEATURE_KEY)
        if selected == NEW_FEATURE_SENTINEL:
            return
        if selected is not None and not any(
            str(f.feature_id) == selected for f in self._config.features
        ):
            app.storage.client[FEATURE_KEY] = None
            self._draft = None

    # --- per-client state ------------------------------------------------------

    def _selected_feature_key(self) -> str | None:
        value = app.storage.client.get(FEATURE_KEY)
        return value if isinstance(value, str) else None

    def _prompt_language(self) -> str:
        value = app.storage.client.get(LANGUAGE_KEY)
        return value if isinstance(value, str) else DEFAULT_LANGUAGE

    def _validate_against(self) -> CorpusId | None:
        value = app.storage.client.get(VALIDATE_KEY)
        return CorpusId(value) if isinstance(value, str) and value else None

    def _table_state(self) -> TableState:
        return table_state(
            FEATURES_TABLE,
            sort_key=DEFAULT_SORT_KEY,
            sort_dir=DEFAULT_SORT_DIR,
            page_size=PAGE_SIZE,
        )

    # --- rendering ---------------------------------------------------------

    def _render(self) -> None:
        assert self._toolbar is not None
        assert self._list_slot is not None
        assert self._detail_slot is not None
        assert self._sets_slot is not None
        self._toolbar.clear()
        with self._toolbar:
            self._render_toolbar()
        self._list_slot.clear()
        with self._list_slot:
            self._render_list()
        self._detail_slot.clear()
        with self._detail_slot:
            self._render_edit_zone()
        self._sets_slot.clear()
        with self._sets_slot:
            self._render_sets_table()

    # --- toolbar -------------------------------------------------------------

    def _render_toolbar(self) -> None:
        with ui.element("div").style(LEFT_GROUP_STYLE):
            self._set_select()
            self._language_select()
            self._danger_chip()
        with ui.element("div").style(RIGHT_GROUP_STYLE):
            self._create_set_button()

    def _set_select(self) -> None:
        current = self._config
        options = [(str(s.feature_config_id), _set_chip_text(s)) for s in self._sets]
        text = _set_chip_text_for(current) if current is not None else "set · none ▾"
        if not options:
            ui.label(text).classes("chip mono").props('data-testid="set-select"')
            return
        _select(
            options=options,
            value=str(current.feature_config_id) if current is not None else "",
            label="Feature set",
            on_change=_sync(self._pick_set),
            classes="chip",
            testid="set-select",
        )

    def _language_select(self) -> None:
        _select(
            options=[(lang, f"prompt language · {lang}") for lang in PROMPT_LANGUAGES],
            value=self._prompt_language(),
            label="Prompt language",
            on_change=_sync(self._pick_language),
            classes="chip",
            testid="language-select",
        )

    def _danger_chip(self) -> None:
        config = self._config
        if config is None:
            return
        count = sum(len(f.validation_errors) for f in config.features)
        if count == 0:
            return
        noun = "error" if count == 1 else "errors"
        with (
            ui.element("span")
            .props('data-testid="danger-chip"')
            .style(
                "background:var(--danger-soft);color:var(--danger);font-size:11.5px;"
                "font-weight:500;padding:4px 9px;border-radius:3px;"
            )
            .mark("danger-chip")
        ):
            ui.label(f"{count} {noun} block set creation")

    def _create_set_button(self) -> None:
        """README, "Frozen state": the primary action becomes **"Clone to new
        evaluation"** once the selected set is frozen, calling
        `FeatureService.clone` rather than `freeze` (open question 5 resolves
        itself here: the label change is exactly what the frozen board draws,
        so this view keeps it distinct from the draft board's own wording)."""
        config = self._config
        if config is not None and config.is_frozen:
            button = (
                ui.element("button")
                .classes("btn primary")
                .props('type="button" data-testid="clone-feature-set"')
                .mark("clone-feature-set")
            )
            button.on("click", cast("Callable[[], None]", self._clone))
            with button:
                ui.label("Clone to new evaluation")
            return
        blocking = config is not None and any(f.validation_errors for f in config.features)
        button = (
            ui.element("button")
            .classes("btn primary")
            .props('type="button" data-testid="create-feature-set"')
            .mark("create-feature-set")
        )
        if config is None:
            button.props("disabled").style("opacity:.45;")
            with button:
                ui.label("Create a feature set")
            return
        if blocking:
            button.style("opacity:.45;")
        button.on("click", cast("Callable[[], None]", self._freeze))
        with button:
            ui.label("Create a feature set")

    # --- feature list (master pane) ------------------------------------------

    def _render_list(self) -> None:
        config = self._config
        with ui.element("div").style(
            "height:46px;flex:none;padding:0 16px;display:flex;align-items:center;"
            "justify-content:space-between;gap:10px;border-bottom:1px solid var(--rule);"
            "overflow:hidden;"
        ):
            count_text = "0 + 0 features" if config is None else _feature_count_text(config)
            ui.label(count_text).classes("lbl").props('data-testid="feature-count"')
            if config is not None and not config.is_frozen:
                add = icon_button(PLUS, label="Add feature", size=24, glyph=12, stroke=2.2)
                add.on("click", lambda _: self._start_new_feature())
        with ui.element("div").style(FILTER_ROW_STYLE):
            self._type_filter_select()
            self._state_filter_select()
        rows = (
            ()
            if config is None
            else _visible_features(config.features, feature_filters(), self._table_state())
        )
        with ui.element("div").style("flex:1;min-height:0;overflow:auto;"):
            data_table(
                columns=self._feature_columns(),
                rows=rows,
                state=self._table_state(),
                on_sort=_sync(self._sort),
                row_class=self._row_class,
                row_style=self._row_style,
                empty_message=NO_FEATURES_MESSAGE if config is not None else NO_SET_MESSAGE,
                wide=True,
                testid="table-features",
            )
        total = 0 if config is None else len(_filtered_features(config.features, feature_filters()))
        pagination_row(
            state=self._table_state(),
            total=total,
            shown=len(rows),
            on_page=_sync(self._page),
            on_page_size=_sync(self._page_size),
        )

    def _type_filter_select(self) -> None:
        chosen = feature_filters().type_filter
        options = [("", "type · all")] + [(t, f"type · {t}") for t in TYPE_OPTIONS]
        _select(
            options=options,
            value=chosen or "",
            label="Feature type filter",
            on_change=_sync(self._pick_type_filter),
            classes="chip",
            style="padding:3px 8px;font-size:10.5px;",
            testid="type-filter",
        )

    def _state_filter_select(self) -> None:
        chosen = feature_filters().state_filter
        options = [("", "state · all")] + [(s, f"state · {s}") for s in STATE_OPTIONS]
        _select(
            options=options,
            value=chosen or "",
            label="Feature state filter",
            on_change=_sync(self._pick_state_filter),
            classes="chip",
            style="padding:3px 8px;font-size:10.5px;",
            testid="state-filter",
        )

    def _feature_columns(self) -> tuple[ColumnSpec[FeatureView], ...]:
        return (
            ColumnSpec(
                key="key",
                label="Feature",
                sortable=True,
                render=self._render_feature_name,
            ),
            ColumnSpec(
                key="type",
                label="Type",
                width="74px",
                sortable=True,
                cell_class="mono",
                render=lambda row: ui.label(_type_label(row)).style("color:var(--ink2);"),
            ),
            ColumnSpec(key="fp", width="72px", align="right", render=_render_fp_or_error),
        )

    def _render_feature_name(self, feature: FeatureView) -> None:
        selected = self._selected_feature_key() == str(feature.feature_id)
        button = (
            ui.element("button")
            .props(f'type="button" aria-label="Edit {feature.key}" data-testid="feature-row"')
            .mark("feature-row")
            .style(
                "background:none;border:none;padding:0;text-align:left;width:100%;"
                "cursor:pointer;overflow:hidden;"
            )
        )
        button.on(
            "click",
            cast("Callable[[], None]", lambda fid=feature.feature_id: self._select_feature(fid)),
        )
        with button:
            ui.label(feature.key).style(
                f"font-size:12.5px;font-weight:{'600' if selected else '500'};"
                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block;"
            )
            ui.label(_source_line(feature)).classes("mono").style(
                "font-size:10.5px;color:var(--ink3);overflow:hidden;"
                "text-overflow:ellipsis;white-space:nowrap;display:block;"
            )

    def _row_class(self, feature: FeatureView) -> str:
        if self._selected_feature_key() == str(feature.feature_id):
            return "selected"
        return "error" if feature.validation_errors else ""

    def _row_style(self, feature: FeatureView) -> str:
        if self._selected_feature_key() == str(feature.feature_id):
            return "background:var(--accent-soft);"
        if feature.validation_errors:
            return "background:var(--danger-soft);"
        return ""

    # --- edit zone (detail pane) ---------------------------------------------

    def _render_edit_zone(self) -> None:
        config = self._config
        if config is None:
            ui.label(NO_SET_MESSAGE).style("color:var(--ink2);font-size:12.5px;")
            return
        if config.is_frozen:
            self._render_frozen_zone(config)
            return
        selected_key = self._selected_feature_key()
        if selected_key is None or self._draft is None:
            ui.label(NO_FEATURE_SELECTED).props('data-testid="no-feature-selected"').style(
                "color:var(--ink2);font-size:12.5px;"
            )
            return
        self._render_draft_zone(config, is_new=selected_key == NEW_FEATURE_SENTINEL)

    def _render_draft_zone(self, config: FeatureConfigView, *, is_new: bool) -> None:
        draft = self._draft
        assert draft is not None
        existing = None if is_new else _find_feature(config, self._selected_feature_key())
        with ui.element("div").style(
            "display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;"
        ):
            ui.label("Editing" if not is_new else "Editing · new feature").classes("lbl")
            with (
                ui.element("h2")
                .props('data-testid="editing-feature-name"')
                .style("margin:0;font-size:16px;font-weight:600;")
            ):
                ui.label(draft.key or "(new feature)")
            with ui.element("div").style("flex:1 1 240px;min-width:0;text-align:right;"):
                ui.label("Definition fingerprint").classes("lbl")
                fingerprint_badge(
                    existing.fingerprint or existing.fingerprint_preview
                    if existing is not None
                    else "",
                    preview=True,
                )
                ui.label("Final value is computed when the evaluation is created.").style(
                    "font-size:11px;color:var(--ink3);"
                )
        with card(
            extra="padding:16px;display:flex;flex-direction:column;gap:14px;margin-top:12px;"
        ):
            ui.label("Key — identifies this feature to the model").classes("lbl")
            _text_input(
                value=draft.key,
                placeholder="e.g. weather",
                on_input=lambda value: setattr(draft, "key", value),
                testid="feature-key",
            )
            with ui.element("div").style(GRID_STYLE):
                self._kind_grain_value_type(draft)
            self._render_source_or_derivation(draft)
            self._render_note(draft)
            ui.label("Description — goes into the prompt verbatim").classes("lbl")
            _textarea(
                value=draft.description,
                on_input=lambda value: setattr(draft, "description", value),
                testid="feature-description",
            )
            with ui.element("div").style(GRID_STYLE):
                self._matching_rule_grid(draft)
        self._render_bottom_cards(config, draft)
        with ui.element("div").style("display:flex;gap:10px;margin-top:12px;"):
            save = (
                ui.element("button")
                .classes("btn primary")
                .props('type="button" data-testid="save-feature"')
                .mark("save-feature")
            )
            save.on("click", cast("Callable[[], None]", self._save_draft))
            with save:
                ui.label("Save")
            if existing is not None:
                delete = (
                    ui.element("button")
                    .classes("btn secondary")
                    .props('type="button" data-testid="delete-feature"')
                    .mark("delete-feature")
                )
                delete.on(
                    "click",
                    cast("Callable[[], None]", lambda: self._delete_feature(existing.feature_id)),
                )
                with delete:
                    ui.label("Delete")

    def _kind_grain_value_type(self, draft: _FeatureDraft) -> None:
        with ui.element("div"):
            ui.label("Kind").classes("lbl")
            segmented_control(
                options=["Labelled", "Exploratory"],
                value="Exploratory" if draft.kind is Kind.EXPLORATORY else "Labelled",
                label="Kind",
                on_change=lambda value: self._set_kind(draft, value),
            )
        with ui.element("div"):
            ui.label("Grain").classes("lbl")
            if draft.kind is Kind.EXPLORATORY:
                frozen_readout("n/a — narrative only")
            else:
                _select(
                    options=[(g.value, _GRAIN_LABELS[g]) for g in Grain],
                    value=draft.grain.value,
                    label="Grain",
                    on_change=lambda value: self._set_grain(draft, value),
                    classes="rof",
                    testid="grain-select",
                )
        with ui.element("div"):
            ui.label("Value type").classes("lbl")
            if draft.kind is Kind.EXPLORATORY:
                frozen_readout("n/a — reported, not typed")
            else:
                _select(
                    options=[(v.value, _VALUE_TYPE_LABELS[v]) for v in ValueType],
                    value=draft.value_type.value,
                    label="Value type",
                    on_change=lambda value: self._set_value_type(draft, value),
                    classes="rof",
                    testid="value-type-select",
                )

    def _render_source_or_derivation(self, draft: _FeatureDraft) -> None:
        if draft.kind is Kind.EXPLORATORY:
            self._case_d_source()
            return
        if draft.grain is Grain.DERIVED:
            self._case_c_source(draft)
            return
        self._validate_against_picker()
        if draft.value_type is ValueType.ENUM:
            self._case_a_source(draft)
        elif draft.value_type is ValueType.TIME:
            self._case_b_source(draft)
        else:
            self._generic_source(draft)

    def _validate_against_picker(self) -> None:
        with ui.element("div").style("display:flex;align-items:center;gap:8px;margin-bottom:2px;"):
            ui.label("Validate against corpus").classes("lbl")
            options = [("", "none")] + [
                (str(c.corpus_id), f"{c.name} · v{c.version}") for c in self._corpora
            ]
            current = self._validate_against()
            _select(
                options=options,
                value=str(current) if current is not None else "",
                label="Validation corpus",
                on_change=_sync(self._pick_validate_corpus),
                classes="rof",
                style="max-width:220px;",
                testid="validate-corpus-select",
            )

    def _case_a_source(self, draft: _FeatureDraft) -> None:
        """README, Case A: native column + "N distinct in corpus" (item 9 —
        `CodelistService.list_columns()`, never `coverage()` directly)."""
        column = _matching_column(self._enum_columns, draft.source_column)
        with ui.element("div").style(FIELD_BOX_STYLE):
            ui.label("Source — native column").classes("lbl")
            _column_picker(draft, self._census_columns, self._enum_columns)
            if column is not None:
                ui.label(
                    f"{column.table_name} · {column.distinct_in_corpus} distinct in corpus"
                ).style("font-size:11px;color:var(--ink3);margin-top:4px;")
            with ui.element("div").style("margin-top:8px;"):
                ui.label("Codelist").classes("lbl")
                coverage = column.coverage if column is not None else None
                if coverage is None:
                    ui.label("Pick a corpus above to see codelist coverage.").style(
                        "font-size:11.5px;color:var(--ink3);"
                    )
                else:
                    ui.label(
                        f"{coverage.labelled_count} of {coverage.total_count} codes labelled"
                    ).props('data-testid="codelist-coverage"').style("font-size:12px;")
                ui.label(OPEN_CODELIST_LABEL).props(
                    'data-testid="open-codelist" aria-disabled="true" title="Codelists cross-link '
                    'not built yet"'
                ).style(
                    "font-size:11px;color:var(--ink3);cursor:default;margin-top:2px;display:block;"
                )

    def _case_b_source(self, draft: _FeatureDraft) -> None:
        """README, Case B: native column + populated-rate/format text."""
        census = _matching_census(self._census_columns, draft.source_column)
        with ui.element("div").style(FIELD_BOX_STYLE):
            ui.label("Source — native column").classes("lbl")
            _column_picker(draft, self._census_columns, self._enum_columns)
            if census is not None:
                ui.label(
                    f"{census.table_name} · {census.populated_rate * 100:.1f} % populated · HH:MM"
                ).style("font-size:11px;color:var(--ink3);margin-top:4px;")
            else:
                ui.label("HH:MM. Pick a corpus above to see the populated rate.").style(
                    "font-size:11px;color:var(--ink3);margin-top:4px;"
                )

    def _generic_source(self, draft: _FeatureDraft) -> None:
        census = _matching_census(self._census_columns, draft.source_column)
        with ui.element("div").style(FIELD_BOX_STYLE):
            ui.label("Source — native column").classes("lbl")
            _column_picker(draft, self._census_columns, self._enum_columns)
            if census is not None:
                ui.label(
                    f"{census.table_name} · {census.populated_rate * 100:.1f} % populated"
                ).style("font-size:11px;color:var(--ink3);margin-top:4px;")

    def _case_c_source(self, draft: _FeatureDraft) -> None:
        """README, Case C: the closed-catalogue derivation builder. G3's body
        (`ra2/ui/components/derivation_builder.py`) is still a stub as this
        file is written — see the module docstring."""
        ui.label("Derivation — closed catalogue").classes("lbl")
        ui.label("7 types · 6 operators").classes("mono").style(
            "font-size:10.5px;color:var(--ink3);"
        )
        derivation_builder(
            value=draft.derivation, on_change=lambda spec: self._set_derivation(draft, spec)
        )

    def _case_d_source(self) -> None:
        with ui.element("div").style(DASHED_BOX_STYLE):
            ui.label("narrative only — no source column exists for this")

    def _render_note(self, draft: _FeatureDraft) -> None:
        if draft.kind is Kind.EXPLORATORY:
            with ui.element("div").style(NOTE_WARN_STYLE):
                ui.label(
                    "An exploratory feature can never be wrong, only surprising. Promote it to "
                    "labelled only once a column or a manual sample exists to score against."
                )
            return
        if draft.grain is Grain.DERIVED:
            with ui.element("div").style(NOTE_WARN_STYLE):
                ui.label(
                    "No native column carries this, so a derivation is right — but where one does "
                    "(e.g. AnzObjFeld for vehicles involved), prefer the native column instead."
                )
            return
        if draft.value_type is ValueType.TIME:
            with ui.element("div").style(NOTE_ACCENT_STYLE):
                ui.label(
                    "The ± tolerance is part of the definition — changing it changes the "
                    "fingerprint."
                )
            return
        if draft.value_type is ValueType.ENUM:
            column = _matching_column(self._enum_columns, draft.source_column)
            coverage = column.coverage if column is not None else None
            unlabelled = (
                [c for c in coverage.codes if c.label is None] if coverage is not None else []
            )
            if unlabelled:
                affected = sum(c.count for c in unlabelled)
                with ui.element("div").style(NOTE_WARN_STYLE):
                    ui.label(
                        f"{len(unlabelled)} code(s) unlabelled, {affected} records — the feature "
                        "still runs; those records score against an unnamed code."
                    )

    def _matching_rule_grid(self, draft: _FeatureDraft) -> None:
        with ui.element("div"):
            ui.label("Matching rule").classes("lbl")
            frozen_readout(_matching_rule_label(draft))
            ui.label(_matching_rule_help(draft)).style(
                "font-size:11px;color:var(--ink3);margin-top:4px;"
            )
        with ui.element("div"):
            ui.label("Parameter").classes("lbl")
            self._parameter_control(draft)
        with ui.element("div"):
            ui.label("Scored in MVP").classes("lbl")
            scored, tone = _scored_label(draft)
            ui.label(scored).classes(tone).style("font-size:12.5px;")

    def _parameter_control(self, draft: _FeatureDraft) -> None:
        if draft.kind is Kind.EXPLORATORY:
            frozen_readout("discovery rate")
            return
        if draft.value_type is not ValueType.TIME:
            frozen_readout("none for enum" if draft.value_type is ValueType.ENUM else "—")
            return
        minutes = draft.matching_rule.tolerance_minutes or DEFAULT_TOLERANCE_MINUTES
        with ui.element("div").style("display:flex;align-items:center;gap:8px;"):
            icon_button(
                "<path d='M5 12h14'></path>",
                label="Decrease tolerance",
                size=22,
                glyph=12,
                on_click=lambda: self._step_tolerance(draft, -TOLERANCE_STEP_MINUTES),
            )
            ui.label(f"± {minutes} min").classes("mono").props(
                'data-testid="tolerance-value"'
            ).style("font-size:13px;font-weight:600;")
            icon_button(
                PLUS,
                label="Increase tolerance",
                size=22,
                glyph=12,
                on_click=lambda: self._step_tolerance(draft, TOLERANCE_STEP_MINUTES),
            )

    def _render_bottom_cards(self, config: FeatureConfigView, draft: _FeatureDraft) -> None:
        with ui.element("div").style("display:flex;gap:14px;flex-wrap:wrap;margin-top:12px;"):
            if draft.kind is Kind.EXPLORATORY:
                self._exploratory_budget_card(config, draft)
            elif draft.grain is Grain.DERIVED:
                with card(flex="1 1 300px", extra="padding:12px 14px;"):
                    ui.label("Also captured, not scored").classes("lbl")
                    ui.label(
                        "Per-vehicle and per-person detail keyed by the narrative's role codes "
                        "(B1, G1, P) is stored on every extraction; only the aggregate is scored."
                    ).style("font-size:12px;color:var(--ink2);margin-top:4px;")
            elif draft.value_type is ValueType.TIME:
                with card(flex="1 1 300px", extra="padding:12px 14px;"):
                    ui.label("Empty is not a guess").classes("lbl")
                    ui.label(
                        "A record with no time in this column leaves this feature's denominator "
                        "entirely (mvp-spec.md §8.6)."
                    ).style("font-size:12px;color:var(--ink2);margin-top:4px;")
            elif draft.value_type is ValueType.ENUM:
                with card(flex="1.4 1 300px", extra="padding:12px 14px;"):
                    ui.label("What the model is shown").classes("lbl")
                    ui.label(
                        _prompt_preview(draft, self._enum_columns, self._prompt_language())
                    ).classes("mono").style("font-size:11.5px;white-space:pre-wrap;margin-top:6px;")

    def _exploratory_budget_card(self, config: FeatureConfigView, draft: _FeatureDraft) -> None:
        count = sum(1 for f in config.features if f.kind is Kind.EXPLORATORY)
        if draft.feature_id is None:
            count += 1
        fill_pct = count / EXPLORATORY_FEATURE_CAP * 100
        with card(flex="1 1 300px", extra="padding:12px 14px;"):
            ui.label("Exploratory budget").classes("lbl")
            ui.label(f"{count} / {EXPLORATORY_FEATURE_CAP} used in this config").classes(
                "mono"
            ).props('data-testid="exploratory-budget"').style("font-size:15px;margin-top:4px;")
            bar(fill_pct=fill_pct)
            ui.label("Each one lengthens the prompt for every record in the run.").style(
                "font-size:11px;color:var(--ink3);margin-top:4px;"
            )
            if count > EXPLORATORY_FEATURE_CAP:
                with ui.element("div").style(NOTE_WARN_STYLE + "margin-top:6px;"):
                    ui.label(
                        f"Over the cap of {EXPLORATORY_FEATURE_CAP} — this feature blocks "
                        "“Create a feature set” until the set is back under it."
                    ).props('data-testid="exploratory-cap-error"')

    # --- frozen state ----------------------------------------------------------

    def _render_frozen_zone(self, config: FeatureConfigView) -> None:
        with ui.element("div").style(
            "display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;"
        ):
            ui.label("Editing · read-only").classes("lbl")
            pill(f"LOCKED · {config.locked_by_evaluations} evals", tone="accent")
        ui.label(
            f"Frozen {config.frozen_at.date().isoformat() if config.frozen_at else ''} · "
            f"cited by {config.locked_by_evaluations} evaluation(s)."
        ).props('data-testid="frozen-banner"').style(
            "font-size:12px;color:var(--ink2);margin-top:6px;"
        )
        selected_key = self._selected_feature_key()
        feature = _find_feature(config, selected_key) if selected_key else None
        if feature is None:
            ui.label("Select a feature to view it (read-only).").style(
                "font-size:12.5px;color:var(--ink2);margin-top:10px;"
            )
        else:
            with card(
                extra="padding:16px;display:flex;flex-direction:column;gap:10px;margin-top:12px;"
            ):
                with (
                    ui.element("h2")
                    .props('data-testid="frozen-feature-name"')
                    .style("margin:0;font-size:16px;font-weight:600;")
                ):
                    ui.label(feature.key)
                fingerprint_badge(feature.fingerprint or "", preview=False)
                with ui.element("div").style(GRID_STYLE):
                    frozen_readout(
                        "Exploratory" if feature.kind is Kind.EXPLORATORY else "Labelled"
                    )
                    frozen_readout(_GRAIN_LABELS[feature.grain])
                    frozen_readout(_VALUE_TYPE_LABELS[feature.value_type])
                frozen_readout(feature.source_column or "narrative only")
                ui.label(feature.description).style("font-size:12.5px;color:var(--ink2);")
                ui.label("Fixed at freeze. Results citing this config compare against it.").style(
                    "font-size:11px;color:var(--ink3);"
                )
        with card(flex="none", extra="padding:12px 14px;margin-top:12px;"):
            ui.label("Evaluations citing this config").classes("lbl")
            if config.locked_by_evaluations:
                ui.label(f"{config.locked_by_evaluations} evaluation(s) cite this config.").style(
                    "font-size:12px;color:var(--ink2);margin-top:4px;"
                )
            ui.label(
                "Editing anything here would break their reproducibility — clone instead."
            ).style("font-size:11.5px;color:var(--ink3);margin-top:4px;")

    # --- feature sets strip ---------------------------------------------------

    def _render_sets_table(self) -> None:
        feature_sets_table(
            sets=self._sets,
            selected_id=str(self._config.feature_config_id) if self._config is not None else None,
            on_select=_sync(self._pick_set),
            on_rename=_sync(self._rename_set),
            on_delete=_sync(self._delete_set),
            on_new_set=_sync(self._new_set),
        )

    # --- draft field handlers --------------------------------------------------

    def _set_kind(self, draft: _FeatureDraft, option: str) -> None:
        draft.kind = Kind.EXPLORATORY if option == "Exploratory" else Kind.LABELLED
        if draft.kind is Kind.EXPLORATORY:
            draft.source_column = None
            draft.derivation = None
            draft.matching_rule = MatchingRule(kind=MatchingRuleKind.NONE)
        else:
            draft.matching_rule = _default_matching_rule(draft.value_type)
        self._render()

    def _set_grain(self, draft: _FeatureDraft, value: str) -> None:
        draft.grain = Grain(value)
        if draft.grain is Grain.DERIVED:
            draft.source_column = None
        else:
            draft.derivation = None
        self._render()

    def _set_value_type(self, draft: _FeatureDraft, value: str) -> None:
        draft.value_type = ValueType(value)
        draft.matching_rule = _default_matching_rule(draft.value_type)
        self._render()

    def _set_derivation(self, draft: _FeatureDraft, derivation: DerivationSpec) -> None:
        draft.derivation = derivation
        draft.value_type = _value_type_for_derivation(derivation)
        self._render()

    def _step_tolerance(self, draft: _FeatureDraft, delta: int) -> None:
        current = draft.matching_rule.tolerance_minutes or DEFAULT_TOLERANCE_MINUTES
        draft.matching_rule = MatchingRule(
            kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=max(0, current + delta)
        )
        self._render()

    # --- toolbar/filter actions -----------------------------------------------

    async def _pick_set(self, feature_config_id: str) -> None:
        app.storage.client[SET_KEY] = feature_config_id
        app.storage.client[FEATURE_KEY] = None
        self._draft = None
        await self.reload()

    async def _pick_language(self, language: str) -> None:
        app.storage.client[LANGUAGE_KEY] = language
        await self._reload_corpus_scoped_columns()
        self._render()

    async def _pick_validate_corpus(self, corpus_id: str) -> None:
        app.storage.client[VALIDATE_KEY] = corpus_id or None
        await self._reload_corpus_scoped_columns()
        self._render()

    async def _pick_type_filter(self, value: str) -> None:
        current = feature_filters()
        app.storage.client[FILTERS_KEY] = FeatureFilters(
            type_filter=value or None, state_filter=current.state_filter
        )
        set_table_state(FEATURES_TABLE, _reset_page(self._table_state()))
        self._render()

    async def _pick_state_filter(self, value: str) -> None:
        current = feature_filters()
        app.storage.client[FILTERS_KEY] = FeatureFilters(
            type_filter=current.type_filter, state_filter=value or None
        )
        set_table_state(FEATURES_TABLE, _reset_page(self._table_state()))
        self._render()

    async def _sort(self, key: str) -> None:
        set_table_state(FEATURES_TABLE, self._table_state().toggled(key))
        self._render()

    async def _page(self, page: int) -> None:
        current = self._table_state()
        set_table_state(
            FEATURES_TABLE, TableState(current.sort_key, current.sort_dir, page, current.page_size)
        )
        self._render()

    async def _page_size(self, size: int) -> None:
        current = self._table_state()
        set_table_state(FEATURES_TABLE, TableState(current.sort_key, current.sort_dir, 1, size))
        self._render()

    # --- selection -------------------------------------------------------------

    def _select_feature(self, feature_id: FeatureId) -> None:
        config = self._config
        if config is None:
            return
        feature = _find_feature(config, str(feature_id))
        if feature is None:
            return
        app.storage.client[FEATURE_KEY] = str(feature_id)
        self._draft = _draft_from(feature)
        self._render()

    def _start_new_feature(self) -> None:
        app.storage.client[FEATURE_KEY] = NEW_FEATURE_SENTINEL
        self._draft = _new_draft()
        self._render()

    # --- mutating actions --------------------------------------------------

    async def _save_draft(self) -> None:
        config = self._config
        draft = self._draft
        if config is None or draft is None:
            return
        if not draft.key.strip():
            ui.notify("Give the feature a key before saving.", type="warning")
            return
        try:
            if draft.feature_id is None:
                await self._services.feature.add_feature(
                    config.feature_config_id,
                    key=draft.key,
                    kind=draft.kind,
                    description=draft.description,
                    grain=draft.grain,
                    source_column=draft.source_column,
                    derivation=draft.derivation,
                    value_type=draft.value_type,
                    matching_rule=draft.matching_rule,
                    validate_against=self._validate_against(),
                )
            else:
                await self._services.feature.edit_feature(
                    config.feature_config_id,
                    draft.feature_id,
                    key=draft.key,
                    kind=draft.kind,
                    description=draft.description,
                    grain=draft.grain,
                    source_column=draft.source_column,
                    derivation=draft.derivation,
                    value_type=draft.value_type,
                    matching_rule=draft.matching_rule,
                    validate_against=self._validate_against(),
                )
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        saved_key = draft.key
        await self.reload()
        config = self._config
        if config is not None:
            saved = next((f for f in config.features if f.key == saved_key), None)
            if saved is not None:
                self._select_feature(saved.feature_id)
                return
        self._render()

    async def _delete_feature(self, feature_id: FeatureId) -> None:
        config = self._config
        if config is None:
            return
        try:
            await self._services.feature.delete_feature(config.feature_config_id, feature_id)
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        app.storage.client[FEATURE_KEY] = None
        self._draft = None
        await self.reload()

    async def _freeze(self) -> None:
        config = self._config
        if config is None:
            return
        try:
            await self._services.feature.freeze(
                config.feature_config_id, validate_against=self._validate_against()
            )
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        await self.reload()

    async def _clone(self) -> None:
        config = self._config
        if config is None:
            return
        try:
            clone = await self._services.feature.clone(
                config.feature_config_id, name=f"{config.name} (clone)"
            )
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        app.storage.client[SET_KEY] = str(clone.feature_config_id)
        app.storage.client[FEATURE_KEY] = None
        self._draft = None
        await self.reload()

    async def _rename_set(self, feature_config_id: str, name: str) -> None:
        try:
            await self._services.feature.rename(FeatureConfigId(feature_config_id), name=name)
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        await self.reload()

    async def _delete_set(self, feature_config_id: str) -> None:
        try:
            await self._services.feature.delete(FeatureConfigId(feature_config_id))
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        if app.storage.client.get(SET_KEY) == feature_config_id:
            app.storage.client[SET_KEY] = None
        await self.reload()

    async def _new_set(self) -> None:
        try:
            created = await self._services.feature.create_draft(name="New feature set")
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        app.storage.client[SET_KEY] = str(created.feature_config_id)
        app.storage.client[FEATURE_KEY] = None
        self._draft = None
        await self.reload()


# --- module-level pure helpers ------------------------------------------------


def _type_label(feature: FeatureView) -> str:
    if feature.kind is Kind.EXPLORATORY:
        return "exploratory"
    return _TYPE_LABELS[feature.grain]


def _source_line(feature: FeatureView) -> str:
    if feature.kind is Kind.EXPLORATORY:
        return "narrative only"
    if feature.validation_errors:
        return f"{feature.source_column or 'derived'} · {feature.validation_errors[0]}"
    if feature.grain is Grain.DERIVED and feature.derivation is not None:
        return type(feature.derivation).__name__
    return feature.source_column or "narrative only"


def _render_fp_or_error(feature: FeatureView) -> None:
    if feature.validation_errors:
        ui.html(svg(ALERT_TRIANGLE, size=14, stroke=1.8), tag="span", sanitize=False).style(
            "color:var(--danger);display:inline-flex;"
        )
        return
    fingerprint_badge(
        feature.fingerprint or feature.fingerprint_preview, preview=feature.fingerprint is None
    )


def _feature_count_text(config: FeatureConfigView) -> str:
    labelled = sum(1 for f in config.features if f.kind is Kind.LABELLED)
    exploratory = sum(1 for f in config.features if f.kind is Kind.EXPLORATORY)
    return f"{labelled} + {exploratory} features"


def _filtered_features(
    features: Sequence[FeatureView], filters: FeatureFilters
) -> tuple[FeatureView, ...]:
    rows = list(features)
    if filters.type_filter is not None:
        rows = [f for f in rows if _type_label(f) == filters.type_filter]
    if filters.state_filter == "error":
        rows = [f for f in rows if f.validation_errors]
    elif filters.state_filter == "ok":
        rows = [f for f in rows if not f.validation_errors]
    return tuple(rows)


def _sort_value(feature: FeatureView, key: str) -> tuple[int, str]:
    if key == "key":
        return (0, feature.key.lower())
    if key == "type":
        return (0, _type_label(feature))
    return (feature.ordinal, "")


def _visible_features(
    features: Sequence[FeatureView], filters: FeatureFilters, state: TableState
) -> tuple[FeatureView, ...]:
    """The page of rows the flat list currently shows — filtered, sorted and
    paged over the whole, already-fetched set (module docstring, point 1)."""
    rows = list(_filtered_features(features, filters))
    rows.sort(key=lambda f: _sort_value(f, state.sort_key), reverse=state.sort_dir is SortDir.DESC)
    start = (state.page - 1) * state.page_size
    return tuple(rows[start : start + state.page_size])


def _reset_page(state: TableState) -> TableState:
    return TableState(state.sort_key, state.sort_dir, 1, state.page_size)


def _find_feature(config: FeatureConfigView, feature_id: str | None) -> FeatureView | None:
    if feature_id is None:
        return None
    return next((f for f in config.features if str(f.feature_id) == feature_id), None)


def _matching_column(
    columns: Sequence[ColumnMappingView], source_column: str | None
) -> ColumnMappingView | None:
    if source_column is None:
        return None
    return next((c for c in columns if c.column_name == source_column), None)


def _matching_census(
    columns: Sequence[CensusColumnView], source_column: str | None
) -> CensusColumnView | None:
    if source_column is None:
        return None
    return next((c for c in columns if c.column_name == source_column), None)


def _column_picker(
    draft: _FeatureDraft,
    census_columns: Sequence[CensusColumnView],
    enum_columns: Sequence[ColumnMappingView],
) -> None:
    """The `.tok`-chip column picker collapses to a native select over every
    column the corpus picker has told this view about, plus whatever the
    draft already names (so a column from a different corpus keeps showing).
    Empty when no corpus has been picked yet — a plain text field instead."""
    names = sorted({c.column_name for c in census_columns} | {c.column_name for c in enum_columns})
    if draft.source_column and draft.source_column not in names:
        names = sorted([*names, draft.source_column])
    if not names:
        _text_input(
            value=draft.source_column or "",
            placeholder="native column name",
            on_input=lambda value: setattr(draft, "source_column", value or None),
            testid="source-column-input",
        )
        return
    _select(
        options=[(n, n) for n in names],
        value=draft.source_column or names[0],
        label="Source column",
        on_change=lambda value: setattr(draft, "source_column", value or None),
        classes="rof",
        testid="source-column-select",
    )


def _default_matching_rule(value_type: ValueType) -> MatchingRule:
    """mvp-spec.md §8.4's table, collapsed to what this view lets the analyst
    change: every type is exact except `time`, which defaults to a tolerance
    (the design's own drawn case)."""
    if value_type is ValueType.TIME:
        return MatchingRule(
            kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=DEFAULT_TOLERANCE_MINUTES
        )
    if value_type is ValueType.DECIMAL:
        return MatchingRule(kind=MatchingRuleKind.EXACT, decimal_precision=2)
    return MatchingRule(kind=MatchingRuleKind.EXACT)


def _value_type_for_derivation(derivation: DerivationSpec) -> ValueType:
    """mvp-spec.md §8.3's result column, as a lookup — `AnyObjectMatches` /
    `AnyPersonMatches` yield boolean, `MaxOrdinal` / `MinOrdinal` yield a code
    (rendered as `enum`), everything else an integer."""
    name = type(derivation).__name__
    if name in ("AnyObjectMatches", "AnyPersonMatches"):
        return ValueType.BOOLEAN
    if name in ("MaxOrdinal", "MinOrdinal"):
        return ValueType.ENUM
    return ValueType.INTEGER


def _matching_rule_label(draft: _FeatureDraft) -> str:
    if draft.kind is Kind.EXPLORATORY:
        return "n/a — no ground truth"
    if draft.matching_rule.kind is MatchingRuleKind.WITHIN_TOLERANCE:
        return "within tolerance"
    return "exact"


def _matching_rule_help(draft: _FeatureDraft) -> str:
    if draft.kind is Kind.EXPLORATORY:
        return "no structured counterpart exists to match against."
    if draft.value_type is ValueType.ENUM:
        return "the emitted code must equal the ground-truth code."
    if draft.matching_rule.kind is MatchingRuleKind.WITHIN_TOLERANCE:
        return "matches within the parameter's tolerance, in minutes."
    return "matches after normalisation (mvp-spec.md §8.4)."


def _scored_label(draft: _FeatureDraft) -> tuple[str, str]:
    if draft.kind is Kind.EXPLORATORY:
        return "No — reported, not scored", "ink2"
    if not _is_scalar(draft.grain):
        return "No — captured, not scored", "ink2"
    return "Yes — scalar", "ok"


def _is_scalar(grain: Grain) -> bool:
    return grain in (Grain.ACCIDENT, Grain.DERIVED)


def _prompt_preview(
    draft: _FeatureDraft, enum_columns: Sequence[ColumnMappingView], language: str
) -> str:
    lines = [f"{draft.key or '<key>'} — enum. Emit the code."]
    column = _matching_column(enum_columns, draft.source_column)
    if column is not None and column.coverage is not None:
        for usage in column.coverage.codes[:3]:
            lines.append(f"{usage.code} = {usage.label or '(unlabelled)'}")
    return "\n".join(lines)


def _set_chip_text(summary: FeatureSetSummary) -> str:
    return f"set · {summary.name} v{summary.version}"


def _set_chip_text_for(config: FeatureConfigView) -> str:
    return f"set · {config.name} v{config.version}"


# --- native-control helpers (see module docstring's fidelity judgment call) ---


def _select(
    *,
    options: Sequence[tuple[str, str]],
    value: str,
    label: str,
    on_change: Callable[[str], None],
    classes: str = "rof",
    style: str = "",
    testid: str = "select",
) -> Element:
    element = (
        ui.element("select")
        .classes(classes)
        .props(f'aria-label="{label}" data-testid="{testid}"')
        .mark(testid)
        .style(style)
    )
    element.on(
        "change",
        lambda event: on_change(str(event.args)),
        js_handler="(e) => emit(e.target.value)",
    )
    with element:
        for option_value, text in options:
            option = ui.element("option").props(f'value="{escape(option_value, quote=True)}"')
            if option_value == value:
                option.props("selected")
            with option:
                ui.label(text)
    return element


def _text_input(
    *, value: str, placeholder: str, on_input: Callable[[str], None], testid: str
) -> Element:
    element = (
        ui.element("input")
        .classes("chip")
        .props(
            f'type="text" value="{escape(value, quote=True)}" '
            f'placeholder="{escape(placeholder, quote=True)}" data-testid="{testid}"'
        )
        .mark(testid)
        .style("width:100%;")
    )
    element.on(
        "input", lambda event: on_input(str(event.args)), js_handler="(e) => emit(e.target.value)"
    )
    return element


def _textarea(*, value: str, on_input: Callable[[str], None], testid: str) -> Element:
    element = (
        ui.element("textarea")
        .props(f'data-testid="{testid}" rows="3"')
        .mark(testid)
        .style(
            "width:100%;border:1px solid var(--rule);border-radius:3px;padding:8px 10px;"
            "font-family:var(--sans);font-size:12.5px;line-height:1.55;resize:vertical;"
        )
    )
    element.on(
        "input", lambda event: on_input(str(event.args)), js_handler="(e) => emit(e.target.value)"
    )
    with element:
        # A `<textarea>`'s default value is its text content, not a `value=`
        # attribute — escaped here (never trusted `sanitize=False` HTML, since
        # `value` is analyst-typed prose) so the initial render round-trips a
        # description containing `<`, `>` or `&` byte-for-byte.
        ui.html(escape(value), sanitize=False)
    return element


def _sync[**P](action: Callable[P, Awaitable[None]]) -> Callable[P, None]:
    """Adapt an async handler to a sync callback type — the identical
    typing formality `census_view._sync` documents."""
    return cast("Callable[P, None]", action)
