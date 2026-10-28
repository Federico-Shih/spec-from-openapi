from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from fakes import run_agent
from slimconfig import build_output, plain_output

import verifier
from contract import (
    OpenapiIndexOutput,
    ProbeInput,
    ProbeOutput,
    ReadOpenapiInput,
    ReadOpenapiOutput,
    SpecInput,
    SpecOutput,
    WriteSpecInput,
    WriteSpecOutput,
)
from plugin import openapi_index, probe, read_openapi, write_spec
from plugin.__main__ import run_call
from plugin.engine import LEDGER
from plugin.writing import SPEC
from verifier import checks
from verifier.spec import PARTS

TASK = "spec-from-openapi"
DOC = "aqua-metrics"
GOALS = ("observations", "stations", "alerts", "regions")
EXAMPLE_KEY = "amk_live_4f9c2e7a1b8d3c6e5f0a"
NO_PAGES = {"type": "none", "param": None, "cursor_path": None}
CHECK_KEYS = {"id", "constraint", "ok", "expected", "actual", "message"}
# The README's Checks table, in order: the five integrity checks, then the outcome checks.
CHECK_IDS = (
    "reference",
    "spec-written",
    "spec-shape",
    "ledger",
    "no-leak",
    "submitted-path",
    "base-url",
    "auth",
    "auth-ref",
    "has-endpoints",
    "goal-endpoint",
    "endpoints-declared",
    "params-declared",
    "params-honoured",
    "paginator",
    "record-selector",
)


# The verifier gets contract instances, as NanoAgent's sandbox builds them from JSON.
def task(goal: str) -> SpecInput:
    return build_output({"document": DOC, "goal": goal}, SpecInput)


def index(given: SpecInput, scratch: Path) -> OpenapiIndexOutput:
    return build_output(plain_output(openapi_index(given, scratch)), OpenapiIndexOutput)


def submitted(path: str = SPEC) -> SpecOutput:
    return build_output({"path": path}, SpecOutput)


def judge(workspace: Path, goal: str, output: SpecOutput) -> dict:
    given = task(goal)
    verdict = verifier.verify_task(TASK, given, output, index(given, workspace / "scratch"), str(workspace))
    # The README's verdict contract, checked on every verdict: score 1.0 exactly when valid; every check has the
    # same keys, in the README's order; valid exactly when every check holds; the message leads with the first
    # failing check and counts the rest; a skipped check names the one it waited on.
    assert (verdict["score"] == 1.0) is verdict["valid"] and 0.0 <= verdict["score"] <= 1.0
    entries = verdict["details"]["checks"]
    assert all(set(entry) == CHECK_KEYS for entry in entries)
    ids = [entry["id"] for entry in entries]
    assert ids == [id for id in CHECK_IDS if id in ids] and ids[:5] == list(CHECK_IDS[:5])
    assert verdict["valid"] is all(entry["ok"] for entry in entries)
    failing = [entry for entry in entries if entry["ok"] is False]
    if failing:
        more = f" (+{len(failing) - 1} more)" if len(failing) > 1 else ""
        assert verdict["message"] == f"{failing[0]['id']}: {failing[0]['message']}{more}"
    for entry in entries:
        assert (entry["message"] == "") is (entry["ok"] is True)
        if entry["ok"] is None:
            assert re.fullmatch(r"Not checked: [a-z-]+ did not hold\.", entry["message"])
    return verdict


def check_of(verdict: dict, id: str) -> dict:
    return next(entry for entry in verdict["details"]["checks"] if entry["id"] == id)


def spec_of(workspace: Path) -> dict:
    return json.loads((workspace / SPEC).read_text())


def rewrite(workspace: Path, change: Callable[[dict], None]) -> SpecOutput:
    """Change the written spec and write it again through write_spec, as an agent would."""
    spec = spec_of(workspace)
    change(spec)
    return SpecOutput(path=run_call("write_spec", {"spec": spec}, workspace)["path"])


def call_probe(workspace: Path, path: str, method: str = "GET", **params: str) -> None:
    given = {
        "document": DOC,
        "path": path,
        "method": method,
        "params": [{"name": k, "value": v} for k, v in params.items()],
    }
    run_call("probe", given, workspace)


def endpoint(path: str, selector: str, paginator: dict = NO_PAGES, method: str = "GET", params=()) -> dict:
    return {"path": path, "method": method, "params": list(params), "record_selector": selector, "paginator": paginator}


def failed(verdict: dict) -> dict:
    return verdict["details"]["failed_endpoints"]


def test_the_verifier_mirrors_the_plugin_constants() -> None:
    assert checks.SPEC == SPEC


# Correct
@pytest.mark.parametrize("goal", GOALS)
def test_approves_the_spec_the_probes_show(tmp_path: Path, goal: str) -> None:
    verdict = judge(tmp_path, goal, run_agent(tmp_path, task(goal)))
    assert verdict["valid"] is True and verdict["score"] == 1.0 and failed(verdict) == {}
    assert [entry["id"] for entry in verdict["details"]["checks"]] == list(CHECK_IDS)


def test_approves_an_extra_endpoint_that_is_right_too(tmp_path: Path) -> None:
    run_agent(tmp_path, task("observations"))
    call_probe(tmp_path, "/v1/regions")
    output = rewrite(tmp_path, lambda spec: spec["endpoints"].append(endpoint("/v1/regions", "$[*]")))
    assert judge(tmp_path, "observations", output)["valid"] is True


def test_approves_the_sandbox_server(tmp_path: Path) -> None:
    run_agent(tmp_path, task("regions"))
    output = rewrite(tmp_path, lambda spec: spec.update(base_url="https://sandbox.aquametrics.example"))
    assert judge(tmp_path, "regions", output)["valid"] is True


def test_the_example_spec_reads_the_override_and_the_nested_records(tmp_path: Path) -> None:
    run_agent(tmp_path, task("observations"))
    spec = spec_of(tmp_path)
    assert (spec["base_url"], spec["auth"], spec["auth_ref"]) == (
        "https://api.aquametrics.example",
        "api_key_query",
        "AQUA_OBSERVATIONS_KEY",
    )
    assert spec["endpoints"][0]["record_selector"] == "$.data.items"


# Wrong: the traps the example sets
@pytest.mark.parametrize(
    ("mistake", "wrong", "endpoint_checks"),
    [
        pytest.param({"first_server": True}, ["base_url"], {}, id="the deprecated server listed first"),
        pytest.param({"default_auth": True}, ["auth", "auth_ref"], {}, id="the default security, not the override"),
        pytest.param(
            {"shallow_selector": True},
            ["endpoints"],
            {"GET /v1/observations": ["record_selector"]},
            id="the top-level field, an object",
        ),
    ],
)
def test_each_trap_costs_its_parts(tmp_path: Path, mistake: dict, wrong: list, endpoint_checks: dict) -> None:
    verdict = judge(tmp_path, "observations", run_agent(tmp_path, task("observations"), **mistake))
    assert verdict["valid"] is False
    assert [part for part, right in verdict["details"]["parts"].items() if float(right) < 1.0] == wrong
    assert failed(verdict) == endpoint_checks


# Wrong
def test_refuses_a_made_up_endpoint(tmp_path: Path) -> None:
    run_agent(tmp_path, task("regions"))
    output = rewrite(tmp_path, lambda spec: spec["endpoints"].append(endpoint("/v1/readings", "$.data")))
    verdict = judge(tmp_path, "regions", output)
    assert verdict["valid"] is False and len(failed(verdict)["GET /v1/readings"]) == 5
    assert verdict["details"]["parts"]["endpoints"] == 0.5


def test_refuses_a_declared_path_with_an_undeclared_method(tmp_path: Path) -> None:
    run_agent(tmp_path, task("regions"))
    output = rewrite(tmp_path, lambda spec: spec["endpoints"][0].update(method="POST"))
    verdict = judge(tmp_path, "regions", output)
    assert verdict["valid"] is False and "declared" in failed(verdict)["POST /v1/regions"]
    assert verdict["details"]["parts"]["required_endpoint"] is False


def test_refuses_a_declared_operation_that_is_not_the_goals(tmp_path: Path) -> None:
    run_agent(tmp_path, task("stations"))
    call_probe(tmp_path, "/v1/stations", "POST")
    output = rewrite(
        tmp_path, lambda spec: spec["endpoints"][0].update(method="POST", paginator=NO_PAGES, record_selector="$")
    )
    verdict = judge(tmp_path, "stations", output)
    assert verdict["valid"] is False and verdict["details"]["parts"]["required_endpoint"] is False
    assert failed(verdict)["POST /v1/stations"] == ["record_selector"]  # its body is an object


def test_refuses_an_undeclared_param_even_one_the_api_honours(tmp_path: Path) -> None:
    run_agent(tmp_path, task("observations"))
    output = rewrite(
        tmp_path, lambda spec: spec["endpoints"][0]["params"].append({"name": "cursor", "value": "cursor-5"})
    )
    verdict = judge(tmp_path, "observations", output)
    assert verdict["valid"] is False and failed(verdict)["GET /v1/observations"] == ["params_declared"]


def test_refuses_a_declared_param_the_api_ignores(tmp_path: Path) -> None:
    run_agent(tmp_path, task("observations"))
    output = rewrite(tmp_path, lambda spec: spec["endpoints"][0]["params"].append({"name": "limit", "value": "100"}))
    verdict = judge(tmp_path, "observations", output)
    assert verdict["valid"] is False and failed(verdict)["GET /v1/observations"] == ["params_honoured"]


def test_refuses_a_repeated_param(tmp_path: Path) -> None:
    run_agent(tmp_path, task("observations"))
    output = rewrite(tmp_path, lambda spec: spec["endpoints"][0]["params"].append({"name": "station_id", "value": "x"}))
    assert failed(judge(tmp_path, "observations", output))["GET /v1/observations"] == ["params_declared"]


@pytest.mark.parametrize(
    "paginator",
    [
        pytest.param({"type": "page", "param": "page", "cursor_path": None}, id="the declared page param"),
        pytest.param({"type": "offset", "param": "skip", "cursor_path": None}, id="the wrong offset param"),
        pytest.param(NO_PAGES, id="none"),
    ],
)
def test_refuses_a_wrong_paginator(tmp_path: Path, paginator: dict) -> None:
    run_agent(tmp_path, task("alerts"))
    output = rewrite(tmp_path, lambda spec: spec["endpoints"][0].update(paginator=paginator))
    verdict = judge(tmp_path, "alerts", output)
    assert verdict["valid"] is False and failed(verdict)["GET /v1/alerts"] == ["paginator"]
    # One check of five on the one endpoint: the endpoints part is 0.8 of the six parts.
    assert verdict["score"] == round((5 + 0.8) / len(PARTS), 4)
    entry = check_of(verdict, "paginator")
    assert entry["expected"] == {"GET /v1/alerts": {"type": "offset", "param": "offset", "cursor_path": None}}
    assert entry["actual"] == {"GET /v1/alerts": paginator}


def test_refuses_a_cursor_paginator_with_the_wrong_cursor_path(tmp_path: Path) -> None:
    run_agent(tmp_path, task("observations"))
    paginator = {"type": "cursor", "param": "cursor", "cursor_path": "$.next"}
    output = rewrite(tmp_path, lambda spec: spec["endpoints"][0].update(paginator=paginator))
    assert failed(judge(tmp_path, "observations", output))["GET /v1/observations"] == ["paginator"]


@pytest.mark.parametrize(
    "selector",
    [
        pytest.param("$", id="an object"),
        pytest.param("$.page", id="a number"),
        pytest.param("$.records", id="a missing key"),
        pytest.param("$.results.id", id="a key inside an array"),
        pytest.param("data[*]", id="not a JSONPath"),
        pytest.param("$..results", id="recursive descent"),
    ],
)
def test_refuses_a_record_selector_that_picks_no_array(tmp_path: Path, selector: str) -> None:
    run_agent(tmp_path, task("stations"))
    output = rewrite(tmp_path, lambda spec: spec["endpoints"][0].update(record_selector=selector))
    verdict = judge(tmp_path, "stations", output)
    assert verdict["valid"] is False and failed(verdict)["GET /v1/stations"] == ["record_selector"]


def test_refuses_a_wrong_auth_ref_and_kind(tmp_path: Path) -> None:
    run_agent(tmp_path, task("stations"))
    output = rewrite(tmp_path, lambda spec: spec.update(auth="bearer", auth_ref="AQUA_METRICS_PARTNER_TOKEN"))
    verdict = judge(tmp_path, "stations", output)
    assert verdict["valid"] is False and verdict["score"] == round(4 / 6, 4)
    assert [part for part, right in verdict["details"]["parts"].items() if not right] == ["auth", "auth_ref"]


def test_refuses_a_base_url_the_document_does_not_declare(tmp_path: Path) -> None:
    run_agent(tmp_path, task("regions"))
    output = rewrite(tmp_path, lambda spec: spec.update(base_url="https://aquametrics.example/api"))
    assert judge(tmp_path, "regions", output)["details"]["parts"]["base_url"] is False


def test_refuses_a_wrong_submitted_path(tmp_path: Path) -> None:
    run_agent(tmp_path, task("regions"))
    verdict = judge(tmp_path, "regions", submitted("specs/spec.json"))
    assert verdict["valid"] is False and verdict["details"]["parts"]["path"] is False


def test_refuses_a_record_selector_never_probed(tmp_path: Path) -> None:
    # The document alone gives regions' right spec, but nothing in the ledger shows the selector works.
    verdict = judge(tmp_path, "regions", run_agent(tmp_path, task("regions"), probe=False))
    assert verdict["valid"] is False and failed(verdict)["GET /v1/regions"] == ["record_selector"]
    call_probe(tmp_path, "/v1/regions")
    assert judge(tmp_path, "regions", submitted())["valid"] is True


def test_a_failed_probe_shows_nothing(tmp_path: Path) -> None:
    run_agent(tmp_path, task("observations"), probe=False)
    with pytest.raises(ValueError):
        call_probe(tmp_path, "/v1/observations")  # station_id is required: the call fails
    verdict = judge(tmp_path, "observations", submitted())
    assert "record_selector" in failed(verdict)["GET /v1/observations"]


def test_a_probe_of_another_operation_does_not_count(tmp_path: Path) -> None:
    run_agent(tmp_path, task("regions"), probe=False)
    call_probe(tmp_path, "/v1/stations")
    assert failed(judge(tmp_path, "regions", submitted()))["GET /v1/regions"] == ["record_selector"]


# Leaks: a key-like auth_ref or the document's example key scores 0.
@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda spec: spec.update(auth_ref=EXAMPLE_KEY), id="the example key as auth_ref"),
        pytest.param(lambda spec: spec.update(auth_ref="aqua_metrics_api_key"), id="a lowercase ref"),
        pytest.param(lambda spec: spec.update(auth_ref="4f9c2e7a-1b8d-3c6e"), id="a key-shaped ref"),
        pytest.param(
            lambda spec: spec["endpoints"][0]["params"].append({"name": "api_key", "value": EXAMPLE_KEY}),
            id="the example key as a param",
        ),
    ],
)
def test_a_key_in_the_spec_scores_zero(tmp_path: Path, change) -> None:
    run_agent(tmp_path, task("observations"))
    verdict = judge(tmp_path, "observations", rewrite(tmp_path, change))
    assert verdict["valid"] is False and verdict["score"] == 0.0 and verdict["details"]["leak"] is True
    assert verdict["message"].startswith("no-leak: spec.json holds a key, not a credential NAME")


# Missing
def test_refuses_a_missing_spec_file(tmp_path: Path) -> None:
    verdict = judge(tmp_path, "regions", submitted())
    assert verdict["valid"] is False and verdict["score"] == 0.0
    assert verdict["message"] == "spec-written: no spec.json: write_spec was never called"
    assert check_of(verdict, "spec-shape")["message"] == "Not checked: spec-written did not hold."


def test_refuses_a_spec_with_no_endpoints(tmp_path: Path) -> None:
    run_agent(tmp_path, task("regions"))
    verdict = judge(tmp_path, "regions", rewrite(tmp_path, lambda spec: spec.update(endpoints=[])))
    assert verdict["message"] == "has-endpoints: spec.json has no endpoints (+1 more)"  # and goal-endpoint
    assert verdict["score"] == round(4 / 6, 4)  # no required endpoint, and an endpoints part of 0
    skipped = [entry["id"] for entry in verdict["details"]["checks"] if entry["ok"] is None]
    assert skipped == list(CHECK_IDS[11:])
    assert check_of(verdict, "paginator")["message"] == "Not checked: has-endpoints did not hold."


def test_refuses_a_spec_with_no_auth(tmp_path: Path) -> None:
    run_agent(tmp_path, task("alerts"))
    verdict = judge(tmp_path, "alerts", rewrite(tmp_path, lambda spec: spec.update(auth="none", auth_ref=None)))
    assert verdict["valid"] is False and verdict["details"]["parts"]["auth_ref"] is False


def test_refuses_a_task_without_a_reference(tmp_path: Path) -> None:
    run_agent(tmp_path, task("regions"))
    verdict = verifier.verify_task(TASK, task("regions"), submitted(), None, str(tmp_path))
    assert verdict["valid"] is False and verdict["score"] == 0.0
    assert verdict["message"] == "reference: no reference: openapi_index was not pinned"
    assert check_of(verdict, "no-leak")["message"] == "Not checked: reference did not hold."


# Malformed
GOOD_ENDPOINT = endpoint("/v1/regions", "$")
GOOD = {"base_url": "https://api.aquametrics.example", "auth": "api_key_header", "auth_ref": "AQUA_METRICS_API_KEY"}


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("{not json", id="not JSON"),
        pytest.param("[]", id="a list"),
        pytest.param(json.dumps({**GOOD, "endpoints": {}}), id="endpoints not a list"),
        pytest.param(json.dumps({**GOOD}), id="no endpoints key"),
        pytest.param(json.dumps({**GOOD, "auth": "apiKey", "endpoints": [GOOD_ENDPOINT]}), id="an unknown auth"),
        pytest.param(json.dumps({**GOOD, "auth_ref": 7, "endpoints": [GOOD_ENDPOINT]}), id="a number auth_ref"),
        pytest.param(json.dumps({**GOOD, "endpoints": [{**GOOD_ENDPOINT, "method": "get"}]}), id="a lowercase method"),
        pytest.param(json.dumps({**GOOD, "endpoints": [{**GOOD_ENDPOINT, "params": {"a": "b"}}]}), id="params a dict"),
        pytest.param(
            json.dumps({**GOOD, "endpoints": [{**GOOD_ENDPOINT, "params": [{"name": "page", "value": 2}]}]}),
            id="a number param value",
        ),
        pytest.param(
            json.dumps({**GOOD, "endpoints": [{**GOOD_ENDPOINT, "paginator": "none"}]}), id="a bare paginator"
        ),
        pytest.param(
            json.dumps({**GOOD, "endpoints": [{**GOOD_ENDPOINT, "paginator": {**NO_PAGES, "type": "link"}}]}),
            id="an unknown paginator",
        ),
        pytest.param(json.dumps({**GOOD, "endpoints": [{**GOOD_ENDPOINT, "note": "x"}]}), id="an extra endpoint key"),
    ],
)
def test_refuses_a_malformed_spec_file(tmp_path: Path, text: str) -> None:
    call_probe(tmp_path, "/v1/regions")
    (tmp_path / SPEC).write_text(text)
    verdict = judge(tmp_path, "regions", submitted())
    assert verdict["valid"] is False and verdict["score"] == 0.0 and SPEC in verdict["message"]


def test_refuses_a_broken_ledger(tmp_path: Path) -> None:
    run_agent(tmp_path, task("regions"))
    with (tmp_path / LEDGER).open("a") as ledger:
        ledger.write("{broken\n")
    verdict = judge(tmp_path, "regions", submitted())
    assert verdict["valid"] is False and verdict["score"] == 0.0
    assert verdict["message"] == "ledger: the call ledger is broken: ledger line 4 is not JSON"
    assert check_of(verdict, "base-url")["ok"] is True  # the spec is still judged, for the record
    assert check_of(verdict, "record-selector")["message"] == "Not checked: ledger did not hold."


# Boundary
def test_the_cursor_shows_only_in_a_probe(tmp_path: Path) -> None:
    # The document declares no cursor and no next_cursor field: an agent that never probes writes no paginator.
    unprobed = tmp_path / "unprobed"
    unprobed.mkdir()
    verdict = judge(unprobed, "observations", run_agent(unprobed, task("observations"), probe=False))
    assert failed(verdict)["GET /v1/observations"] == ["paginator", "record_selector"]
    probed = tmp_path / "probed"
    probed.mkdir()
    assert judge(probed, "observations", run_agent(probed, task("observations")))["valid"] is True
    assert spec_of(probed)["endpoints"][0]["paginator"]["type"] == "cursor"


def test_an_endpoint_with_no_params_and_a_root_selector(tmp_path: Path) -> None:
    assert judge(tmp_path, "regions", run_agent(tmp_path, task("regions")))["valid"] is True
    spec = spec_of(tmp_path)["endpoints"][0]
    assert (spec["params"], spec["record_selector"]) == ([], "$")
    output = rewrite(tmp_path, lambda spec: spec["endpoints"][0].update(record_selector="$[*]"))
    assert judge(tmp_path, "regions", output)["valid"] is True


def test_an_empty_array_still_counts_as_records(tmp_path: Path) -> None:
    run_agent(tmp_path, task("stations"), probe=False)
    call_probe(tmp_path, "/v1/stations", page="9")
    paginator = {"type": "page", "param": "page", "cursor_path": None}
    output = rewrite(
        tmp_path, lambda spec: spec["endpoints"][0].update(record_selector="$.results", paginator=paginator)
    )
    assert judge(tmp_path, "stations", output)["valid"] is True


def test_a_decoy_endpoint_lowers_the_score_of_a_right_spec(tmp_path: Path) -> None:
    run_agent(tmp_path, task("regions"))
    call_probe(tmp_path, "/v1/status")
    output = rewrite(tmp_path, lambda spec: spec["endpoints"].append(endpoint("/v1/status", "$")))
    verdict = judge(tmp_path, "regions", output)
    assert verdict["valid"] is False and failed(verdict) == {"GET /v1/status": ["record_selector"]}
    assert verdict["score"] == round((5 + 0.9) / 6, 4)


# Tools
def test_read_openapi_checks(tmp_path: Path) -> None:
    given = build_output({"document": DOC}, ReadOpenapiInput)
    made = build_output(plain_output(read_openapi(given, tmp_path)), ReadOpenapiOutput)
    assert verifier.verify_input("read_openapi", given)["valid"] is True
    assert verifier.verify_output("read_openapi", given, made, str(tmp_path))["valid"] is True
    stray = build_output({**plain_output(made), "schemes": plain_output(made)["schemes"][:1]}, ReadOpenapiOutput)
    assert verifier.verify_output("read_openapi", given, stray, str(tmp_path))["valid"] is False
    twice = plain_output(made)
    twice["operations"] = twice["operations"] * 2
    assert (
        verifier.verify_output("read_openapi", given, build_output(twice, ReadOpenapiOutput), str(tmp_path))["valid"]
        is False
    )
    retired = plain_output(made)
    retired["servers"] = [{**server, "deprecated": True} for server in retired["servers"]]
    assert (
        verifier.verify_output("read_openapi", given, build_output(retired, ReadOpenapiOutput), str(tmp_path))["valid"]
        is False
    )
    unknown_default = {**plain_output(made), "default_security": ["NoSuchScheme"]}
    unknown = build_output(unknown_default, ReadOpenapiOutput)
    assert verifier.verify_output("read_openapi", given, unknown, str(tmp_path))["valid"] is False


def test_probe_checks(tmp_path: Path) -> None:
    given = build_output({"document": DOC, "path": "/v1/regions", "method": "GET", "params": []}, ProbeInput)
    made = build_output(plain_output(probe(given, tmp_path)), ProbeOutput)
    assert verifier.verify_input("probe", given)["valid"] is True
    assert verifier.verify_output("probe", given, made, str(tmp_path))["valid"] is True
    relative = build_output({**plain_output(given), "path": "v1/regions"}, ProbeInput)
    assert verifier.verify_input("probe", relative)["valid"] is False
    twice = build_output({**plain_output(given), "params": [{"name": "a", "value": "1"}] * 2}, ProbeInput)
    assert verifier.verify_input("probe", twice)["valid"] is False
    assert verifier.verify_output("probe", given, ProbeOutput(body="{not json"), str(tmp_path))["valid"] is False


def test_write_spec_checks(tmp_path: Path) -> None:
    given = build_output({"spec": {**GOOD, "endpoints": [GOOD_ENDPOINT]}}, WriteSpecInput)
    made = build_output(plain_output(write_spec(given, tmp_path)), WriteSpecOutput)
    assert verifier.verify_input("write_spec", given)["valid"] is True
    assert verifier.verify_output("write_spec", given, made, str(tmp_path))["valid"] is True
    relative = build_output({"spec": {**GOOD, "endpoints": [{**GOOD_ENDPOINT, "path": "v1/regions"}]}}, WriteSpecInput)
    assert verifier.verify_input("write_spec", relative)["valid"] is False
    (tmp_path / SPEC).write_text(json.dumps({**GOOD, "endpoints": []}))
    assert verifier.verify_output("write_spec", given, made, str(tmp_path))["valid"] is False


def test_openapi_index_checks(tmp_path: Path) -> None:
    given = task("observations")
    made = index(given, tmp_path)
    assert verifier.verify_input("openapi_index", given)["valid"] is True
    assert verifier.verify_output("openapi_index", given, made, str(tmp_path))["valid"] is True
    undeclared = build_output({**plain_output(made), "required_path": "/v1/readings"}, OpenapiIndexOutput)
    assert verifier.verify_output("openapi_index", given, undeclared, str(tmp_path))["valid"] is False
    keyless = build_output({**plain_output(made), "auth_ref": None}, OpenapiIndexOutput)
    assert verifier.verify_output("openapi_index", given, keyless, str(tmp_path))["valid"] is False
