"""Layer 2 fixtures for `/api/v1/evaluations/*` (K2, Wave 3).

Everything is implemented in `_seed.py`, shared with `tests/backend/api/
{runs,models}/**` — all three are K2's own paths (CONTRACTS.md). This file
only re-exports, with the explicit `as` alias mypy strict's
`no_implicit_reexport` requires for a name to count as part of this module's
own public surface (`tests/` carries no `__init__.py`, so a fixture is not
picked up across directories any other way; pytest itself only needs the name
bound in a `conftest.py` module's namespace, regardless of where it was
originally defined).
"""

from tests.backend.api.evaluations._seed import (
    FITTING_MODEL as FITTING_MODEL,
)
from tests.backend.api.evaluations._seed import (
    FIXTURE_GPU as FIXTURE_GPU,
)
from tests.backend.api.evaluations._seed import (
    NOW as NOW,
)
from tests.backend.api.evaluations._seed import (
    OVERSIZED_MODEL as OVERSIZED_MODEL,
)
from tests.backend.api.evaluations._seed import (
    api_client as api_client,
)
from tests.backend.api.evaluations._seed import (
    api_endpoint_prober as api_endpoint_prober,
)
from tests.backend.api.evaluations._seed import (
    api_gpu_probe as api_gpu_probe,
)
from tests.backend.api.evaluations._seed import (
    api_ids as api_ids,
)
from tests.backend.api.evaluations._seed import (
    api_llm_client as api_llm_client,
)
from tests.backend.api.evaluations._seed import (
    api_model_catalog as api_model_catalog,
)
from tests.backend.api.evaluations._seed import (
    create_feature_config as create_feature_config,
)
from tests.backend.api.evaluations._seed import (
    seed_corpus as seed_corpus,
)
from tests.backend.api.evaluations._seed import (
    seed_ready as seed_ready,
)
from tests.backend.api.evaluations._seed import (
    seed_template as seed_template,
)

__all__ = [
    "FITTING_MODEL",
    "FIXTURE_GPU",
    "NOW",
    "OVERSIZED_MODEL",
    "api_client",
    "api_endpoint_prober",
    "api_gpu_probe",
    "api_ids",
    "api_llm_client",
    "api_model_catalog",
    "create_feature_config",
    "seed_corpus",
    "seed_ready",
    "seed_template",
]
