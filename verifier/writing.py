"""write_spec: spec.json holds exactly the spec written."""

import json
from pathlib import Path

from .checks import SPEC, plain_spec, result


def verify_input(value):
    strays = [endpoint.path for endpoint in value.spec.endpoints if not endpoint.path.startswith("/")]
    if strays:
        return result(False, "an endpoint path does not start with /", paths=strays)
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if output_value.path != SPEC or output_value.endpoints != len(input_value.spec.endpoints):
        return result(False, f"the output is not the written spec in {SPEC}")
    path = Path(workspace) / SPEC
    try:
        written = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        written = None
    if written != plain_spec(input_value.spec):
        return result(False, f"{SPEC} does not hold the spec written")
    return result(True, "the spec is written", endpoints=output_value.endpoints)
