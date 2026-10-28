"""openapi_index, the reference tool: the goal's endpoint is declared and its auth is a credential NAME."""

from .checks import CREDENTIAL_NAME, repeated, result


def verify_input(value):
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    keys = [(facts.path, facts.method) for facts in output_value.endpoints]
    if repeated([f"{method.value} {path}" for path, method in keys]):
        return result(False, "the index repeats an operation")
    if (output_value.required_path, output_value.required_method) not in keys:
        return result(False, "the goal's endpoint is not declared")
    if (output_value.auth.value == "none") != (output_value.auth_ref is None):
        return result(False, "auth and auth_ref disagree")
    if output_value.auth_ref is not None and not CREDENTIAL_NAME.fullmatch(output_value.auth_ref):
        return result(False, "auth_ref is not a credential NAME")
    return result(True, f"{len(keys)} declared operations")
