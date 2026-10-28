"""The spec-from-openapi task: workspace/spec.json against the pinned openapi_index and the probes in the ledger."""

import json
from pathlib import Path

from .checks import (
    AUTH_KINDS,
    CREDENTIAL_NAME,
    METHODS,
    PAGINATORS,
    SPEC,
    plain_paginator,
    repeated,
    selects_records,
)
from .checks import result as verdict
from .ledger import read_calls

SPEC_KEYS = {"base_url", "auth", "auth_ref", "endpoints"}
ENDPOINT_KEYS = {"path", "method", "params", "record_selector", "paginator"}
PAGINATOR_KEYS = {"type", "param", "cursor_path"}
# Each endpoint's checks, in order; an endpoint's grade is the fraction it passes.
ENDPOINT_CHECKS = ("declared", "params_declared", "params_honoured", "paginator", "record_selector")
# The spec's parts; an invalid spec's score is their mean (at most 0.99), the endpoints part being the endpoints'
# mean grade.
PARTS = ("path", "base_url", "auth", "auth_ref", "required_endpoint", "endpoints")


def text_or_none(value):
    return value is None or isinstance(value, str)


def shape_problem(data):
    """Why ``data`` is not a SourceSpec as write_spec writes it, or None."""
    if not isinstance(data, dict) or set(data) != SPEC_KEYS:
        return f"{SPEC} is not {{base_url, auth, auth_ref, endpoints}}"
    if not isinstance(data["base_url"], str) or data["auth"] not in AUTH_KINDS or not text_or_none(data["auth_ref"]):
        return f"{SPEC} has a bad base_url, auth or auth_ref"
    if not isinstance(data["endpoints"], list):
        return f"{SPEC}'s endpoints is not a list"
    for endpoint in data["endpoints"]:
        if not isinstance(endpoint, dict) or set(endpoint) != ENDPOINT_KEYS:
            return f"{SPEC} holds an endpoint that is not {{path, method, params, record_selector, paginator}}"
        params, paginator = endpoint["params"], endpoint["paginator"]
        if not (
            isinstance(endpoint["path"], str)
            and endpoint["method"] in METHODS
            and isinstance(endpoint["record_selector"], str)
            and isinstance(params, list)
            and all(
                isinstance(param, dict)
                and set(param) == {"name", "value"}
                and isinstance(param["name"], str)
                and isinstance(param["value"], str)
                for param in params
            )
            and isinstance(paginator, dict)
            and set(paginator) == PAGINATOR_KEYS
            and paginator["type"] in PAGINATORS
            and text_or_none(paginator["param"])
            and text_or_none(paginator["cursor_path"])
        ):
            return f"{SPEC} holds a malformed endpoint: {endpoint.get('method')} {endpoint.get('path')}"
    return None


def read_spec(workspace):
    """(spec.json as parsed JSON, its text, None), or (None, "", the problem) when it is missing or not JSON."""
    path = Path(workspace) / SPEC
    if not path.is_file():
        return None, "", f"no {SPEC}: write_spec was never called"
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text), text, None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "", f"{SPEC} is not JSON"


def probed_bodies(calls, document):
    """{(path, method): [response bodies]} of every successful probe of ``document`` in the ledger."""
    bodies = {}
    for call in calls:
        given = call.get("input")
        if call.get("tool") != "probe" or "response" not in call or not isinstance(given, dict):
            continue
        if given.get("document") != document:
            continue
        response = call["response"]
        try:
            body = json.loads(response["body"]) if isinstance(response, dict) else None
        except (TypeError, KeyError, json.JSONDecodeError):
            continue
        bodies.setdefault((given.get("path"), given.get("method")), []).append(body)
    return bodies


def grade_endpoint(endpoint, facts, bodies):
    """{check: passed} for one endpoint of the spec; ``facts`` is its EndpointFacts, None when undeclared."""
    if facts is None:
        return dict.fromkeys(ENDPOINT_CHECKS, False)
    names = [param["name"] for param in endpoint["params"]]
    return {
        "declared": True,
        "params_declared": not repeated(names) and set(names) <= set(facts.declared_params),
        "params_honoured": set(names) <= set(facts.honoured_params),
        "paginator": endpoint["paginator"] == plain_paginator(facts.paginator),
        "record_selector": any(
            selects_records(body, endpoint["record_selector"])
            for body in bodies.get((endpoint["path"], endpoint["method"]), [])
        ),
    }


def check(id, constraint, ok, message="", expected=None, actual=None):
    """One entry of details.checks. ``ok`` None means not checked; ``message`` then names the check it waited on."""
    if ok is None:
        message = f"Not checked: {message} did not hold."
    elif ok:
        message = ""
    return {"id": id, "constraint": constraint, "ok": ok, "expected": expected, "actual": actual, "message": message}


def key_of(endpoint):
    return f"{endpoint['method']} {endpoint['path']}"


def per_endpoint(endpoints, grades, name, field):
    """(the failing endpoints' keys, {key: the endpoint's ``field``} for them) for endpoint check ``name``."""
    failing = [key_of(endpoint) for endpoint, grade in zip(endpoints, grades, strict=True) if not grade[name]]
    return failing, {key_of(endpoint): field(endpoint) for endpoint in endpoints if key_of(endpoint) in failing}


def integrity_checks(reference, spec, text, problem, ledger_problem, output_path):
    """The checks that guard the verdict's inputs: any that fails scores 0.0."""
    has_reference = reference is not None
    written = problem is None
    shape = shape_problem(spec) if written else None
    entries = [
        check(
            "reference",
            "The hidden openapi_index reference was pinned",
            has_reference,
            "no reference: openapi_index was not pinned",
        ),
        check("spec-written", f"write_spec wrote {SPEC} and it is JSON", written, problem),
        check(
            "spec-shape",
            f"{SPEC} is a SourceSpec as write_spec writes it",
            None if not written else shape is None,
            "spec-written" if not written else shape,
        ),
        check(
            "ledger",
            "The call ledger is well formed",
            ledger_problem is None,
            f"the call ledger is broken: {ledger_problem}",
        ),
    ]
    if not has_reference or not written or shape is not None:
        waited = "reference" if not has_reference else "spec-written" if not written else "spec-shape"
        entries.append(
            check(
                "no-leak",
                f"{SPEC} holds no key: auth_ref is a credential NAME and no example key appears",
                None,
                waited,
            )
        )
        return entries
    where = [
        field
        for field, leaked in (
            ("auth_ref", spec["auth_ref"] is not None and not CREDENTIAL_NAME.fullmatch(spec["auth_ref"])),
            ("the document's example key", any(key in text or key in output_path for key in reference.example_keys)),
        )
        if leaked
    ]
    entries.append(
        check(
            "no-leak",
            f"{SPEC} holds no key: auth_ref is a credential NAME and no example key appears",
            not where,
            f"{SPEC} holds a key, not a credential NAME ({', '.join(where)})",
        )
    )
    return entries


def outcome_checks(spec, output_path, reference, calls, document):
    """(the checks on what the spec says, its parts, its failed endpoints); ``calls`` is None when the ledger broke."""
    facts = {(item.path, item.method.value): item for item in reference.endpoints}
    endpoints = spec["endpoints"]
    bodies = probed_bodies(calls or [], document)
    grades = [
        grade_endpoint(endpoint, facts.get((endpoint["path"], endpoint["method"])), bodies) for endpoint in endpoints
    ]
    fractions = [sum(grade.values()) / len(ENDPOINT_CHECKS) for grade in grades]
    required = f"{reference.required_method.value} {reference.required_path}"
    keys = [key_of(endpoint) for endpoint in endpoints]
    parts = {
        "path": output_path == SPEC,
        "base_url": spec["base_url"] in reference.servers,
        "auth": spec["auth"] == reference.auth.value,
        "auth_ref": spec["auth_ref"] == reference.auth_ref,
        "required_endpoint": required in keys,
        "endpoints": sum(fractions) / len(fractions) if fractions else 0.0,
    }
    failed = {
        key: [name for name in ENDPOINT_CHECKS if not grade[name]]
        for key, grade in zip(keys, grades, strict=True)
        if not all(grade.values())
    }
    entries = [
        check(
            "submitted-path",
            f"The submitted path is {SPEC}",
            parts["path"],
            f"the submitted path is {output_path!r}, not {SPEC}",
            SPEC,
            output_path,
        ),
        check(
            "base-url",
            "base_url is a declared server that is not deprecated",
            parts["base_url"],
            f"base_url {spec['base_url']} is not a declared, current server",
            reference.servers,
            spec["base_url"],
        ),
        check(
            "auth",
            "auth is the kind of the goal endpoint's own security scheme",
            parts["auth"],
            f"auth is {spec['auth']}, but {required} uses {reference.auth.value}",
            reference.auth.value,
            spec["auth"],
        ),
        check(
            "auth-ref",
            "auth_ref is the credential NAME of the goal endpoint's scheme",
            parts["auth_ref"],
            f"auth_ref is {spec['auth_ref']}, but {required} needs {reference.auth_ref}",
            reference.auth_ref,
            spec["auth_ref"],
        ),
        check(
            "has-endpoints",
            "The spec has at least one endpoint",
            bool(endpoints),
            f"{SPEC} has no endpoints",
            "at least one endpoint",
            len(endpoints),
        ),
        check(
            "goal-endpoint",
            "The goal's endpoint is in the spec",
            parts["required_endpoint"],
            f"the spec has no {required}",
            required,
            keys,
        ),
    ]
    undeclared = [key for key, grade in zip(keys, grades, strict=True) if not grade["declared"]]
    entries.append(
        check("endpoints-declared", "Every endpoint's path and method is a declared operation", None, "has-endpoints")
        if not endpoints
        else check(
            "endpoints-declared",
            "Every endpoint's path and method is a declared operation",
            not undeclared,
            f"{', '.join(undeclared)} {'is' if len(undeclared) == 1 else 'are'} not declared by the document",
            None,
            undeclared or None,
        )
    )
    # The other endpoint checks judge the declared endpoints; an undeclared one already scores 0 in the parts.
    declared = [(endpoint, grade) for endpoint, grade in zip(endpoints, grades, strict=True) if grade["declared"]]
    shown, shown_grades = [endpoint for endpoint, _ in declared], [grade for _, grade in declared]

    def facts_of(endpoint):
        return facts[(endpoint["path"], endpoint["method"])]

    def names(endpoint):
        return [param["name"] for param in endpoint["params"]]

    specs = (
        (
            "params-declared",
            "Every endpoint sends only params the document declares, none repeated",
            "params_declared",
            lambda e: facts_of(e).declared_params,
            names,
            "sends params the document does not declare, or repeats one",
        ),
        (
            "params-honoured",
            "Every endpoint sends only params the API honours",
            "params_honoured",
            lambda e: facts_of(e).honoured_params,
            names,
            "sends params the API ignores",
        ),
        (
            "paginator",
            "Every endpoint has the API's real paginator",
            "paginator",
            lambda e: plain_paginator(facts_of(e).paginator),
            lambda e: e["paginator"],
            "has the wrong paginator",
        ),
        (
            "record-selector",
            "Every endpoint's record_selector picks an array out of a probe of it in the ledger",
            "record_selector",
            None,
            lambda e: e["record_selector"],
            "has a record_selector no probe of it bears out",
        ),
    )
    for id, constraint, name, want, have, problem in specs:
        if not endpoints or not shown:
            entries.append(check(id, constraint, None, "has-endpoints" if not endpoints else "endpoints-declared"))
            continue
        if name == "record_selector" and calls is None:
            entries.append(check(id, constraint, None, "ledger"))
            continue
        failing, actual = per_endpoint(shown, shown_grades, name, have)
        expected = None if want is None else {key_of(e): want(e) for e in shown if key_of(e) in failing}
        entries.append(
            check(id, constraint, not failing, f"{', '.join(failing)} {problem}", expected or None, actual or None)
        )
    return entries, parts, failed


def verify_task(arguments, output, reference, workspace):
    """``output``: a contract SpecOutput; ``reference``: the pinned OpenapiIndexOutput.

    details.checks lists every check in order (see the README's Checks table). Valid only when all hold, and then the
    score is 1.0. Any integrity check failing (reference, spec-written, spec-shape, ledger, no-leak) scores 0.0.
    Otherwise score = the mean of the six parts (path, base_url, auth, auth_ref, required_endpoint, and endpoints,
    the endpoints' mean fraction of their five checks), at most 0.99.
    """
    spec, text, problem = read_spec(workspace)
    try:
        calls, ledger_problem = read_calls(workspace), None
    except ValueError as error:
        calls, ledger_problem = None, str(error)
    entries = integrity_checks(reference, spec, text, problem, ledger_problem, output.path)
    intact = all(entry["ok"] for entry in entries)
    details = {"leak": next(entry for entry in entries if entry["id"] == "no-leak")["ok"] is False}
    if reference is not None and problem is None and entries[2]["ok"]:
        outcomes, parts, failed = outcome_checks(spec, output.path, reference, calls, arguments.document.value)
        entries += outcomes
        details |= {"parts": parts, "failed_endpoints": failed}
    failing = [entry for entry in entries if entry["ok"] is False]
    if all(entry["ok"] for entry in entries):
        required = f"{reference.required_method.value} {reference.required_path}"
        return verdict(
            True, f"the spec reads {required} as the document and probes say", score=1.0, checks=entries, **details
        )
    if not intact:
        score = 0.0
    else:
        score = min(0.99, round(sum(float(details["parts"][part]) for part in PARTS) / len(PARTS), 4))
    message = f"{failing[0]['id']}: {failing[0]['message']}" + (
        f" (+{len(failing) - 1} more)" if len(failing) > 1 else ""
    )
    return verdict(False, message, score=score, checks=entries, **details)
