"""Contract tests for API schema conformance using Schemathesis.

Property-based fuzzing: generates random valid/invalid inputs from the
OpenAPI schema and tests every endpoint automatically.  Tests auto-update
when the schema changes -- zero maintenance.

Endpoints that require a running model backend (MLflow/Redis) are expected
to return 500 when those services are unavailable.  The ``not_a_server_error``
and ``status_code_conformance`` checks are excluded so that 5xx from missing
backends do not cause false failures -- every other contract check still runs.
"""

import schemathesis
from schemathesis import checks

from src.api.main import app

# Ensure all built-in checks are registered (some are lazy-loaded)
checks.load_all_checks()

# ---------------------------------------------------------------------------
# Build the Schemathesis schema from the live ASGI app
# ---------------------------------------------------------------------------
schema = schemathesis.openapi.from_asgi(
    "/openapi.json",
    app=app,
    generation_config=schemathesis.config.GenerationConfig(max_examples=10),
)


# ---------------------------------------------------------------------------
# Property-based contract test -- one parametrized case per operation
# ---------------------------------------------------------------------------
@schema.parametrize()
def test_api_contract(case):
    """Every endpoint must return a response that conforms to its OpenAPI spec.

    Schemathesis generates random valid payloads from the declared request
    schemas and validates the response status code + body against the
    declared response schema.

    We exclude ``not_a_server_error`` and ``status_code_conformance`` because
    endpoints that hit MLflow/Redis will return 500 when those services are
    not running -- that is an infrastructure concern, not a contract violation.
    All other checks (response_schema_conformance, content_type_conformance,
    response_headers_conformance, etc.) remain active.
    """
    case.call_and_validate(
        excluded_checks=[
            checks.not_a_server_error,
            checks.status_code_conformance,
        ],
    )
