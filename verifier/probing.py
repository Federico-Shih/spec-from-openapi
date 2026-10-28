"""probe: one request to the mock API; its body is JSON."""

import json

from .checks import repeated, result


def verify_input(value):
    if not value.path.startswith("/"):
        return result(False, f"path {value.path!r} does not start with /")
    names = [param.name for param in value.params]
    if repeated(names):
        return result(False, "params repeat a name", names=repeated(names))
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    try:
        json.loads(output_value.body)
    except json.JSONDecodeError:
        return result(False, "the response body is not JSON")
    return result(True, f"{input_value.method.value} {input_value.path} answered")
