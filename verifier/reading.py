"""read_openapi: the typed document, every operation once, every security it names (its own or the default)
declared, and at least one server that is not deprecated."""

from .checks import CREDENTIAL_NAME, repeated, result


def verify_input(value):
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    keys = [f"{operation.method.value} {operation.path}" for operation in output_value.operations]
    if not any(not server.deprecated for server in output_value.servers) or not keys:
        return result(False, "the document declares no usable server or no operation")
    if repeated(keys):
        return result(False, "the document repeats an operation", operations=repeated(keys))
    names = {scheme.name for scheme in output_value.schemes}
    named = {name for operation in output_value.operations for name in operation.security or []}
    unknown = sorted((named | set(output_value.default_security)) - names)
    if unknown:
        return result(False, "an operation names an undeclared security scheme", schemes=unknown)
    if not all(CREDENTIAL_NAME.fullmatch(scheme.credential_ref) for scheme in output_value.schemes):
        return result(False, "a scheme's credential_ref is not a credential NAME")
    return result(True, f"{len(keys)} operations, {len(names)} security schemes")
