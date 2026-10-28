from __future__ import annotations

from pathlib import Path

from contract import EndpointFacts, OpenapiIndexOutput, SpecInput
from plugin.api import EXAMPLE_KEYS, GOALS, HONOURED, auth_of, operation, read


def openapi_index(given: SpecInput, workspace: Path) -> OpenapiIndexOutput:
    """The reference tool: every declared operation with its declared and honoured params and its real paginator,
    the goal's endpoint and its auth. The agent never sees it."""
    honoured = HONOURED[given.document]
    endpoints = [
        EndpointFacts(
            path=declared.path,
            method=declared.method,
            declared_params=[param.name for param in declared.params],
            honoured_params=sorted(honoured[(declared.path, declared.method)][0]),
            paginator=honoured[(declared.path, declared.method)][1],
        )
        for declared in read(given.document).operations
    ]
    path, method = GOALS[given.goal]
    auth, auth_ref = auth_of(given.document, operation(given.document, path, method))
    return OpenapiIndexOutput(
        servers=[server.url for server in read(given.document).servers if not server.deprecated],
        endpoints=endpoints,
        required_path=path,
        required_method=method,
        auth=auth,
        auth_ref=auth_ref,
        example_keys=list(EXAMPLE_KEYS[given.document]),
    )
