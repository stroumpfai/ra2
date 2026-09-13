# Phase 3 Plan — Prompts and Evaluation

Delivers the two views drawn in `design/prompt-evaluation/README.md` —
**Prompts** (the versioned wording around the feature descriptions) and
**Evaluation** (pin one corpus + one frozen feature set + one template, run it
across several local models) — plus the machinery underneath the Launch button:
the one `LLMClient` implementation, the extraction output schema, and the
restart-safe run worker. That is `mvp-spec.md` §1's **F5** and **F6**, plus
the provenance half of **F12**.

Scoring, Results and Mismatches (F7–F11) remain out of scope. This phase ends
where a corpus has been extracted across several models, every run carries
enough provenance to reproduce it, and **nothing yet scores any of it**.

**Contracts for implementing agents, in authority order:** `mvp-spec.md` (what)
→ `sw-design.md` (how, including its §15 — see §0 below) →
`design/prompt-evaluation/README.md` (pixel/behaviour fidelity for the two
screens) → this file (who builds what, and what they may touch). On a conflict,
`sw-design.md` wins over this file; `mvp-spec.md` wins over both — same rule as
`plan-m0-m5.md` §0 and `plan-phase-2.md`, restated because it is the rule that
makes disjoint sub-agents safe.

Same shape as `plan-phase-2.md`: one document carrying scope, milestones *and*
the wave-by-wave sub-agent breakdown.

---

## 0. The architecture this plan sits under — `sw-design.md` §15

`sw-design.md` §14 was written **before** `plan-phase-2.md` and is what that
plan pointed its agents at for every "how" question. **§15 now does the same
job for this phase, and it is written** — no sub-agent in any wave below has
to invent a run-worker design in its own worktree.

It settles the five things that were open when this plan was drafted:

| # | Settled in | What |
|---|---|---|
| 1 | §15.1 | `prompt_template` storage, the closed slot catalogue, copy-on-write, the two fingerprints, why token counts are estimates |
| 2 | §15.2 | Where the per-evaluation codelist snapshot and the final fingerprints live (`evaluation_feature`), and why "evaluation creation" in `mvp-spec.md` §8.5's sense is the launch commit |
| 3 | §15.3 | The extraction transaction boundary — one record, one commit — and why `UNIQUE (run_id, record_id)` *is* the resume key |
| 4 | §15.4 | The run worker on the phase-1 `TaskRunner` seam: serial, bounded counted retries, progress derived from committed rows, explicit Resume |
| 5 | §15.5, §15.6 | The `openai` adapter's placement and the loopback guard; the NVML probe and why a library load is not N3's shell-out |

`sw-design.md` §13 carries the five deviations that follow — `SD11`–`SD15`.

**Everything below is subordinate to it.** Where this file and §15 disagree,
§15 wins and this file gets corrected in the same commit; where §15 is silent,
an agent follows the nearest existing pattern rather than inventing one
(`CLAUDE.md`).

---

## 1. Clarifications

Asked before writing the rest of this plan, because each answer changes its
shape. Recorded here rather than only in chat history, so a later reader does
not have to guess why a scope line reads the way it does.

| # | Question | Answer | Consequence |
|---|---|---|---|
| Q1 | How deep past the two views? The Evaluation progress column (live bars, parse-failure counts, median latency) only has real content if runs actually execute. | **Views + real extraction (F5–F6, and F12's provenance).** The real Ollama client, the restart-safe worker, and `extraction`/`extraction_value`/`extraction_entity` persistence. Scoring stays out. | The largest phase so far: 5 agents in Wave 1, 3 in Wave 2. It also ends phase 1's "no egress at all" posture — replaced by a **loopback-only** rule (§15 F4) rather than dropped. |
| Q2 | Where do prompt templates live? `mvp-spec.md` §10.2 says "a versioned **on-disk** template", but the design's version list (citation counts, per-version fingerprint, delete-only-when-uncited, an ACTIVE flag) is a database shape, and §5's data model has no table for it. | **A new `prompt_template` table**, and `mvp-spec.md` §5 + §10.2 are corrected to say so. | Copy-on-write lives in one store, so "delete only when uncited" is a foreign key and not a filesystem convention. §5 amendment listed in §2.4. |
| Q3 | The Models card disables a model that "exceeds 24 GB VRAM". Ollama reports tag, digest and size; it does **not** report the host's VRAM. Where does the number come from? | **Probe the host GPU.** | Collides head-on with `mvp-spec.md` N3 / `sw-design.md` §10 — "no shell-outs". Resolved, not waived: probe through the **NVML library bindings** (`nvidia-ml-py`, a `ctypes` load of `libnvidia-ml`, Windows and Linux, no subprocess), behind a `GpuProbe` protocol, with a config override and an honest "unknown" state when there is no NVIDIA GPU. Never `nvidia-smi`. See §15 F5 and R2. |
| Q4 | The Ollama connection settings dialog behind the gear button is explicitly undesigned (design open question 1). | **Build a minimal dialog** to this plan's own design — endpoint, timeout, "refresh model list" — the way `plan-phase-2.md` C2 settled the undrawn Add-feature panel. | One more component (L3), no design round-trip. Its three controls are exactly the three settings the adapter already takes. |

Smaller open items — the design's own "Open questions for the team" and the
decisions §15 will have to make — resolved here rather than left blocking, each
reversible:

| # | Item | Resolution |
|---|---|---|
| C1 | Design open question 2: does the prompt language belong to the template or the evaluation? | **The evaluation.** `evaluation.prompt_language` — which is also the first real home for a value that is currently a *view-local* selector in both `codelists_view.py` and `features_view.py` and is persisted nowhere. `{{language}}` therefore stops being "unused": it resolves to that value, and stays **optional** in a template (unlike `{{feature_block}}` and `{{narrative}}`, which are required). |
| C2 | Design open question 3: templates are bare integers with no name. | **Bare integers stay.** One lineage, `v1…vN`, exactly as drawn. Names are what you need when templates fork; nothing in the MVP forks them, and `run.prompt_template_version` (spec §5) is an integer already. |
| C3 | Design open question 4: empty states, and does an unreachable endpoint block Launch? | Empty states: the standard phase-1/2 empty card ("no versions yet" / "no runs yet"), no new pattern. **An unreachable endpoint disables Launch** with the reason rendered next to the endpoint line, as the design asks — not a toast. Reachability is re-checked when the dialog's "refresh" is pressed and on view load, never on a timer. |
| C4 | Design open question 5: are "Preview with record 1" (Prompts) and "Preview prompt" (Evaluation) the same screen? | **Yes — one component, two entry points.** Both resolve the current template against a feature set and one record and make **no model call**. Prompts resolves against the *active* feature set and record 1; Evaluation resolves against its own pinned inputs. Owned by L3, placed by L1 and L2. |
| C5 | The design's Evaluation step 2 note reads "Freezes when the first run executes." | **Wrong as of phase 2.** `plan-phase-2.md` §15 F2 froze a `feature_config` at "Create a feature set", and `mvp-spec.md` §9 was corrected to "already frozen from the moment it was created — an evaluation only ever cites an already-frozen config". L2 renders the corrected copy: the set is *already* frozen; cloning is how you change it. The design file is stale here, the spec is not. |
| C6 | The resolved prompt's exact token count ("1 842 tokens"). | **An estimate, labelled as one.** An exact count needs the model's tokeniser, and every tokeniser package downloads its vocabulary — egress, forbidden by N1. The preview reads `≈ 1 842 tokens` from a pure `estimate_tokens()`; the **real** counts (`prompt_tokens`, `completion_tokens`) come back from the endpoint per call and are stored per extraction, which is where they matter. |
| C7 | The design's `--danger` / `--danger-soft` note ("they belong in the shared token set"). | Already true — `theme.py` has them since phase 1. No change. |

---

## 2. Scope

### 2.1 In

| # | Deliverable |
|---|---|
| P21 | Contract freeze: `prompt_template`, `run`, `extraction*`, `evaluation_feature`, the amended `evaluation`, three new ids, three new seams, `sw-design.md` §15, the doc corrections in §2.4 |
| P22 | Prompt template domain: the closed slot catalogue, save-time validation, feature-block rendering, template fingerprint, token estimate |
| P23 | Extraction domain: the `mvp-spec.md` §10.3 output schema built per feature set, parse + normalise, per-entity capture, parse failure as a recorded outcome |
| P24 | Prompt template CRUD: copy-on-write versioning, the active flag, delete only when uncited |
| P25 | Prompt resolution / preview: template + feature set + record → resolved text + token estimate, **no model call** |
| P26 | `OllamaLLMClient` — the one `openai` import — with the loopback guard, bounded counted retries, and the model catalogue (tag, digest, size, reachability) |
| P27 | `GpuProbe`: NVML-backed VRAM + GPU name, config override, honest "unknown" |
| P28 | Evaluation drafts and launch: pin corpus + frozen config + template + models + decoding + size; snapshot `enum_codelist_json` and resolve each feature's final fingerprint at launch |
| P29 | The run worker: one run per selected model, serial, restart-safe (resumes from the last committed extraction), progress, dev marking |
| P30 | Provenance: every run stores model + digest, template version + fingerprint, temperature, seed, config + per-feature fingerprints, corpus + version, host, GPU, endpoint (`mvp-spec.md` §19.8) |
| P31 | `/api/v1/prompt-templates/*`, `/api/v1/evaluations/*`, `/api/v1/runs/*`, `/api/v1/models` |
| P32 | Prompts view, to the design (`PromptTemplate - A source.dc.html`) |
| P33 | Evaluation view, to the design (`Evaluation.dc.html`), including the Ollama settings dialog (Q4) and the shared prompt-preview component (C4) |
| P34 | The navigation change: an eighth entry, **Prompts**, in the Configure group after Features — and the J4/J5/J6 updates that follow from it |
| P35 | Two new E2E journeys (J9 Prompts, J10 Evaluation) and the fixture/unit/backend/UI layers under them |
| P36 | **Layer 5 comes alive** — the first `tests/eval` suite behind `@pytest.mark.eval` against a real local Ollama, plus `evals/baseline.json`. `CLAUDE.md`'s test-layer table assigns `tests/eval` to phase 3, and this is the phase that first has an endpoint to talk to (§10.4) |

### 2.2 Out of phase 3

Scoring (`mvp-spec.md` §11) — that is F7, F8, F9 and F10 — and Mismatch
review (F11). Their nav entries keep routing to `placeholder_view`. Entity **scoring**
(captured, never scored — `mvp-spec.md` §10.3, unchanged). Per-language result breakdowns.
Cross-evaluation views. Batched feature prompts (`mvp-spec.md` §10.1's fallback option).
Docker and the installer. **Not** the eval layer — `tests/eval` is P36, and
§10.4 says who runs it and where.

### 2.3 Deliberately deferred inside phase 3

- **Concurrency across models.** Runs execute **serially**, one model at a
  time. The GPU is the bottleneck and the design draws exactly this (one
  `running`, the rest `queued`). `RA2_RUN_CONCURRENCY` exists, defaults to 1,
  and nothing in this phase raises it.
- **Auto-resume at startup.** A run interrupted by a restart is left
  `interrupted`, and the Evaluation view offers **Resume** on it. The worker is
  restart-*safe* and resumable (N6); it does not silently restart work the user
  may not want restarted. One button, one explicit action.
- **Streaming progress.** The UI polls `GET /api/v1/tasks/{id}` with
  `ui.timer`, exactly as import does (`sw-design.md` §9). No websocket push,
  no SSE.
- **A second prompt lineage.** C2.

### 2.4 Documents this phase corrects

Same-commit corrections, per `CLAUDE.md`'s "where it is wrong, raise it and
change *that file* first". All are Wave 0's, all reviewed at the §5.3 gate.

| Document | Correction |
|---|---|
| `sw-design.md` | **§15 and `SD11`–`SD15` are already written** (§0). Wave 0's job is to keep them true — any change it makes to a table, a seam or a name lands in §15 in the same commit. |
| `mvp-spec.md` §5 | + `prompt_template`; + `evaluation_feature`; `evaluation` gains its draft/decoding columns; `run` gains `prompt_template_id` and `status` values. |
| `mvp-spec.md` §10.2 | "a versioned **on-disk** template" → a versioned template **row** (Q2). |
| `mvp-spec.md` §3 | Structured output is Pydantic → JSON Schema → the endpoint's constrained decoding through the **`openai` SDK**. **PydanticAI is dropped** (§15 F3). |
| `mvp-spec.md` §14 N3 | Unchanged as written — but §15 must record that the GPU probe is a library `ctypes` load, *not* a shell-out, so the next reader does not read `nvidia-smi` into it (Q3). |
| `CLAUDE.md` | "one per phase — A3 for phase 1, D3 for phase 2" → "…, H3 for phase 3". "**No egress at all in phase 1**" → the phase-3 rule: no egress except the configured LLM endpoint, which must be loopback (§19.10, §15 F4). |
| `CONTRACTS.md` | A "Phase 3 — owner: M17 (Wave 0)" section in the shape of the existing phase-2 one. |
| `pyproject.toml` | + `openai`, + `nvidia-ml-py`, both pinned. (Frozen at M0 — "every M0–M8 dependency pinned" — so this is a Wave 0 amendment, not a casual add.) |
| `.importlinter` | The `one-llm-seam` contract's forbidden list gains `pynvml` alongside `openai`/`ollama`: the probe is an adapter too, and `ra2/infra/` stays the only place either lives. |

---

## 3. What's new in the data model

Full definitions are `mvp-spec.md` §5 (as corrected by §2.4) and
`sw-design.md` §15; this is an orientation table, not the source of truth.

| Table | New / existing | Note |
|---|---|---|
| `prompt_template` | **new, beyond spec §5** (Q2) | `(id, version, source, created_at, activated_at, fingerprint)`. Never updated — a save is a new row (`Do-NOT #2` in spirit, copy-on-write in the design's words). `version` unique. |
| `evaluation` | **changed** | + `prompt_template_id` FK, `prompt_language` (C1), `temperature`, `seed`, `size` (`full`/`dev`), `selected_models_json`, `launched_at`. Editable while `launched_at IS NULL` ("Save draft"); immutable after. |
| `evaluation_feature` | **new, beyond spec §5** | `(evaluation_id, feature_id, enum_codelist_json, fingerprint)`. Spec §5 puts both on `feature`, but phase 2 made a frozen `feature_config` corpus-**independent** (`plan-phase-2.md` §15 F2), so the codelist snapshot and the final fingerprint cannot resolve until an evaluation fixes a corpus. Written once, in the launch transaction. This is the second caller of `domain/fingerprint.py` that `plan-phase-2.md` Q3 promised. |
| `run` | new (spec-defined, not yet in `models.py`) | Spec §5's columns, + `prompt_template_id` (the version integer alone cannot resolve exact text) and a `status` of `queued`/`running`/`done`/`failed`/`interrupted`. |
| `extraction` | new (spec-defined) | **IMMUTABLE.** `UNIQUE (run_id, record_id)` — that constraint *is* the resume key (§8, I3). |
| `extraction_value` | new (spec-defined) | `(extraction_id, feature_id, value_raw, value_normalised, present_flag, evidence_span)` |
| `extraction_entity` | new (spec-defined) | Captured, never scored (`mvp-spec.md` §10.3). |

**No denormalised progress counter anywhere.** `records_done` is
`COUNT(extraction WHERE run_id = …)`. A counter would be a second source of
truth that a restart could disagree with; the count cannot be, which is the
whole reason per-record commits are the transaction boundary.

New `NewType`s in `ra2/domain/ids.py`: `PromptTemplateId`, `RunId`,
`ExtractionId`. (`EvaluationId` has existed since M0.)

### 3.1 Three new protocols and three component signatures, declared at Wave 0

Same reasoning as `CensusMaterialiser` (plan-m0-m5.md E6) and
`EnumCodeTableProvider` (plan-phase-2.md §3): declared once up front so the two
sides get built by different agents at the same time, and neither waits.

```python
# ra2/domain/llm.py (amendment) — beside the existing LLMClient
@dataclass(frozen=True, slots=True)
class ModelInfo:
    tag: str
    digest: str
    size_bytes: int

class ModelCatalog(Protocol):
    """What the endpoint has, and whether it is there at all.
    H4 implements (infra/ollama_client.py); I2 calls it."""
    async def models(self) -> tuple[ModelInfo, ...]: ...
    async def reachable(self) -> EndpointStatus: ...

# ra2/infra/gpu.py (new)
class GpuProbe(Protocol):
    """None = no NVIDIA GPU, or NVML not present. Not an error (Q3)."""
    def describe(self) -> GpuInfo | None: ...

# ra2/services/protocols.py (amendment)
class PromptResolver(Protocol):
    """The run worker needs the resolved prompt per record without
    run_service importing prompt_service. I1 implements, I3 calls."""
    async def resolve(
        self, session: AsyncSession, evaluation_id: EvaluationId, record_id: RecordId
    ) -> ResolvedPrompt: ...

# ra2/ui/components/ (new files, signatures only at Wave 0)
def progress_card(*, progress: RunProgressView) -> Element: ...
def ollama_settings_dialog(*, settings: ConnectionView, on_save: ..., on_refresh: ...) -> Element: ...
def prompt_preview_panel(*, resolved: ResolvedPromptView) -> Element: ...
```

The three component signatures are what let L2 (the Evaluation view) and L3
(these components) build in parallel in Wave 4 — the trick
`plan-phase-2.md` used for `derivation_builder` / `feature_sets_table`.

---

## 4. The parallelisation model

Same four ideas as `plan-m0-m5.md` §1: one serial contract freeze, disjoint
file ownership, isolated worktrees, tests as the handshake. Read that section
if this is the first phase you're executing. As in phase 2, **Wave 0 may edit
any file `CONTRACTS.md` currently lists**, including ones M0 and M9 froze;
after it re-tags, those files are frozen again for Waves 1–4.

**Agent letters skip `J`.** Phase 1 used A/B/C, phase 2 D/E/F/G, and `J` is
the E2E journey prefix (J1–J10). Phase 3 uses **H, I, K, L**.

| Wave | Base | Agents | Milestones | Parallel? |
|---|---|---|---|---|
| **0** | tag `phase2-done` (= current `main`) | 1 (lead or `p3-foundation`) | M17 | no |
| **1** | tag `p3-frozen` | 5 (H1–H5) | M18, M19, M20, M21 | yes |
| **2** | tag `p3w1-green` | 3 (I1–I3) | M22 | yes |
| **3** | tag `p3w2-green` | 2 (K1–K2) | M23 | yes |
| **4** | tag `p3w3-green` | 3 (L1–L3) | M24, M25 | yes |
| **after 4** | tag `p3w4-green` | lead, on the target machine (§10.4) | M26 | n/a |

Fourteen agent runs (including Wave 0), five integration points, and one
closing step no agent can run. This is the largest phase; Q1 is why.

---

## 5. Wave 0 — contract freeze

One agent, serial. Reads `mvp-spec.md` §5/§9/§10, **`sw-design.md` §15 in
full** (§0 — it is the architecture this wave transcribes into code), and
`design/prompt-evaluation/README.md` before writing anything.

### 5.1 Deliverables

- **§2.4's document corrections** — `mvp-spec.md`, `CLAUDE.md`, `CONTRACTS.md`,
  `pyproject.toml`, `.importlinter`. `sw-design.md` §15 and `SD11`–`SD15` are
  already in place (§0); this wave amends them only if it changes something
  they describe.
- **`ra2/domain/ids.py`** — `PromptTemplateId`, `RunId`, `ExtractionId`.
- **`ra2/domain/prompt.py`** *(new, frozen after this wave)* — `Slot`,
  `SLOTS` (the closed catalogue: `feature_block` and `narrative` required,
  `language` optional — C1), `PromptTemplateDraft`, `ResolvedPrompt`,
  `PromptValidationError` payload types, and the **signatures** of
  `validate_template`, `render_feature_block`, `resolve_template`,
  `estimate_tokens`, `compute_template_fingerprint`. Bodies are H1's.
- **`ra2/domain/extraction.py`** *(new, frozen after this wave)* — the
  `mvp-spec.md` §10.3 shapes (`FeatureAnswer`, `EntityAnswer`,
  `ExtractionOutput`), and the **signatures** of `build_output_schema` and
  `parse_output`. Bodies are H2's.
- **`ra2/domain/llm.py` (amendment)** — `ModelInfo`, `EndpointStatus`,
  `ModelCatalog` (§3.1). The existing `LLMClient` protocol is **unchanged**:
  `extract(text, schema, model, *, temperature, seed)` is exactly adequate —
  `text` takes the resolved prompt, and the timeout belongs to client
  construction, not to a per-call argument. Confirming that is part of this
  wave's job; if it turns out to be wrong, it is an amendment, not a quiet
  signature change.
- **`ra2/infra/gpu.py`** *(new)* — `GpuInfo`, the `GpuProbe` protocol, and
  `StaticGpuProbe` (config override + the tests' substitute). `NvmlGpuProbe`
  is a stub here; H4 fills it in.
- **`ra2/persistence/models.py` (amendment)** — `PromptTemplate`,
  `EvaluationFeature`, `Run`, `Extraction`, `ExtractionValue`,
  `ExtractionEntity`; the new `Evaluation` columns (§3).
- **`ra2/services/protocols.py` (amendment)** — `PromptResolver` (§3.1).
- **`ra2/services/container.py` (amendment)** — `prompt: PromptService`,
  `evaluation: EvaluationService`, `run: RunService`.
- **`ra2/services/errors.py` (amendment)** — `PromptValidationError`,
  `PromptTemplateCitedError` (delete or in-place edit of a cited version),
  `EvaluationLockedError` (edit after launch), `LlmEndpointError` (unreachable,
  or a non-loopback endpoint refused). **No new `FindingCode`s** — a parse
  failure is a recorded outcome on the `extraction` row, counted and visible
  (`mvp-spec.md` §10.4), which is how `Do-NOT #6` is satisfied without inventing a report
  vocabulary for a table that already stores the evidence. Phase 2 set this
  precedent with `CodelistImportError`.
- **`ra2/services/readmodels.py` (amendment)** — `PromptTemplateView`,
  `SlotView`, `ResolvedPromptView`, `EvaluationView`, `EvaluationDraftView`,
  `ModelChoiceView` (tag, digest, size, `fits_vram`, `selected`),
  `ConnectionView`, `RunProgressView`, `RunView`, `ProvenanceView`.
- **`ra2/infra/config.py` (amendment)** — `RA2_LLM_TIMEOUT_S` (120),
  `RA2_LLM_MAX_RETRIES` (2 — bounded and counted, `mvp-spec.md` §10.4),
  `RA2_RUN_CONCURRENCY` (1, §2.3), `RA2_GPU_VRAM_GB` / `RA2_GPU_NAME`
  (overrides, default unset → probe). `llm_base_url`'s default becomes
  `http://127.0.0.1:11434/v1` — the design's endpoint line, and one fewer
  name to resolve in the loopback guard.
- **`ra2/api/schemas.py` (amendment)** and **`ra2/api/v1/router.py`
  (amendment)** — request/response models and the new routers.
- **`ra2/api/deps.py` (amendment)** — `PromptServiceDep`,
  `EvaluationServiceDep`, `RunServiceDep`.
- **`ra2/main.py` (amendment)** — construct the three services, the
  `OllamaLLMClient`, the `ModelCatalog` and the `GpuProbe`, each as a
  **defaulted keyword argument** so tests substitute without a test-mode
  branch (`Do-NOT #12`).
- **`ra2/ui/shell.py` (amendment)** — the eighth `NavItem`: key `prompts`,
  group `Configure`, path `/prompts`, after `features`, `built=False`.
  **`ra2/ui/components/icons.py` (amendment)** — `ALIGN_LEFT`
  (`M4 5h16 · M4 10h10 · M4 15h13 · M4 20h7`, the README's exact paths) wired
  into `NAV_ICONS`.
- **New stubs** — `ra2/services/{prompt,evaluation,run}_service.py`,
  `ra2/api/v1/{prompt_templates,evaluations,runs,models}.py`,
  `ra2/infra/ollama_client.py`, `ra2/ui/views/{prompts,evaluation}_view.py`,
  `ra2/ui/components/{progress_card,ollama_settings,prompt_preview}.py`:
  constructors and typed signatures, bodies `raise NotImplementedError`.
- **One migration** — an empty revision wired into the chain, so H3's Wave 1
  work is "fill this in", not "create the first phase-3 revision from nothing".
- **`CONTRACTS.md`** and **`CLAUDE.md`** amendments per §2.4.
- **`tests/test_p3_contract.py`** *(new, lead-owned)* — this wave's exit
  criteria as tests, in the shape of the existing `test_m0_contract.py` and
  `test_p2_contract.py`: every file §5.1 freezes carries its `# FROZEN`
  header, is listed in `CONTRACTS.md`, and imports cleanly. A Wave 1+ agent
  should never need to touch it; a failure there means a frozen contract was
  edited without an amendment.

### 5.2 Exit criteria

- `just lint && just test` green with the new stubs raising
  `NotImplementedError`; every phase-1 and phase-2 test still green — this
  wave adds surface, it does not change behaviour.
- `alembic upgrade head` runs the new empty migration cleanly, on a fresh DB
  **and** on one already at `phase2-done`.
- The new nav entry renders and routes to `placeholder_view`; **J4, J5 and J6
  are green with eight items, not seven** (all three parametrise over
  `NAV_ITEMS`, so this is where the nav change is proven, not in Wave 4).
- `CONTRACTS.md` lists every file this wave touched; each carries
  `# FROZEN — see CONTRACTS.md` where the convention applies.
- `tests/test_p3_contract.py` green — the exit criteria above as tests, not as
  a checklist someone reads.
- `import-linter` green with the amended `one-llm-seam` contract — including
  the stub `ollama_client.py`, which is the first module in the repo allowed
  to import `openai`.

### 5.3 Review gate

The lead reads **line by line** before tagging `p3-frozen`: `sw-design.md`
§15, `models.py`'s diff, `domain/prompt.py`, `domain/extraction.py`, the
`llm.py` amendment, and `config.py`'s new settings. Two things get a second
look specifically:

1. **`evaluation_feature`** — the one table in this wave whose existence is a
   consequence of a phase-2 decision rather than a spec line (§3). If it is
   wrong, every fingerprint in the phase is wrong.
2. **The loopback guard and the `pyproject`/`.importlinter` amendments
   together** — this is the commit where the codebase gains the ability to
   make an outbound request at all. It should be reviewed as that, not as
   two dependency lines.

---

## 6. File ownership matrix

| Path | W0 | W1 | W2 | W3 | W4 |
|---|---|---|---|---|---|
| `sw-design.md` `mvp-spec.md` `CONTRACTS.md` `CLAUDE.md` | M17 | 🔒 | 🔒 | 🔒 | 🔒 |
| `tests/test_p3_contract.py` `tests/conftest.py` | M17 | 🔒 | 🔒 | 🔒 | 🔒 |
| `pyproject.toml` `.importlinter` | M17 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/domain/{ids,prompt,extraction,llm}.py` | M17 | 🔒 *(bodies open)* | 🔒 | 🔒 | 🔒 |
| `ra2/persistence/models.py` | M17 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/services/{protocols,container,errors,readmodels}.py` | M17 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/api/{schemas,deps,v1/router}.py` `ra2/main.py` | M17 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/ui/shell.py` `ra2/ui/components/icons.py` | M17 | 🔒 | 🔒 | 🔒 | 🔒 *(the two-line exception, §6.1)* |
| `ra2/domain/prompt.py` *(bodies)* | M17 stub | **H1** | 🔒 | 🔒 | 🔒 |
| `ra2/domain/extraction.py` *(bodies)* | M17 stub | **H2** | 🔒 | 🔒 | 🔒 |
| `ra2/persistence/repositories/{prompt,evaluation,run,extraction}_repo.py`, `migrations/versions/**` | M17 stub | **H3** | 🔒 | 🔒 | 🔒 |
| `ra2/infra/ollama_client.py`, `ra2/infra/gpu.py` *(`NvmlGpuProbe`)* | M17 stub | **H4** | 🔒 | 🔒 | 🔒 |
| `ra2/ui/components/primitives.py` *(additions)* | — | **H5** | 🔒 | 🔒 | 🔒 |
| `ra2/services/prompt_service.py` | M17 stub | 🔒 | **I1** | 🔒 | 🔒 |
| `ra2/services/evaluation_service.py` | M17 stub | 🔒 | **I2** | 🔒 | 🔒 |
| `ra2/services/run_service.py` | M17 stub | 🔒 | **I3** | 🔒 | 🔒 |
| `ra2/api/v1/prompt_templates.py` | M17 stub | 🔒 | 🔒 | **K1** | 🔒 |
| `ra2/api/v1/{evaluations,runs,models}.py` | M17 stub | 🔒 | 🔒 | **K2** | 🔒 |
| `ra2/ui/views/prompts_view.py` | M17 stub | 🔒 | 🔒 | 🔒 | **L1** |
| `ra2/ui/views/evaluation_view.py`, `ui/state.py` *(additions)* | M17 stub | 🔒 | 🔒 | 🔒 | **L2** |
| `ra2/ui/components/{progress_card,ollama_settings,prompt_preview}.py` *(bodies)* | M17 stub | 🔒 | 🔒 | 🔒 | **L3** |
| `tests/unit/prompt/**` | — | **H1** | | | |
| `tests/unit/extraction/**` | — | **H2** | | | |
| `tests/backend/persistence/test_{prompt,evaluation,run,extraction}_repo.py`, migration tests | — | **H3** | | | |
| `tests/backend/infra/test_ollama_client.py`, `test_gpu_probe.py`, `tests/fixtures/fake_llm.py` | — | **H4** | | | |
| `tests/ui/test_components.py` *(additions)* | — | **H5** | | | |
| `tests/backend/services/prompt/**` | — | | **I1** | | |
| `tests/backend/services/evaluation/**` | — | | **I2** | | |
| `tests/backend/services/run/**` | — | | **I3** | | |
| `tests/backend/api/prompt_templates/**` | — | | | **K1** | |
| `tests/backend/api/{evaluations,runs,models}/**` | — | | | **K2** | |
| `tests/ui/test_prompts_view.py`, `tests/e2e/test_j9_prompts.py` | — | | | | **L1** |
| `tests/ui/test_evaluation_view.py`, `tests/e2e/test_j10_evaluation.py` | — | | | | **L2** |
| `tests/eval/**`, `evals/baseline.json` | — | | | | lead, after the wave (§10.4) |

🔒 = frozen for that wave; amendment only. Per-layer conftests follow phase
1's rule: owned by whoever owns that layer in that wave; only
`tests/conftest.py` stays lead-owned, and is one of the files Wave 0 may
extend — a `fake_llm` / `static_gpu` root fixture pair almost certainly earns
its place there, since three later waves need it.

### 6.1 The two-line nav exception

`ra2/ui/shell.py` carries a `built` flag per `NavItem`, and
`ra2/ui/views/__init__.py` carries one `register()` call per built view. Both
Wave 4 view agents need their own flag flipped and their own line added, or
their E2E journey cannot reach the page in their own worktree.

**In phase 2 this was left implicit and the lead had to fix it up afterwards**
(commit `e386a66`, "Wire Codelists/Features into the shell"). So it is
declared here instead: **L1 and L2 may each edit exactly their own `built`
flag and add exactly their own line to `register_all`.** Nothing else in
either file. The merge conflict is one line in a known place, and the lead
resolves it at integration. L3 touches neither file.

---

## 7. Wave 1 — domain, persistence, adapters, component kit

Base tag `p3-frozen`. Five agents, isolated worktrees.

### H1 — `feat/p3-prompt-domain` · prompt template domain *(M, sonnet)*

**Build:** `domain/prompt.py` bodies.
- `validate_template(source) -> list[PromptValidationError]` — the closed slot
  set (C1): an unknown `{{slot}}` is an error, a missing `{{feature_block}}`
  or `{{narrative}}` is an error, a duplicated slot is not. Malformed
  half-braces (`{{narrative}`) are errors, not silently ignored text.
- `render_feature_block(features, codelists, language) -> str` — `name — type`
  lines plus the **full code → label list** per enum feature (`mvp-spec.md`
  §10.2), the
  expert's description verbatim per exploratory attribute.
- `resolve_template(source, blocks) -> ResolvedPrompt` — pure substitution.
- `estimate_tokens(text) -> int` (C6) and
  `compute_template_fingerprint(source) -> str` — sha256 over the exact
  source bytes, reusing `domain/fingerprint.py`'s canonicalisation so two
  fingerprint functions cannot drift apart.

**Fixtures** (`tests/fixtures/prompts/`, the h01–h12 / c01–c05 hazard
philosophy — synthetic, small, committed):
`p01` valid with all three slots · `p02` missing `{{narrative}}` ·
`p03` unknown `{{corpus}}` · `p04` `{{feature_block}}` twice (valid) ·
`p05` half-brace `{{narrative}` · `p06` a feature block where one enum's
codelist has a code with **no label in the requested language** (the phase-2
`partial` case seen from the prompt's side — the label must fall back
visibly, never render empty) · `p07` a narrative containing `{{` literally
(substitution must not recurse into record text).

**Exit:** one named test per hazard asserting the exact outcome; `p07` proves
resolution is single-pass; the fingerprint is tested for stability and for
sensitivity to a single whitespace change (a template's whitespace is part of
the prompt); `render_feature_block` is asserted against a golden string, not
a substring match.

### H2 — `feat/p3-extraction-domain` · output schema and parsing *(M, sonnet)*

**Build:** `domain/extraction.py` bodies.
- `build_output_schema(features) -> type[BaseModel]` — `pydantic.create_model`
  producing `mvp-spec.md` §10.3's shape for *this* feature set: one key per feature key,
  each `{value, present, evidence}`, plus `entities`. This is what becomes a
  JSON Schema for constrained decoding, so its **key order is stable** across
  calls (two runs must ask the same question).
- `parse_output(raw, features) -> ParsedExtraction | ParseFailure` — never
  raises, never repairs. A missing feature key, an extra key, a non-null
  value with a null evidence span, an enum value outside the snapshotted
  codelist: each is a recorded, typed outcome. Normalisation (`value_raw` →
  `value_normalised`) is exact-and-trimmed only (`D6`: no fuzzy matching).

**Exit:** a golden JSON Schema snapshot per feature-kind combination (the
snapshot diff is part of the PR, not a silent regeneration); parse tests for
valid output, truncated JSON, JSON-with-prose-around-it, an extra key, a
missing key, `null` value with a non-null evidence span, an enum code not in
the codelist; a property test that `parse_output` never raises on arbitrary
bytes.

### H3 — `feat/p3-persistence` · migration and repositories *(L, sonnet)*

**One migration author, one per phase — H3 for phase 3** (`CLAUDE.md`, as
amended at Wave 0). Nobody else runs `alembic revision`.

**Build:** the **single** phase-3 migration — `prompt_template`,
`evaluation_feature`, `run`, `extraction`, `extraction_value`,
`extraction_entity`, plus the new `evaluation` columns, plus
`UNIQUE (run_id, record_id)` on `extraction` and `UNIQUE (version)` on
`prompt_template`. Repositories: `prompt_repo` (versions, citation counts,
the active flag), `evaluation_repo` (drafts, launch, the
`evaluation_feature` snapshot), `run_repo` (create, status transitions,
progress counts), `extraction_repo` (the per-record write, and the
**resume query**: record ids in the run's scope with no `extraction` row).

**Exit:** `alembic upgrade head` clean on a fresh DB **and** on a DB at
`phase2-done` — this migration must apply to a real phase-2 database, not
just to fresh ones; `alembic check` clean; a round-trip test per repository;
the resume query tested against a run with a deliberate hole in the middle of
its record range (not just a truncated tail — a retry that failed and was
skipped leaves a hole, and resume must find it); the `UNIQUE (run_id,
record_id)` constraint asserted to raise on a double write rather than
silently updating (`Do-NOT #2`).

### H4 — `feat/p3-llm-adapter` · the one `openai` import, and the GPU probe *(L, opus)*

**Build:** `infra/ollama_client.py` — `OllamaLLMClient` implementing
`LLMClient`, `OllamaModelCatalog` implementing `ModelCatalog`. Pydantic model
→ JSON Schema → the endpoint's constrained decoding, through the `openai`
SDK at `/v1` (§15 F3). **The loopback guard:** the client refuses, at
construction, a `base_url` whose host is not loopback — `LlmEndpointError`,
with the reason naming N1. Retries bounded by `RA2_LLM_MAX_RETRIES` and
**counted into the returned `Extraction`**, never silent (`mvp-spec.md`
§10.4). Latency and
token counts populated from the response.
`infra/gpu.py` — `NvmlGpuProbe` via `nvidia-ml-py`'s `ctypes` load: GPU name
and total VRAM, `None` when NVML is absent, **no subprocess ever** (Q3, R2).
`tests/fixtures/fake_llm.py` — the `FakeLLMClient` / `StaticModelCatalog` every
later wave and both E2E journeys build the app with, beside the existing
`tests/fixtures/factories.py` stubs (that is where this repo's test doubles
live; there is no `tests/fakes/`).

**Exit:** the client tested against a **local `respx`/ASGI stub of the
endpoint**, never a live Ollama — the suite must pass on a machine with no
GPU and nothing on port 11434; the loopback guard tested for `localhost`,
`127.0.0.1`, `::1` (accepted) and a LAN address and a public host name
(refused); a retry test asserting the count reaches the `Extraction` and the
bound is respected; `NvmlGpuProbe` tested with NVML stubbed present and
absent; `grep`-level proof that `openai` appears in exactly one module, which
`import-linter` already enforces and this test documents.

### H5 — `feat/p3-components` · shared component kit additions *(S, sonnet)*

**Build:** the primitives both views need and `primitives.py` lacks, per the
design's utility-class list: a **label-above-field** pair (step 5's
Temperature/Seed, explicitly drawn that way "so input and label can't be
confused"), a **radio-style `.sel` option** (step 6's `●`/`○` full/dev
choice), a **scroll well** with a fixed row-count cap (the models card's
196px = 4 rows, the version list's 530px = 10 × 53px), a **slot-highlighting
mono block** (`white-space:pre-wrap` with `{{slot}}` tokens on
`--accent-soft`), and the **numbered step label** (`N · Title`). Extend,
don't replace: `card`, `card_header`, `tick`, `bar`, `pill`,
`pagination_row`, `field_select`, `master_detail_split`, `footnote` all exist
and both views reuse them as-is.

**Exit:** `tests/ui/test_components.py` gains one case per new primitive; the
scroll well's cap is asserted in pixels against the design's numbers; a
resize test asserts both new splits never wrap down to 1024px and that the
setup/progress floor widths are the design's 320px/360px (mirrors J4 and
phase 2's D4).

---

## 8. Wave 2 — services

Base tag `p3w1-green`. Three agents. This is the wave `PromptResolver` (§3.1)
exists for.

### I1 — `feat/p3-prompt-service` *(M, sonnet)*

**Build:** `prompt_service.py` — `list_versions` (with citation counts and
the `deletable` flag), `save_as_next_version` (**copy-on-write**: validate via
H1, write a new row, never touch an existing one), `activate`, `delete`
(refused with `PromptTemplateCitedError` when any run cites it),
`resolve(evaluation_id, record_id)` implementing `PromptResolver` for I3, and
`preview(template_id, feature_config_id, record_id)` for the views (C4) —
both no-model-call paths.

**Exit:** saving over a cited version creates a new row and leaves the old
`source` **byte-identical** (asserted on bytes, not on equality of a parsed
form); deleting a cited version raises and deletes nothing; exactly one row
is active at a time, asserted after an activate-twice sequence; a template
failing validation writes nothing; `resolve` against a dev-sized evaluation
and against a full one produce the same text for the same record.

### I2 — `feat/p3-evaluation-service` *(L, opus)*

**Build:** `evaluation_service.py` — `save_draft` / `update_draft` (editable
while `launched_at IS NULL`), `list_models` (H4's `ModelCatalog` + the
`GpuProbe`'s VRAM → `fits_vram` per model; unreachable endpoint → an empty
list and a reason, never an exception into the UI), `connection_status`,
and **`launch`**: in one transaction, pin corpus + frozen `feature_config` +
`prompt_template` + `prompt_language` + temperature + seed + size, write the
`evaluation_feature` snapshot (`enum_codelist_json` from the corpus's current
`column_mapping`, plus each feature's final fingerprint via
`domain/fingerprint.py`), mark `is_dev` from the size choice against
`RA2_EVAL_RECORD_MIN` / `RA2_DEV_RECORD_MAX`, and create one `queued` `run`
per selected model. Editing after launch raises `EvaluationLockedError`.

The **dev sample is deterministic**: the first `RA2_DEV_RECORD_MAX` records
by id. A dev re-run is a check, not a new sample — the same property the
seed gives the model, applied to the record selection. The design's "Dev · 40
records" label reads its number from config.

**Exit:** launching an evaluation whose `feature_config` is not frozen is
refused (nothing created); the snapshot is proven independent of later
`column_mapping` edits (re-point a mapping after launch, assert the stored
`enum_codelist_json` is unchanged — this is `mvp-spec.md` §19.3 and §19.8
seen from the evaluation's side); a feature's `evaluation_feature.fingerprint`
differs from its draft **preview** fingerprint exactly when the codelist
snapshot differs (phase 2 Q3's promise, now testable); a VRAM-infeasible
model cannot be selected; an unreachable endpoint yields a reason, not a
traceback.

### I3 — `feat/p3-run-service` · the worker *(L, opus)*

**Build:** `run_service.py` — `launch_runs(evaluation_id)` submitting one
`TaskRunner` job per `run`, executed **serially** (§2.3); per record: resolve
the prompt through `PromptResolver` (never importing `prompt_service`), call
`LLMClient.extract`, parse through H2, and commit **one `extraction` +
its `extraction_value`/`extraction_entity` children per record** — the
transaction boundary that makes resume correct. Progress reported through
`ProgressReporter` and derived from committed rows (§3). `resume(run_id)`
picks up from H3's resume query. Terminal states: `done`, `failed`,
`interrupted` (the restart case, §2.3). Provenance written at run start:
model + digest, template version + fingerprint, temperature, seed, corpus
version, host platform, GPU name, endpoint (P30).

**Exit:** the headline test — **kill the run mid-corpus and resume it**:
build the app, run with a fake client that raises after N records, rebuild
the app from the same database, resume, and assert every record has exactly
one extraction and no record was extracted twice (`mvp-spec.md` §19.5,
N5, N6); a parse failure is stored with `parse_ok=False` and its raw output
verbatim, and the run **continues** (a failure is a datum, not a stop); the
retry count and parse-failure count reaching the progress view match the
rows; a run over a dev-sized selection is marked `dev`; two runs of the same
evaluation with the same seed produce identical stored values for the same
record, given the same fake client.

---

## 9. Wave 3 — API v1

Base tag `p3w2-green`. Two agents; thin routers, no ORM object crosses the
boundary — the same rule as phase 1's C1/C2 and phase 2's F1/F2.

- **K1 — `feat/p3-api-prompts`**: `/api/v1/prompt-templates/*` — list, get,
  `POST` a new version (copy-on-write; **never** a `PATCH` on a cited one),
  activate, delete, and `POST /resolve` for the preview. *Exit:* every
  endpoint tested through `httpx.ASGITransport`; an invalid template returns
  **422 with the typed validation errors**, not a 500; deleting a cited
  version returns 409; a `PATCH` route does not exist (asserted — the absence
  is the contract).
- **K2 — `feat/p3-api-evaluations`**: `/api/v1/evaluations/*` (list, save
  draft, update draft, launch), `/api/v1/runs/*` (list per evaluation, get
  one with progress and provenance, resume), `/api/v1/models` (catalogue +
  reachability). *Exit:* launching with an unfrozen config returns 422 and
  creates nothing; editing a launched evaluation returns 409; an unreachable
  endpoint returns **200 with `reachable: false`**, not a 502 — the UI renders
  a reason next to the endpoint line (C3), and an error status would make that
  a toast; OpenAPI snapshot regenerated with the diff in the PR.

---

## 10. Wave 4 — the two views

Base tag `p3w3-green`. Three agents. L2 and L3 both touch the Evaluation
screen but own disjoint files, made possible by the component signatures Wave
0 declared (§3.1). The two-line nav exception is §6.1.

### L1 — `feat/p3-prompts-view` *(L, opus)*

**Build:** `ui/views/prompts_view.py` to the README's §1 — the right-only
toolbar ("Preview with record 1", "Save as vN"), the version list (the four
row markers: ACTIVE pill, `locked`, a `--danger` delete button on an uncited
version, plus the selected-row treatment), the 10-row/530px well with its
pagination row, the two reference strips ("Slots available" + the slot
table), and the editor: the fingerprint block, the Source card with inline
slot highlighting and the `--warn-soft` copy-on-write footer, and the
Resolved card capped at 210px. State via `app.storage.client` (selected
version, page) — no module globals (`Do-NOT #8`).

**Exit:** `tests/ui/test_prompts_view.py` covers all four row markers, the
save-as-next-version flow, a validation error rendering against H1's `p02`
and `p03` fixtures, and the slot-highlighting of the Source body;
`tests/e2e/test_j9_prompts.py` (**J9**, new): seed templates through the API,
edit the active version, save as the next one, and assert the old version is
still present, still byte-identical, and now shows `locked`.

### L2 — `feat/p3-evaluation-view` *(L, opus)*

**Build:** `ui/views/evaluation_view.py` to the README's §2 — the toolbar
(the pinned-inputs line, "Save draft"), the six numbered setup steps with
their exact notes (step 2's note per **C5**, not the design's stale wording),
the models card with its 4-row well, VRAM-disabled rows, footer count and
gear button, the endpoint/reachability line, the launch row whose label
counts selected models, and the progress column: the per-model progress
cards, the runs table (the five columns at their exact widths, the
`dev`/`failed` row states, `dd.mm.yy - hh:mm:ss` timestamps, 10-row
pagination, run id linking to Results — a placeholder route in this phase,
which is honest rather than hidden), and the reproducibility card. Progress
polls `GET /api/v1/tasks/{id}` with `ui.timer`, the import view's pattern.
The `align-self:flex-start` setup column and the never-wrapping split are
both called out in the README as past regressions — assert them.

**Exit:** `tests/ui/test_evaluation_view.py` covers all six steps, the
VRAM-disabled row, the unreachable-endpoint state disabling Launch (C3), the
launch-label count following the selection, the three run row states, and the
`interrupted` run's Resume action; `tests/e2e/test_j10_evaluation.py`
(**J10**, new): seed a corpus, a frozen feature set and a template through the
API; build the app with H4's `FakeLLMClient` and `StaticGpuProbe`; select two
models; launch; poll to completion; assert two runs `done`, the runs table
rows, the dev marker on a dev-sized run, and that the reproducibility card
names every field `mvp-spec.md` §19.8 requires.

### L3 — `feat/p3-evaluation-components` *(M, sonnet)*

**Build:** `ui/components/progress_card.py` (the per-model card: tag, status
line, `.bar`, the metrics line, and the `queued` variant with no metrics),
`ollama_settings.py` (Q4's minimal dialog — endpoint, timeout, "refresh model
list" — on the existing `dialog_card` pattern, with the phase-2 dialog
clipping fix respected), and `prompt_preview.py` (C4's shared preview panel,
used by both views).

**Exit:** the progress card renders all four states (`queued`, `running`,
`done`, `failed`) from `RunProgressView` alone, with no service call inside
the component (`Do-NOT #7`); the settings dialog's save emits its three
values and touches no global; the preview panel renders identically from both
entry points, asserted against one golden string; the dialog opens without
clipping at 1024px.

### 10.4 After Wave 4 — the eval layer and the acceptance run *(lead, on the target machine)*

`sw-design.md` §11.6 puts `tests/eval/` behind `@pytest.mark.eval`, "against
real Ollama, gated on `evals/baseline.json`", and `CLAUDE.md`'s test-layer
table assigns it to phase 3. It is the one layer **no sub-agent can run** —
there is no GPU and nothing listening on 11434 in a worktree — so it is not an
agent's deliverable. The lead does it on the target machine after
`p3w4-green`, as the phase's closing step:

- A first eval case: resolve the active template against a real feature set
  and a sample of real records, call a real model, and assert **adherence** —
  every response parses, every non-null value carries an evidence span, every
  enum value is in the snapshotted codelist. Adherence, not accuracy: accuracy
  is scoring, and scoring is phase 4.
- `evals/baseline.json` seeded from that first run, so the next change to a
  prompt or a model is measured against something.
- Excluded from `just test` and from CI (`-m "not eval"`), because a gate that
  needs a GPU is a gate that fails on every machine that does not have one.
- The same session covers `mvp-spec.md` §19.5 — ≥200 records across ≥2 models,
  visible progress, and a deliberate restart mid-run. That is the acceptance
  criterion this phase exists to meet, and it can only be met here.

---

## 11. Testing — cross-cutting summary

Every agent above owns its own test paths (§6); this is the "does it all still
add up" view over the gates `mvp-spec.md` §15 / `sw-design.md` §11 already
establish.

| Layer | New in this phase |
|---|---|
| **Unit** | `domain/prompt.py` (H1), `domain/extraction.py` (H2) — pure, no I/O, no network |
| **Backend** | repositories + the migration from a phase-2-shaped DB (H3), the LLM adapter and GPU probe against local stubs (H4), three services (I1–I3), four routers (K1, K2) |
| **Frontend** | `test_components.py` additions (H5), `test_prompts_view.py` (L1), `test_evaluation_view.py` (L2) — NiceGUI `User` fixture, unchanged |
| **E2E** | **J9** (Prompts: edit → save as next → old version locked and byte-identical, L1) and **J10** (Evaluation: launch → progress → runs table → provenance, L2) join J1–J8. J4/J5/J6 gain an eighth nav item at **Wave 0**, not Wave 4 (§5.2). |
| **Fixtures** | `tests/fixtures/prompts/` (`p01`–`p07`, H1); `tests/fixtures/fake_llm.py` (H4) — the fake client and static catalogue every later wave builds the app with |
| **Eval** | Layer 5 comes alive (P36, §10.4) — `@pytest.mark.eval`, a real model, adherence only, excluded from `just test` and from CI |

**No live endpoint in layers 1–4.** Everything inside `just test` and
`just e2e` must pass on a machine with no GPU and nothing listening on 11434:
H4's adapter tests run against a local stub, everything above them runs
against `tests/fixtures/fake_llm.py`. The one place a real model is allowed is
layer 5, which already has a marker for exactly this (`@pytest.mark.eval`) and
sits outside both gates — so no second "live" marker gets invented.

**J6 stays exactly as strict.** It watches the *browser*, and the browser
still talks only to the server under test — the new outbound call is
server-side. What changes is the rule it sits under: `CLAUDE.md`'s "no egress
at all in phase 1" becomes "no egress except the configured LLM endpoint,
which must be loopback" (§2.4), and H4's loopback-guard tests are what make
*that* enforceable rather than aspirational. `mvp-spec.md` §19.10 has said so
from the start.

No change to the five gates in `sw-design.md` §11.7. Coverage stays scoped to
`ra2/domain` + `ra2/services` at `fail_under = 85`, which now includes the run
worker — I3's resume test is the one that carries it.

---

## 12. Integration protocol

Identical to `plan-m0-m5.md` §8 and `plan-phase-2.md` §12: per branch, in
dependency order, check `git diff --name-only <base>..<branch>` against §6,
apply or defer any `contracts/amendments/<branch>.md`, merge, run
`just lint && just test` **on the merged tree**, resolve or name-as-follow-up
any `xfail`. After the last branch of a wave: `just e2e`, tag, spawn the next
wave.

Dependency order per wave (leaf-most first):

- **Wave 1** — H5 (nothing depends on it), then H1, H2, H4, H3 last (its
  migration is the file most likely to need a rebase, and it is the cheapest
  one to rewrite).
- **Wave 2** — I1 (implements `PromptResolver`), then I2, then I3 (calls
  both seams).
- **Wave 3** — K1, then K2.
- **Wave 4** — L3 (the components), then L1, then L2 (it imports L3's
  components and shares §6.1's two-line conflict with L1).

Manual verification of any merged tree runs **`just dev-agent`, never bare
`just dev`** (`CLAUDE.md`) — and in this phase that matters more than in
either previous one: `just dev` points at the developer's real `./var`
database, and this is the first phase whose code writes extraction rows and
opens a socket.

---

## 13. Milestone coverage

| Milestone | Delivered by | Exit criteria met at |
|---|---|---|
| M17 Contract freeze (§15 already written, §0) | Wave 0 lead | tag `p3-frozen` |
| M18 Prompt + extraction domain | H1 + H2 | tag `p3w1-green` |
| M19 Persistence | H3 | tag `p3w1-green` |
| M20 LLM adapter + GPU probe | H4 | tag `p3w1-green` |
| M21 Component kit additions | H5 | tag `p3w1-green` |
| M22 Services (prompt, evaluation, run worker) | I1 + I2 + I3 | tag `p3w2-green` |
| M23 API v1 | K1 + K2 | tag `p3w3-green` |
| M24 Prompts view | L1 | tag `p3w4-green` |
| M25 Evaluation view | L2 + L3 | tag `p3w4-green` |
| M26 Eval layer + the acceptance run | lead, on the target machine (§10.4) | tag `phase3-done` |

At `p3w4-green`, `mvp-spec.md` §19's acceptance criteria **8** (every run
reproducible from its own record) and **9** (dev-sized runs visibly marked)
are met, and criterion **5** is met in everything but its final proof — the
≥200-record run across ≥2 real models, surviving a restart, happens on the
target machine at M26 (§10.4), because that is the only place a real model
exists. Criteria 6 and 7 (Results, Mismatches) are phase 4.

---

## 14. Risks and flags

| # | Flag |
|---|---|
| R1 | **§15 and this plan must not drift.** §15 is written (§0), which removes the risk that started this phase — but Wave 0 touches almost every name §15 uses. A rename that lands in `models.py` and not in §15 puts five Wave-1 agents on a stale contract. The §5.3 gate reads both diffs together for that reason. |
| R2 | **Q3's GPU probe versus N3's "no shell-outs".** Resolved by using NVML's library bindings rather than `nvidia-smi`, but the resolution is only as good as its enforcement: an agent under time pressure reaches for `subprocess`. §15 must state the rule and H4's review must check for it. A machine with an AMD/Intel GPU or none gets "unknown" and a config override, which is honest but *is* a gap versus the design's drawn state. |
| R3 | **I3 is the single largest piece of work in the project so far** — a restart-safe worker with bounded retries, per-record transactions and live progress. It is sized `L`/opus and its exit criteria lead with the resume test for that reason. If it runs long, the cut is `resume` (leave runs `interrupted` with a manual Resume as §2.3 already says) *before* it is the per-record transaction boundary, which is not optional. |
| R4 | **The first outbound socket in the codebase.** Everything about N1 has so far been enforceable by having no network code at all. From this phase the guarantee rests on one guard in one constructor. That is why the guard is tested against five host forms, and why `import-linter` gained `pynvml`. |
| R5 | **`evaluation_feature` is a table this plan invents** (§3) as a consequence of a phase-2 decision. It is the right answer to "a frozen config is corpus-independent, so when does `enum_codelist_json` resolve?", but it is *our* answer, not the spec's. It gets the §5.3 line-by-line review, and if it is wrong the fingerprints are wrong. |
| R6 | **The design file is stale in one place** (C5: "Freezes when the first run executes"). An agent building L2 from the `.dc.html` alone will render copy that contradicts `mvp-spec.md` §9. Called out in L2's brief and worth repeating in the PR description. |
| R7 | **Three design open questions are settled by this plan, not by design** (C1, C2, C3/C4, plus Q4's dialog). Each is reversible and each is named here, so a later design round can overrule any of them cheaply — but nothing in phase 3 waits on one. |
| R8 | **The token count is an estimate** (C6) where the design shows an exact figure. Like `plan-phase-2.md` R4, call it out in the PR so a reviewer comparing against the `.dc.html` does not file it as a bug. |
| R9 | **Fourteen agent runs across five waves** is a third more than phase 2. The per-wave integration cost is the same, but Wave 1 has five branches touching `models.py`-adjacent code. H3 merging last (§12) is the mitigation. |

---

## 15. Decisions this plan makes

Numbered `F1…` following `plan-phase-2.md` §15, and always cited as
“§15 F*n*” — `mvp-spec.md` §1 uses `F1…F12` for capabilities, and the two
must not be read into each other.

| # | Decision | Why |
|---|---|---|
| **F1** | `prompt_template` is a **database table**, and `mvp-spec.md` §5/§10.2 are corrected to say so (Q2) | Copy-on-write, citation counts, an active flag and "delete only when uncited" are one foreign key in a table and four filesystem conventions on disk. The design's version list is a table shape; making it one puts the invariant where the database can enforce it. |
| **F2** | `evaluation_feature` holds the per-evaluation `enum_codelist_json` snapshot and the final fingerprint, rather than `feature` holding both as spec §5 writes | Phase 2 decided a frozen `feature_config` is corpus-independent and reusable across evaluations (`plan-phase-2.md` §15 F2). A codelist snapshot cannot resolve until a corpus — and therefore a `column_mapping` generation — is fixed, which happens at launch. The alternative (snapshot on `feature`) would silently make a frozen config single-corpus and contradict the phase it just came out of. |
| **F3** | The `openai` SDK **alone** in `infra/ollama_client.py`; **PydanticAI is dropped** from the stack | `mvp-spec.md` §3 names both, but the one call this product makes is "one prompt, one JSON Schema, one response". PydanticAI's value is an agent loop nobody here wants, and it would be a *second* place a provider client gets constructed — which is exactly what `Do-NOT #1` and the `one-llm-seam` contract exist to prevent. One library, one module, one lint rule. |
| **F4** | Egress policy becomes **loopback-only**, enforced in the client's constructor, rather than "no egress" being quietly dropped | `mvp-spec.md` §19.10 always said "no egress **beyond the configured LLM endpoint**", and N1 says no data leaves the host. A configurable base URL with no guard satisfies neither: a typo or a copied `.env` would ship accident narratives to a LAN address. There is deliberately **no opt-out setting** — an opt-out is how "no data leaves the host" becomes "no data leaves the host by default". |
| **F5** | VRAM comes from an **NVML library load** behind a `GpuProbe` protocol, with a config override and an honest "unknown" (Q3) | Q3 asked for a probe; N3 forbids shell-outs. `nvidia-ml-py` is a `ctypes` load of a library that is already present wherever the GPU is, works on both target platforms, and needs no subprocess. Behind a protocol it is also substitutable, which is what keeps the suite runnable on a laptop with no GPU. |
| **F6** | Progress is **derived from committed `extraction` rows**, never from a counter column | A counter is a second source of truth that a restart can desynchronise, and restart-safety (N6) is the one property this worker is judged on. `COUNT(*)` on an indexed `run_id` is cheap; being wrong about how much work is done is not. |
| **F7** | Runs execute **serially**, one model at a time (§2.3) | The GPU is the bottleneck; two models sharing 24 GB is slower than two in sequence, and it is what the design draws (one `running`, the rest `queued`). `RA2_RUN_CONCURRENCY` exists so the decision is a config line rather than a rewrite. |
| **F8** | An interrupted run stays `interrupted` with an explicit **Resume**; nothing auto-restarts at startup | N6 asks for restart-*safe* and resumable, not automatic. A run that resumes itself on every app start is a run that burns GPU hours on work the user may have abandoned — and `just dev-agent`'s whole existence is a reminder that an app can be started for reasons unrelated to the work in it. |
| **F9** | The dev sample is the **first N records by id**, N from `RA2_DEV_RECORD_MAX` | "A re-run is a check, not a new sample" (design, §2's purpose line) is false the moment the record selection is random. The seed fixes what the model does; determinism has to cover what it is *shown* too. |
| **F10** | The prompt language lives on the **evaluation** (C1) | It is the first persistent home for a value that two phase-2 views already select and nowhere stores, and it matches how the codelist snapshot resolves: both are per-evaluation, both for the same reason. It also turns `{{language}}` from a slot marked "unused" into a slot that resolves. |
| **F11** | Agent letters skip **`J`**; journeys keep it | Phase 2's letters ran D–G, and `J1`–`J8` are journeys. An agent called `J1` next to a test called `J1` is a half-hour of confusion in every integration report. |
| **F12** | The **two-line nav exception** is declared up front (§6.1) | Phase 2 left it implicit and paid for it with a lead fix-up commit after the wave. Two agents each need one flag flipped and one line added; saying so costs three sentences and saves a commit that looks like a bug fix. |
