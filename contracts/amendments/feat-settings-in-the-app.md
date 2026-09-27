# Amendment — `feat/settings-in-the-app`

> **Applied file by file in the stage whose code needs it**, as
> `fix-settings-with-no-reader` was. No wave is running.

`plan-settings-in-the-app.md`, design `sw-design.md` **SD43**. Five frozen
files (four at Stage 1; `errors.py`, §5, found in Stage 2) and **one revision** (`app_setting`), whose author is this branch's
implementer.

The defect: the Models card's settings dialog draws an endpoint and a timeout,
and **Save does not save**. `evaluation_view._save_settings` notifies *"Set
RA2_LLM_BASE_URL=… and RA2_LLM_TIMEOUT_S=…, then restart."* — honest, and the
reason `docs/risk-assesment.md` E3 exists: the one person who can change the
endpoint is a developer, working on the machine that holds real data.

**Why a table and not a `config.json`** (plan §2): the store has to be writable
by the app, and the app already has one — repositories, migrations,
transactions. A file adds a second mechanism with a precedence rule, and cannot
carry a comment saying what a key does.

---

## 1. `ra2/infra/config.py` — docstrings only *(Stage 3)*

```diff
     #: **The host must be loopback.** `OllamaLLMClient` refuses anything else
     #: at construction, and there is deliberately no opt-out setting: an
     #: opt-out is how "no data leaves the host" (N1) becomes "no data leaves
     #: the host by default" (mvp-spec.md §19.10, §15 F4).
+    #:
+    #: **The seed, not the value** (`SD43`). The settings dialog stores an
+    #: endpoint in `app_setting`, and a stored row wins; this is what a host
+    #: with no row uses. A stored row is refused on the same loopback rule at
+    #: startup, so nothing reaches the client that this field could not.
     llm_base_url: str = "http://127.0.0.1:11434/v1"
```

```diff
     #: Per-call timeout. Belongs to client construction, not to a per-call
     #: argument — which is why `LLMClient.extract` never took one.
+    #: Like `llm_base_url`, **the seed** for a stored value (`SD43`).
```

**Stage 3, not Stage 1** as the plan's §6 first said: these sentences say a
stored row wins, and that is true only once Stage 3 reads the override at
startup. Written in Stage 1 they would describe a store that does not exist for
two stages — the defect class `SD42` closed. No field, default or validator
changes, so `SD42`'s gate is untouched: `main.py` keeps reading both.

## 2. `ra2/persistence/models.py` — `+ AppSetting` *(Stage 2)*

```diff
+class AppSetting(Base):
+    """A setting an analyst changed from the product (sw-design.md SD43).
+
+    **Append-only.** A save adds a row and the newest per key wins, the way
+    a re-run adds runs (§12.2) — and the history answers "when did the
+    endpoint change", the first question a week of runs against the wrong
+    Ollama raises. Nothing updates or deletes one except `just reset`.
+
+    **Referenced by nothing**, and it references nothing. Keys are the closed
+    set `domain.settings.SettingKey`; a key this build does not know is
+    ignored, so a database written by a newer build still opens.
+    """
+
+    __tablename__ = "app_setting"
+    __table_args__ = (Index("ix_app_setting_key_changed_at", "key", "changed_at"),)
+
+    #: A plain string, no `NewType`: nothing joins against it (`P2-D6`'s
+    #: reasoning for `code_value`).
+    id: Mapped[str] = mapped_column(String(_ID_LEN), primary_key=True)
+    key: Mapped[str] = mapped_column(String(64))
+    #: JSON, so one column holds a URL and an integer alike.
+    value_json: Mapped[str]
+    changed_at: Mapped[datetime]
```

Appended after `ModelQualification`, the table it copies the shape of.

## 3. `ra2/services/protocols.py` — `+ ConnectionSettings` *(Stage 2)*

```diff
 __all__ = [
     "CensusInput",
     "CensusMaterialiser",
     "CensusTableInput",
+    "ConnectionSettings",
     "EnumCodeTableProvider",
```

```diff
+@runtime_checkable
+class ConnectionSettings(Protocol):
+    """The LLM endpoint and timeout **as they are now** (sw-design.md SD43).
+
+    Satisfied structurally by `SettingsService`, so `evaluation_service` and
+    `run_service` never import it — the `ScoreSubmitter` trick once more.
+
+    Plain attributes, not coroutines: the values are resolved at startup and
+    after each accepted save, and held. Nothing on the record loop's path
+    reads the database for them.
+    """
+
+    @property
+    def endpoint(self) -> str: ...
+
+    @property
+    def timeout_s(self) -> int: ...
```

The five reads that move to it: `EvaluationService.connection_status`
(endpoint and timeout), its `test_connection` default, `RunService`'s timeout,
and its `run.llm_endpoint` pin.

## 4. `ra2/services/container.py` — `+ Services.settings` *(Stage 2)*

```diff
+from ra2.services.settings_service import SettingsService
```

```diff
     lifecycle: LifecycleService
     qualification: QualificationService
+    settings: SettingsService
```

The dialog saves through a service the view is handed, like every other write
in `ui/` (Do-NOT #7).

## 5. `ra2/services/errors.py` — `+ SettingRefusedError` *(Stage 2)*

```diff
 from ra2.domain.prompt import PromptValidationError
+from ra2.domain.settings import SettingRefusal
```

```diff
+class SettingRefusedError(ServiceError):
+    """A setting the analyst tried to store is refused (sw-design.md SD43).
+
+    Carries a **code**, not a sentence (CLAUDE.md: findings, not prose): the
+    settings dialog renders it from one table in `ui/`, and tests assert on
+    `refusal`. Nothing is stored when this is raised.
+    """
+
+    def __init__(self, refusal: SettingRefusal) -> None:
+        super().__init__(f"setting refused: {refusal.value}")
+        self.refusal = refusal
```

and a comment after `RunActiveError` saying it **also refuses a settings
save**: a rebind under a queued or running run would move its endpoint between
two of its records while `run.llm_endpoint` pins one. Reused rather than a
second error for the same two statuses (`lifecycle_service.ACTIVE_STATUSES`),
which would be a second meaning of "active".

**Missed at Stage 1.** The plan named the refusals and never the class that
carries them; `errors.py` is where every service error lives, frozen, and each
later one arrived by amendment the same way. Registered in
`tests/test_p5_contract.py`'s `POST_PHASE_5_ERRORS`, whose purpose is exactly
that an addition is an entry somebody wrote.
