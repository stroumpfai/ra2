"""M17 (phase 3 Wave 0) exit criteria, as tests (plan-phase-3.md §5.2).

Owned by the lead, same reasoning as `test_m0_contract.py` and
`test_p2_contract.py`: a Wave 1+ agent should never need to touch this file,
and a failure here means a frozen contract was edited without an amendment.
"""

import ast
import importlib
from pathlib import Path

import pytest

from ra2.domain.prompt import REQUIRED_SLOTS, SLOTS, SlotName
from ra2.ui.shell import NAV_ITEMS

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_MD = REPO_ROOT / "CONTRACTS.md"

FROZEN_HEADER = "# FROZEN"

#: Every file this wave freezes (plan-phase-3.md §5.1), excluding the ones
#: `test_m0_contract.py` / `test_p2_contract.py` already cover.
NEW_FROZEN_MODULES = [
    "ra2/domain/prompt.py",
    "ra2/domain/extraction.py",
    "ra2/infra/gpu.py",
]

#: Amended, already covered by the earlier contract tests' header checks —
#: re-asserted here so a Wave 0 diff that drops a header is caught locally.
AMENDED_FROZEN_MODULES = [
    "ra2/domain/ids.py",
    "ra2/domain/llm.py",
    "ra2/persistence/models.py",
    "ra2/services/protocols.py",
    "ra2/services/container.py",
    "ra2/services/errors.py",
    "ra2/services/readmodels.py",
    "ra2/api/schemas.py",
    "ra2/api/deps.py",
    "ra2/api/v1/router.py",
    "ra2/infra/config.py",
    "ra2/main.py",
    "tests/conftest.py",
]

#: New, not frozen — a body is expected from Wave 1+ (plan-phase-3.md §6).
NEW_STUB_MODULES = [
    "ra2/services/prompt_service.py",
    "ra2/services/evaluation_service.py",
    "ra2/services/run_service.py",
    "ra2/api/v1/prompt_templates.py",
    "ra2/api/v1/evaluations.py",
    "ra2/api/v1/runs.py",
    "ra2/api/v1/models.py",
    "ra2/infra/ollama_client.py",
    "ra2/ui/views/prompts_view.py",
    "ra2/ui/views/evaluation_view.py",
    "ra2/ui/components/progress_card.py",
    "ra2/ui/components/ollama_settings.py",
    "ra2/ui/components/prompt_preview.py",
]


@pytest.mark.parametrize("relative_path", NEW_FROZEN_MODULES + AMENDED_FROZEN_MODULES)
def test_frozen_module_carries_the_header(relative_path):
    path = REPO_ROOT / relative_path
    assert path.exists(), f"{relative_path} is missing"
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith(FROZEN_HEADER), (
        f"{relative_path} must start with '{FROZEN_HEADER}...' — see CONTRACTS.md"
    )
    assert "CONTRACTS.md" in first_line


@pytest.mark.parametrize("relative_path", NEW_STUB_MODULES)
def test_stub_module_carries_the_header(relative_path):
    path = REPO_ROOT / relative_path
    assert path.exists(), f"{relative_path} is missing"
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("# STUB"), f"{relative_path} must start with '# STUB...'"


@pytest.mark.parametrize("relative_path", NEW_FROZEN_MODULES + NEW_STUB_MODULES)
def test_contracts_md_lists_every_new_file(relative_path):
    text = CONTRACTS_MD.read_text(encoding="utf-8")
    assert relative_path in text, f"CONTRACTS.md does not list {relative_path}"


@pytest.mark.parametrize("relative_path", NEW_FROZEN_MODULES + NEW_STUB_MODULES)
def test_every_new_module_imports(relative_path):
    module = relative_path.removesuffix(".py").replace("/", ".")
    imported = importlib.import_module(module)
    for name in getattr(imported, "__all__", ()):
        assert hasattr(imported, name), f"{module}.__all__ names a missing {name}"


def test_claude_md_names_all_three_migration_authors():
    """One migration author per phase, and the list has to grow with the
    phases (plan-phase-3.md §2.4)."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "A3 for phase 1" in text
    assert "D3 for phase 2" in text
    assert "H3 for phase 3" in text


def test_claude_md_egress_rule_is_loopback_only_not_none():
    """Phase 1's "no egress at all" posture **ends** here — replaced by
    loopback-only, not dropped (plan-phase-3.md §2.4, §15 F4). A CLAUDE.md
    still saying "no egress at all in phase 1" would put a Wave 1+ agent on a
    rule the codebase no longer follows."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "no egress at all in phase 1" not in text
    assert "loopback" in text.lower()


def test_the_phase_3_revision_is_wired_into_the_chain():
    """One phase-3 revision, chained onto phase 2's — not orphaned and not a
    second head (plan-phase-3.md §5.2, CLAUDE.md's one-author rule).

    It is a **real** migration, not the empty stub §5.1 asked for: phase 3
    alters `evaluation`, so an empty one would break every phase-1 and
    phase-2 test that seeds an evaluation row, and §5.2's "every phase-1 and
    phase-2 test still green" is the stricter criterion (P3-D11).
    """
    versions_dir = REPO_ROOT / "ra2/persistence/migrations/versions"
    revisions = [p for p in versions_dir.glob("*.py") if "phase_3_prompts_and_runs" in p.name]
    assert len(revisions) == 1
    text = revisions[0].read_text(encoding="utf-8")
    assert 'down_revision: str | None = "4995824acfe4"' in text
    #: The two constraints that carry invariants rather than tidiness.
    assert 'name="uq_extraction_run_record"' in text, (
        "UNIQUE (run_id, record_id) IS the resume key (sw-design.md §15.3)"
    )
    assert 'ondelete="RESTRICT"' in text, (
        "run.prompt_template_id's RESTRICT IS 'delete only when uncited' (§15.1)"
    )


def test_services_bundle_has_the_three_new_fields(app_factory):
    """A fresh `create_app()` still builds; `Services` has three more fields,
    all satisfiable by the new stub classes (plan-phase-3.md §5.2)."""
    app = app_factory(mount_ui=False)
    services = app.state.services
    assert services.prompt is not None
    assert services.evaluation is not None
    assert services.run is not None


def test_the_four_new_routers_are_registered(app_factory):
    """P31: `/prompt-templates`, `/evaluations`, `/runs`, `/models`."""
    app = app_factory(mount_ui=False)
    paths = set(app.openapi()["paths"])
    for prefix in (
        "/api/v1/prompt-templates",
        "/api/v1/evaluations",
        "/api/v1/runs",
        "/api/v1/models",
    ):
        assert any(p.startswith(prefix) for p in paths), f"no route under {prefix}"


def test_prompt_templates_router_has_no_patch_route(app_factory):
    """**The absence is the contract** (sw-design.md §15.1): saving is
    copy-on-write, so there is no route that edits a version in place. K1's
    exit criteria assert this too; asserting it at the freeze means the route
    can never be added by accident in between."""
    app = app_factory(mount_ui=False)
    schema = app.openapi()["paths"]
    for path, operations in schema.items():
        if path.startswith("/api/v1/prompt-templates"):
            assert "patch" not in operations, f"{path} has a PATCH; §15.1 forbids one"
            assert "put" not in operations, f"{path} has a PUT; §15.1 forbids one"


def test_the_nav_has_eight_items_with_prompts_after_features():
    """The nav change lands at Wave 0, not Wave 4 — J4, J5 and J6 all
    parametrise over `NAV_ITEMS`, so this is where it is proven
    (plan-phase-3.md §5.2)."""
    keys = [item.key for item in NAV_ITEMS]
    assert len(keys) == 8
    assert keys.index("prompts") == keys.index("features") + 1
    prompts = next(i for i in NAV_ITEMS if i.key == "prompts")
    assert prompts.group == "Configure"
    assert prompts.path == "/prompts"
    assert prompts.label == "Prompts"
    #: `built` is deliberately **not** asserted here. It is wave sequencing,
    #: not a contract: §6.1's two-line exception exists precisely so L1 flips
    #: it in Wave 4, and pinning either value makes this frozen, lead-owned
    #: file need an amendment the moment the declared exception is used —
    #: which is what L1 hit (contracts/amendments/feat-p3-prompts-view.md).
    #: What *is* the contract is the entry's identity and position, asserted
    #: above, plus the route resolving at all, which
    #: `test_m0_contract.py`'s NAV_ROUTES asserts whether it is built or not.


def test_the_slot_catalogue_is_closed_and_matches_the_design():
    """Three slots, two required. `{{language}}` is optional and resolves to
    the **evaluation's** `prompt_language` (C1 / §15 F10) — it is no longer
    the "unused" slot the design file marks it as."""
    assert {slot.name for slot in SLOTS} == set(SlotName)
    assert set(REQUIRED_SLOTS) == {SlotName.FEATURE_BLOCK, SlotName.NARRATIVE}
    assert [slot.token for slot in SLOTS] == [
        "{{feature_block}}",
        "{{narrative}}",
        "{{language}}",
    ]


def test_openai_is_imported_in_exactly_one_module():
    """Do-NOT #1, as a test rather than only as an `import-linter` contract.

    The lint rule is the gate; this documents *which* module holds the
    exemption, so a reader of the test suite learns the seam's location
    without reading `.importlinter` (plan-phase-3.md §7, H4).
    """
    offenders = []
    for path in sorted((REPO_ROOT / "ra2").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n == "openai" or n.startswith("openai.") for n in names):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders in ([], ["ra2/infra/ollama_client.py"]), (
        f"openai must be imported only in ra2/infra/ollama_client.py; found {offenders}"
    )


def test_pynvml_is_imported_in_exactly_one_module():
    """The GPU probe is an adapter too (sw-design.md §15.6): `ra2/infra/gpu.py`
    is the one place NVML may be loaded."""
    offenders = []
    for path in sorted((REPO_ROOT / "ra2").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n == "pynvml" or n.startswith("pynvml.") for n in names):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders in ([], ["ra2/infra/gpu.py"]), (
        f"pynvml must be imported only in ra2/infra/gpu.py; found {offenders}"
    )


def test_nothing_shells_out(app_factory):
    """N3, and plan-phase-3.md R2's named failure mode.

    The GPU probe is the first thing in this codebase with an obvious
    temptation to shell out — `nvidia-smi` is one line and NVML is three. It
    is forbidden, so the gate is on the *mechanism*: no module under `ra2/`
    imports `subprocess` or calls `os.system` / `os.popen`, and no `nvidia-smi`
    string reaches executable code.

    Matched on the AST rather than on raw text, the same way
    `test_migrations.py`'s `create_all` gate is: `ra2/infra/gpu.py`'s own
    docstring *states* the rule and names `nvidia-smi` doing so, and a text
    grep would make this permanently red on the file that documents it.
    """
    banned_calls = {"system", "popen", "spawn", "execv", "execvp"}
    offenders = []
    for path in sorted((REPO_ROOT / "ra2").rglob("*.py")):
        relative = str(path.relative_to(REPO_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            ast.get_docstring(n, clean=False)
            for n in ast.walk(tree)
            if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        }
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n == "subprocess" or n.startswith("subprocess.") for n in names):
                offenders.append(f"{relative}: imports subprocess")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in banned_calls
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                offenders.append(f"{relative}:{node.lineno}: os.{node.func.attr}")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "nvidia-smi" in node.value
                and node.value not in docstrings
            ):
                offenders.append(f"{relative}:{node.lineno}: an nvidia-smi literal")
    assert offenders == [], f"N3 forbids shell-outs; found {offenders}"
