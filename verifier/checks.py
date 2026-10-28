"""Checks shared by the tool verifiers. Pure functions of their arguments and the files on disk."""

import re

from contract import AuthKind, Method, PaginatorType

# This mirrors src/plugin/writing.py (the verifier may import only the standard library and the contract);
# tests/test_verifier.py holds them equal.
SPEC = "spec.json"
METHODS = frozenset(method.value for method in Method)
PAGINATORS = frozenset(kind.value for kind in PaginatorType)
AUTH_KINDS = frozenset(kind.value for kind in AuthKind)
# A credential ref is a NAME in UPPER_SNAKE_CASE, as host environment variables are. Anything else (lowercase,
# dashes, a leading digit, over 64 characters) may be a pasted key, and scores as a leak.
CREDENTIAL_NAME = re.compile(r"[A-Z][A-Z0-9_]{2,63}")
# The record selectors a spec may use: $ (the root), $.key or $.key.key..., each with an optional [*].
SELECTOR = re.compile(r"\$((?:\.[A-Za-z_][A-Za-z0-9_]*)*)(?:\[\*\])?")


def result(valid, message, *, score=None, **details):
    return {
        "valid": valid,
        "score": float(valid) if score is None else score,
        "message": message,
        "details": details,
    }


def select(body, selector):
    """(True, the value) that ``selector`` picks out of ``body``; (False, None) when it is bad or misses a key."""
    found = SELECTOR.fullmatch(selector)
    if not found:
        return False, None
    value = body
    for key in found.group(1).split(".")[1:]:
        if not isinstance(value, dict) or key not in value:
            return False, None
        value = value[key]
    return True, value


def selects_records(body, selector):
    """Whether ``selector`` picks a JSON array out of ``body``."""
    found, value = select(body, selector)
    return found and isinstance(value, list)


def plain_paginator(paginator):
    return {"type": paginator.type.value, "param": paginator.param, "cursor_path": paginator.cursor_path}


def plain_spec(spec):
    """A contract SourceSpec as the JSON write_spec writes."""
    return {
        "base_url": spec.base_url,
        "auth": spec.auth.value,
        "auth_ref": spec.auth_ref,
        "endpoints": [
            {
                "path": endpoint.path,
                "method": endpoint.method.value,
                "params": [{"name": param.name, "value": param.value} for param in endpoint.params],
                "record_selector": endpoint.record_selector,
                "paginator": plain_paginator(endpoint.paginator),
            }
            for endpoint in spec.endpoints
        ],
    }


def repeated(names):
    return sorted({name for name in names if names.count(name) > 1})
