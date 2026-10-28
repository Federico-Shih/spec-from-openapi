from __future__ import annotations

import json
from pathlib import Path

import pytest
from slimconfig import build_output

from contract import AuthKind, Method, PaginatorType, ProbeInput, ReadOpenapiInput, SpecInput, Tool, WriteSpecInput
from plugin import openapi_index, probe, read_openapi, write_spec
from plugin.__main__ import IMPLEMENTATIONS, run_call
from plugin.api import PAGE_SIZE
from plugin.engine import LEDGER
from plugin.writing import SPEC

DOC = "aqua-metrics"


def ask(path: str, method: str = "GET", **params: str) -> ProbeInput:
    given = {
        "document": DOC,
        "path": path,
        "method": method,
        "params": [{"name": k, "value": v} for k, v in params.items()],
    }
    return build_output(given, ProbeInput)


def body(path: str, method: str = "GET", **params: str):
    return json.loads(probe(ask(path, method, **params), Path(".")).body)


def test_every_tool_is_implemented() -> None:
    assert set(IMPLEMENTATIONS) == set(Tool)


def test_read_openapi_types_every_operation_and_scheme(tmp_path: Path) -> None:
    read = read_openapi(build_output({"document": DOC}, ReadOpenapiInput), tmp_path)
    keys = [(operation.method.value, operation.path) for operation in read.operations]
    assert len(keys) == 6 and ("POST", "/v1/stations") in keys
    by_key = {(operation.method.value, operation.path): operation for operation in read.operations}
    assert [param.name for param in by_key["GET", "/v1/observations"].params] == ["station_id", "since", "limit"]
    # Security as written: an operation's own (observations and POST stations override the default, status is
    # public), or null where the default applies.
    assert read.default_security == ["ApiKeyHeader"]
    assert by_key["GET", "/v1/observations"].security == ["ObservationsQueryKey"]
    assert by_key["POST", "/v1/stations"].security == ["PartnerBearer"]
    assert by_key["GET", "/v1/status"].security == []
    assert by_key["GET", "/v1/stations"].security is None
    assert by_key["GET", "/v1/regions"].params == [] and by_key["GET", "/v1/regions"].response_type == "array"
    assert {(s.name, s.credential_ref) for s in read.schemes} == {
        ("ApiKeyHeader", "AQUA_METRICS_API_KEY"),
        ("PartnerBearer", "AQUA_METRICS_PARTNER_TOKEN"),
        ("ObservationsQueryKey", "AQUA_OBSERVATIONS_KEY"),
    }
    # The first server listed is deprecated.
    assert [(server.url, server.deprecated) for server in read.servers] == [
        ("https://v0.aquametrics.example", True),
        ("https://api.aquametrics.example", False),
        ("https://sandbox.aquametrics.example", False),
    ]


def test_probe_refuses_undeclared_operations_and_repeated_params(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="not declared"):
        probe(ask("/v1/readings"), tmp_path)
    with pytest.raises(LookupError, match="not declared"):
        probe(ask("/v1/regions", "POST"), tmp_path)
    with pytest.raises(ValueError, match="repeat"):
        twice = [{"name": "page", "value": "1"}, {"name": "page", "value": "2"}]
        probe(
            build_output({"document": DOC, "path": "/v1/stations", "method": "GET", "params": twice}, ProbeInput),
            tmp_path,
        )


def test_observations_page_by_an_undeclared_cursor_and_ignore_limit() -> None:
    # The records sit one level down, in data.items.
    first = body("/v1/observations", station_id="ST-002", limit="2")
    assert len(first["data"]["items"]) == first["data"]["count"] == PAGE_SIZE and first["next_cursor"] == "cursor-5"
    last = body("/v1/observations", station_id="ST-002", cursor=first["next_cursor"])
    assert len(last["data"]["items"]) == 2 and last["next_cursor"] is None
    assert all(row["station_id"] == "ST-002" for row in first["data"]["items"] + last["data"]["items"])
    with pytest.raises(ValueError, match="station_id is required"):
        body("/v1/observations")
    with pytest.raises(ValueError, match="unknown cursor"):
        body("/v1/observations", station_id="ST-002", cursor="cursor-99")


def test_stations_page_by_page_number() -> None:
    first, third = body("/v1/stations"), body("/v1/stations", page="3")
    assert (len(first["results"]), first["total_pages"], len(third["results"])) == (4, 3, 1)
    assert {row["country"] for row in body("/v1/stations", country="NO")["results"]} == {"NO"}
    with pytest.raises(ValueError, match="page"):
        body("/v1/stations", page="zero")


def test_alerts_page_by_offset_and_ignore_page() -> None:
    assert body("/v1/alerts", page="2") == body("/v1/alerts")
    moved = body("/v1/alerts", offset="5")
    assert moved["items"][0]["id"] == "al-006" and moved["total"] == 13
    assert {row["severity"] for row in body("/v1/alerts", severity="high")["items"]} == {"high"}


def test_regions_are_a_root_array_and_status_an_object() -> None:
    assert isinstance(body("/v1/regions"), list) and len(body("/v1/regions")) == 4
    assert body("/v1/status")["status"] == "ok"


def test_write_spec_writes_and_replaces_spec_json(tmp_path: Path) -> None:
    spec = {
        "base_url": "https://api.aquametrics.example",
        "auth": "api_key_header",
        "auth_ref": "AQUA_METRICS_API_KEY",
        "endpoints": [
            {
                "path": "/v1/regions",
                "method": "GET",
                "params": [],
                "record_selector": "$",
                "paginator": {"type": "none", "param": None, "cursor_path": None},
            }
        ],
    }
    output = write_spec(build_output({"spec": spec}, WriteSpecInput), tmp_path)
    assert (output.path, output.endpoints) == (SPEC, 1)
    assert json.loads((tmp_path / SPEC).read_text()) == spec
    write_spec(build_output({"spec": {**spec, "endpoints": []}}, WriteSpecInput), tmp_path)
    assert json.loads((tmp_path / SPEC).read_text())["endpoints"] == []


@pytest.mark.parametrize(
    ("goal", "path", "paginator"),
    [
        ("observations", "/v1/observations", PaginatorType.CURSOR),
        ("stations", "/v1/stations", PaginatorType.PAGE),
        ("alerts", "/v1/alerts", PaginatorType.OFFSET),
        ("regions", "/v1/regions", PaginatorType.NONE),
    ],
)
def test_openapi_index_names_the_goal_endpoint_and_its_facts(tmp_path: Path, goal, path, paginator) -> None:
    index = openapi_index(build_output({"document": DOC, "goal": goal}, SpecInput), tmp_path)
    assert (index.required_path, index.required_method) == (path, Method.GET)
    # Observations declares its own scheme; the other goals use the document's default.
    if goal == "observations":
        assert (index.auth, index.auth_ref) == (AuthKind.API_KEY_QUERY, "AQUA_OBSERVATIONS_KEY")
    else:
        assert (index.auth, index.auth_ref) == (AuthKind.API_KEY_HEADER, "AQUA_METRICS_API_KEY")
    facts = {(item.path, item.method): item for item in index.endpoints}
    assert facts[path, Method.GET].paginator.type is paginator and len(facts) == 6
    assert index.example_keys == ["amk_live_4f9c2e7a1b8d3c6e5f0a"]
    # A spec's base_url may be any server but the deprecated one.
    assert index.servers == ["https://api.aquametrics.example", "https://sandbox.aquametrics.example"]


def test_the_server_records_every_call_in_the_ledger(tmp_path: Path) -> None:
    run_call("probe", {"document": DOC, "path": "/v1/regions", "method": "GET", "params": []}, tmp_path)
    with pytest.raises(LookupError):
        run_call("probe", {"document": DOC, "path": "/v1/nope", "method": "GET", "params": []}, tmp_path)
    calls = [json.loads(line) for line in (tmp_path / LEDGER).read_text().splitlines()]
    assert [call["call_id"] for call in calls] == ["call-0001", "call-0002"]
    assert "response" in calls[0] and calls[1]["error"].startswith("LookupError")
