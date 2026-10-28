"""A scripted agent that works the spec-from-openapi task through the real tools and the server's call path, as an
agent would, so every probe lands in the ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slimconfig import build_output, plain_output

from contract import SpecInput, SpecOutput
from plugin.__main__ import run_call

# Where each goal's records live, as an agent reads it off the operations' summaries.
GOAL_PATHS = {
    "observations": "/v1/observations",
    "stations": "/v1/stations",
    "alerts": "/v1/alerts",
    "regions": "/v1/regions",
}
# Values for the params the document requires.
REQUIRED_VALUES = {"station_id": "ST-002"}
AUTH = {("apiKey", "header"): "api_key_header", ("apiKey", "query"): "api_key_query", ("http", "bearer"): "bearer"}


def paginator_from(body: Any) -> dict[str, Any]:
    """The paginator a probe's body shows: a next_cursor field, page and total_pages, an offset, or none."""
    if isinstance(body, dict) and "next_cursor" in body:
        return {"type": "cursor", "param": "cursor", "cursor_path": "$.next_cursor"}
    if isinstance(body, dict) and "total_pages" in body:
        return {"type": "page", "param": "page", "cursor_path": None}
    if isinstance(body, dict) and "offset" in body:
        return {"type": "offset", "param": "offset", "cursor_path": None}
    return {"type": "none", "param": None, "cursor_path": None}


def selector_from(body: Any, *, shallow: bool = False) -> str:
    """The JSONPath of the records array in ``body``: $ for a root array, else the first field that holds one, an
    object's field nested deeper; ``shallow`` stops at the first top-level field that holds an array or object."""
    if isinstance(body, list):
        return "$"
    for key, value in sorted(body.items()):
        if isinstance(value, list) or (shallow and isinstance(value, dict)):
            return f"$.{key}"
        if isinstance(value, dict) and any(isinstance(inner, list) for inner in value.values()):
            return f"$.{key}" + selector_from(value).removeprefix("$")
    raise ValueError("no records array in the body")


def run_agent(
    workspace: Path,
    task: SpecInput,
    *,
    probe: bool = True,
    first_server: bool = False,
    default_auth: bool = False,
    shallow_selector: bool = False,
) -> SpecOutput:
    """Read the document, probe the goal's endpoint, and write a spec from what the probe shows.

    Each switch makes one mistake: ``probe=False`` writes the spec from the document alone (no paginator, the
    first declared field), never probing; ``first_server`` takes the first server listed, deprecated or not;
    ``default_auth`` takes the document's default security even where the operation declares its own;
    ``shallow_selector`` selects the first top-level field of the body that holds an array or an object."""
    document = task.document.value
    read = run_call("read_openapi", {"document": document}, workspace)
    path = GOAL_PATHS[task.goal.value]
    operation = next(item for item in read["operations"] if item["path"] == path and item["method"] == "GET")
    params = [{"name": p["name"], "value": REQUIRED_VALUES[p["name"]]} for p in operation["params"] if p["required"]]
    if probe:
        given = {"document": document, "path": path, "method": "GET", "params": params}
        body = json.loads(run_call("probe", given, workspace)["body"])
        paginator, selector = paginator_from(body), selector_from(body, shallow=shallow_selector)
    else:
        paginator = {"type": "none", "param": None, "cursor_path": None}
        fields = operation["response_fields"]
        selector = f"$.{fields[0]}" if fields else "$"
    own = operation["security"]
    security = read["default_security"] if default_auth or own is None else own
    scheme = next(item for item in read["schemes"] if item["name"] == security[0])
    servers = read["servers"] if first_server else [server for server in read["servers"] if not server["deprecated"]]
    spec = {
        "base_url": servers[0]["url"],
        "auth": AUTH[(scheme["type"], scheme["location"] or scheme["scheme"])],
        "auth_ref": scheme["credential_ref"],
        "endpoints": [
            {"path": path, "method": "GET", "params": params, "record_selector": selector, "paginator": paginator}
        ],
    }
    written = run_call("write_spec", {"spec": spec}, workspace)
    # What the sandbox hands the verifier: the output rebuilt from its JSON.
    return build_output(plain_output(build_output({"path": written["path"]}, SpecOutput)), SpecOutput)
