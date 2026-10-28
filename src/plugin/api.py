"""The bundled OpenAPI documents (fixtures/<document>.json), their mock APIs (fixtures/records.json) and the hidden
facts of how each mock really serves its endpoints."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from contract import (
    AuthKind,
    DeclaredParam,
    Document,
    Goal,
    Method,
    Operation,
    Paginator,
    PaginatorType,
    ReadOpenapiOutput,
    SecurityScheme,
    Server,
)
from plugin.engine import page

FIXTURES = Path(__file__).with_name("fixtures")
RECORDS = FIXTURES / "records.json"
PAGE_SIZE = 5  # observations per response, whatever limit asks
STATIONS_PER_PAGE = 4
ALERTS_LIMIT = 5


def paginator(kind: PaginatorType, param: str | None = None, cursor_path: str | None = None) -> Paginator:
    return Paginator(type=kind, param=param, cursor_path=cursor_path)


# What the document leaves out or gets wrong, the agent can only learn by probing. Per (path, method): the params
# the mock acts on (observations honours an undeclared cursor and ignores its declared limit; alerts ignores its
# declared page) and how it really pages (observations' cursor shows only in a response body).
HONOURED: dict[Document, dict[tuple[str, Method], tuple[frozenset[str], Paginator]]] = {
    Document.AQUA_METRICS: {
        ("/v1/observations", Method.GET): (
            frozenset({"station_id", "since", "cursor"}),
            paginator(PaginatorType.CURSOR, "cursor", "$.next_cursor"),
        ),
        ("/v1/stations", Method.GET): (
            frozenset({"country", "page", "per_page"}),
            paginator(PaginatorType.PAGE, "page"),
        ),
        ("/v1/stations", Method.POST): (frozenset(), paginator(PaginatorType.NONE)),
        ("/v1/alerts", Method.GET): (
            frozenset({"severity", "offset", "limit"}),
            paginator(PaginatorType.OFFSET, "offset"),
        ),
        ("/v1/regions", Method.GET): (frozenset(), paginator(PaginatorType.NONE)),
        ("/v1/status", Method.GET): (frozenset(), paginator(PaginatorType.NONE)),
    }
}
GOALS = {
    Goal.OBSERVATIONS: ("/v1/observations", Method.GET),
    Goal.STATIONS: ("/v1/stations", Method.GET),
    Goal.ALERTS: ("/v1/alerts", Method.GET),
    Goal.REGIONS: ("/v1/regions", Method.GET),
}
# Key-like example values a document shows; a spec holding one leaks it.
EXAMPLE_KEYS = {Document.AQUA_METRICS: ("amk_live_4f9c2e7a1b8d3c6e5f0a",)}
SCHEME_AUTH = {("apiKey", "header"): AuthKind.API_KEY_HEADER, ("apiKey", "query"): AuthKind.API_KEY_QUERY}
HTTP_AUTH = {"bearer": AuthKind.BEARER, "basic": AuthKind.BASIC}


@cache
def raw(document: Document) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{document.value}.json").read_text(encoding="utf-8"))


@cache
def records() -> dict[str, list[dict[str, Any]]]:
    return json.loads(RECORDS.read_text(encoding="utf-8"))


def response_shape(operation: dict[str, Any]) -> tuple[str, list[str]]:
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    return schema["type"], sorted(schema.get("properties", {})) if schema["type"] == "object" else []


@cache
def read(document: Document) -> ReadOpenapiOutput:
    """The document, typed, as it is written: its servers, its default security, every operation with its declared
    params and its own security (None when it declares none), every scheme."""
    spec = raw(document)
    default_security = [name for item in spec.get("security", []) for name in item]
    operations = []
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            response_type, response_fields = response_shape(operation)
            security = operation.get("security")
            operations.append(
                Operation(
                    path=path,
                    method=Method(method.upper()),
                    summary=operation.get("summary", ""),
                    params=[
                        DeclaredParam(
                            name=param["name"],
                            location=param["in"],
                            required=bool(param.get("required", False)),
                            description=param.get("description", ""),
                        )
                        for param in operation.get("parameters", [])
                    ],
                    security=None if security is None else [name for item in security for name in item],
                    response_type=response_type,
                    response_fields=response_fields,
                )
            )
    schemes = [
        SecurityScheme(
            name=name,
            type=scheme["type"],
            location=scheme.get("in"),
            param_name=scheme.get("name"),
            scheme=scheme.get("scheme"),
            credential_ref=scheme["x-credential-ref"],
            description=scheme.get("description", ""),
        )
        for name, scheme in spec["components"]["securitySchemes"].items()
    ]
    return ReadOpenapiOutput(
        title=spec["info"]["title"],
        servers=[
            Server(
                url=server["url"],
                description=server.get("description", ""),
                deprecated=bool(server.get("x-deprecated", False)),
            )
            for server in spec["servers"]
        ],
        default_security=default_security,
        operations=operations,
        schemes=schemes,
    )


def operation(document: Document, path: str, method: Method) -> Operation:
    for declared in read(document).operations:
        if (declared.path, declared.method) == (path, method):
            return declared
    raise LookupError(f"{method.value} {path} is not declared in the {document.value} document")


def auth_of(document: Document, declared: Operation) -> tuple[AuthKind, str | None]:
    """How ``declared`` authenticates: the first scheme of its own security, or of the document's default when it
    declares none, as a kind and a credential ref; or none."""
    security = read(document).default_security if declared.security is None else declared.security
    if not security:
        return AuthKind.NONE, None
    scheme = next(item for item in read(document).schemes if item.name == security[0])
    kind = SCHEME_AUTH.get((scheme.type, scheme.location or "")) or HTTP_AUTH.get(scheme.scheme or "")
    if kind is None:
        raise ValueError(f"scheme {scheme.name!r} has no auth kind")
    return kind, scheme.credential_ref


def number(params: dict[str, str], name: str, default: int, low: int, high: int) -> int:
    text = params.get(name, str(default))
    if not text.isdigit() or not low <= int(text) <= high:
        raise ValueError(f"{name} must be a whole number from {low} to {high}, not {text!r}")
    return int(text)


def serve(document: Document, path: str, method: Method, params: dict[str, str]) -> Any:
    """The mock API's response body for one request; an undeclared operation or a bad value raises."""
    operation(document, path, method)
    data = records()
    if (path, method) == ("/v1/observations", Method.GET):
        if "station_id" not in params:
            raise ValueError("station_id is required")
        rows = [
            row
            for row in data["observations"]
            if row["station_id"] == params["station_id"] and row["observed_on"] >= params.get("since", "")
        ]
        page_rows, next_cursor = page(rows, params.get("cursor"), PAGE_SIZE)
        return {"data": {"items": page_rows, "count": len(page_rows)}, "next_cursor": next_cursor}
    if (path, method) == ("/v1/stations", Method.GET):
        rows = [row for row in data["stations"] if row["country"] == params.get("country", row["country"])]
        size = number(params, "per_page", STATIONS_PER_PAGE, 1, 50)
        pages = max(1, -(-len(rows) // size))
        at = number(params, "page", 1, 1, 10_000)
        return {"results": rows[(at - 1) * size : at * size], "page": at, "total_pages": pages}
    if (path, method) == ("/v1/stations", Method.POST):
        return {"station": {"id": "ST-010", "name": "New station", "country": "NO", "region": "west"}}
    if (path, method) == ("/v1/alerts", Method.GET):
        rows = [row for row in data["alerts"] if row["severity"] == params.get("severity", row["severity"])]
        offset = number(params, "offset", 0, 0, 10_000)
        limit = number(params, "limit", ALERTS_LIMIT, 1, 20)
        return {"items": rows[offset : offset + limit], "offset": offset, "limit": limit, "total": len(rows)}
    if (path, method) == ("/v1/regions", Method.GET):
        return data["regions"]
    return {"status": "ok", "version": raw(document)["info"]["version"]}
