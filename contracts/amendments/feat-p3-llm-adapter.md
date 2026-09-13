# Amendment — `feat/p3-llm-adapter` (H4)

Three frozen files, three small changes. Each was found by building
sw-design.md §15.5/§15.6 literally, and each is a place where a Wave-0
contract and the design it encodes disagree.

Nothing frozen was edited. Every item below has a working shim inside H4's
owned paths, so the branch is green: `just lint`, `just test` and
`uv run lint-imports` all pass as delivered.

---

## 1. `.importlinter` — `one-llm-seam` needs `allow_indirect_imports = True`

**Why.** The contract forbids `pynvml` to `ra2.services`, `ra2.api` and
`ra2.ui`, and its own comment explains the exemption in terms of *direct*
imports: "`ra2.infra.gpu` the one that may import `pynvml` — neither appears
above, which is what permits it." But `forbidden` contracts report **indirect
chains** unless `allow_indirect_imports` is set, and the two sibling
`forbidden` contracts in the same file both set it for exactly this reason
("Only *direct* imports: ui legitimately calls services…").

`ra2/services/run_service.py` and `ra2/services/evaluation_service.py` import
`GpuProbe` from `ra2.infra.gpu` — which the layer rule explicitly sanctions
("`ra2/services/`: `domain`, `persistence`, **`infra` protocols**") and which
M17 itself wrote. So the moment `ra2/infra/gpu.py` contains a static
`import pynvml`, `lint-imports` reports three broken chains:

```
ra2.services is not allowed to import pynvml:
-   ra2.services.run_service -> ra2.infra.gpu (l.36)
    ra2.infra.gpu -> pynvml (l.112)
```

(plus the same reached through `ra2.api.deps` and `ra2.ui.views.*`). Verified
by running it, not inferred. This is plan-phase-3.md **R4**'s "`import-linter`
gained `pynvml`" not having met an actual `pynvml` import yet.

The `openai` half of the contract is unaffected: nothing above `ra2/infra/`
imports `ra2.infra.ollama_client` — only `ra2/main.py`, which is not a source
module of any contract.

**Proposed diff.**

```diff
--- a/.importlinter
+++ b/.importlinter
@@
 [importlinter:contract:one-llm-seam]
 name = nothing outside the LLMClient implementation imports openai or ollama (§12.1)
 type = forbidden
 source_modules =
     ra2.domain
     ra2.persistence
     ra2.services
     ra2.api
     ra2.ui
 # `pynvml` (the `nvidia-ml-py` distribution) joins the list at phase 3: the GPU
 # probe is an adapter too (sw-design.md §15.6), so `ra2/infra/` stays the only
 # package allowed to load a vendor library. `ra2.infra.ollama_client` is the
 # one module in the repo that may import `openai`, and `ra2.infra.gpu` the one
 # that may import `pynvml` — neither appears above, which is what permits it.
 forbidden_modules =
     openai
     ollama
     pynvml
+# Direct imports only, for the same reason as the ui and api contracts above.
+# `ra2.services` legitimately imports the `GpuProbe` *protocol* from
+# `ra2.infra.gpu` (the layer rule says so), so without this every static
+# `import pynvml` inside the probe reads as a services -> pynvml violation.
+# What the contract protects is unchanged and is additionally asserted on the
+# AST by `tests/test_p3_contract.py` and
+# `tests/backend/infra/test_gpu_probe.py::test_nvml_is_named_only_by_this_module`.
+allow_indirect_imports = True
```

**What H4 did instead.** `ra2/infra/gpu.py`'s `NvmlGpuProbe.describe()` loads
NVML with `import_module("pynvml")` rather than `import pynvml`, marked `SHIM`
with this file named in the comment. A dynamic load is invisible to `grimp`,
so `lint-imports` is green — and because that *weakens* a gate, H4 added a
stricter local one in a path it owns:
`tests/backend/infra/test_gpu_probe.py::test_nvml_is_named_only_by_this_module`
asserts that `pynvml` is named by exactly `ra2/infra/gpu.py` across all of
`ra2/`, covering `import`, `importlib.import_module` and `__import__` alike.

**On applying this amendment:** change the two lines in `describe()` back to
`import pynvml  # type: ignore[import-untyped]  # noqa: PLC0415` (the import
stays *inside* `describe()` — that part is architecture, not a shim) and drop
the SHIM comment. The local test keeps passing either way.

---

## 2. `ra2/domain/llm.py` — `Extraction` has nowhere to carry the retry count

**Why.** sw-design.md §15.4: "Retries bounded and counted. `RA2_LLM_MAX_RETRIES`,
the count **carried back on the `Extraction`** and rendered in the progress
card's metrics line". `ra2/infra/config.py`'s own comment on `llm_max_retries`
repeats it verbatim. The number has a column
(`persistence/models.py: extraction.retry_count`), a read model
(`services/readmodels.py: retries`) and an API field
(`api/schemas.py: retries`) — the **only** place it is missing is the type
that crosses the seam where the retries actually happen.

**Proposed diff.**

```diff
--- a/ra2/domain/llm.py
+++ b/ra2/domain/llm.py
@@ class Extraction[T]:
     latency_ms: int | None = None
     prompt_tokens: int | None = None
     completion_tokens: int | None = None
+    #: Retries **performed**, not attempts made: `0` means the first call
+    #: answered. Bounded by `RA2_LLM_MAX_RETRIES` and never silent — this is
+    #: the number `extraction.retry_count` stores and the progress card's
+    #: "retries N (bounded, counted)" line renders (mvp-spec.md §10.4,
+    #: sw-design.md §15.4).
+    retry_count: int = 0
```

Purely additive, with a default, so every existing construction site keeps
working.

**What H4 did instead.** `ra2/infra/ollama_client.py` defines
`RetriedExtraction[T](Extraction[T])` — a frozen, slotted subclass adding
exactly that field, marked `SHIM`. It *is* a `domain.llm.Extraction` for every
`isinstance` and every annotation, so nothing downstream has to know.
`tests/fixtures/fake_llm.py` imports the same class rather than declaring a
second one, so the double and the real adapter return one type.

**On applying this amendment:** delete the subclass, replace
`RetriedExtraction[T](` with `Extraction[T](` at the three construction sites
(two in `ollama_client.py`, one in `fake_llm.py`) and drop the import in
`fake_llm.py`. `tests/backend/infra/test_ollama_client.py` asserts
`isinstance(result, Extraction)` beside the shim assertions, so the retry tests
survive unchanged.

---

## 3. `ra2/services/errors.py` — `LlmEndpointError` cannot be raised from where
   it says it is raised

**Why.** sw-design.md §15.5 says the loopback guard raises `LlmEndpointError`,
and `services/errors.py`'s own docstring says `REFUSED_NOT_LOOPBACK` is
"Raised by `OllamaLLMClient` **at construction**". But `ra2/infra/` may import
`domain` only, and `lint-imports` rejects it (verified):

```
ra2.infra is not allowed to import ra2.services:
-   ra2.infra.ollama_client -> ra2.services.errors (l.39)
```

Two ways out; **A is recommended** because it is one line and changes no code.

**A — permit the one import** (the mirror image of the M0-D4 deviation already
recorded in `CONTRACTS.md`). `ra2.services.errors` imports nothing but
`ra2.domain`, so there is no cycle:

```diff
--- a/.importlinter
+++ b/.importlinter
@@
 [importlinter:contract:layers]
 name = Layered architecture (sw-design.md §1.1)
 type = layers
 layers =
     ra2.ui
     ra2.api
     ra2.services
     ra2.persistence
     ra2.infra
     ra2.domain
 exhaustive = False
+# The LLM adapter raises the service-layer error the design names for it
+# (sw-design.md §15.5, and `services/errors.py`'s own docstring). The error
+# vocabulary is what crosses the seam, not behaviour: `ra2.services.errors`
+# imports only `ra2.domain`, so this edge creates no cycle. Declared here
+# rather than left implicit; see CONTRACTS.md "Documented deviations".
+ignore_imports =
+    ra2.infra.ollama_client -> ra2.services.errors
```

**B — move the error down to `ra2/domain/llm.py`**, beside `EndpointStatus`,
and re-export it from `services/errors.py`. This follows the repo's existing
pattern (`domain.codes.CodeImportError` wrapped by
`services.errors.CodelistImportError`) but costs more: `LlmEndpointError`
currently subclasses `ServiceError`, which the API's error translation keys
on, so either `ServiceError` moves too or a second type appears.

**What H4 did instead.** `ra2/infra/ollama_client.py` defines a local
`LlmEndpointError(Exception)` with the **same name, same constructor
`(base_url, status)` and same message string** as the real one, marked `SHIM`.

⚠️ **This is the one shim with a downstream trap**: a Wave-2 or Wave-4 agent
writing `from ra2.services.errors import LlmEndpointError` and
`except LlmEndpointError` will *not* catch what the adapter raises until this
amendment lands. It is called out in H4's final report for that reason.

**On applying this amendment (option A):** delete the local class and add
`from ra2.services.errors import LlmEndpointError`. Nothing else in
`ollama_client.py`, `fake_llm.py` or the tests changes — the name and the
constructor were chosen so the diff is exactly those two lines.
