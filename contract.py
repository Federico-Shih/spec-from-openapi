"""Each tool's and task's typed input and output (see nanoagent.plugin.v0001.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    READ_OPENAPI = "read_openapi"
    PROBE = "probe"
    WRITE_SPEC = "write_spec"
    OPENAPI_INDEX = "openapi_index"


class Task(Enum):
    SPEC_FROM_OPENAPI = "spec-from-openapi"


class Document(Enum):
    """The OpenAPI documents bundled in src/plugin/fixtures/, each served by an in-process mock API."""

    AQUA_METRICS = "aqua-metrics"


class Goal(Enum):
    """The records the spec must read; each is one endpoint of the document."""

    OBSERVATIONS = "observations"
    STATIONS = "stations"
    ALERTS = "alerts"
    REGIONS = "regions"


class Method(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class PaginatorType(Enum):
    """How an endpoint pages: an offset, a page number, a cursor from the body, or a single response."""

    OFFSET = "offset"
    PAGE = "page"
    CURSOR = "cursor"
    NONE = "none"


class AuthKind(Enum):
    """How requests authenticate; mirrors the auth values of Empiric's SourceSpec (src/empiric/contracts/sources.py)."""

    NONE = "none"
    API_KEY_HEADER = "api_key_header"
    API_KEY_QUERY = "api_key_query"
    BEARER = "bearer"
    BASIC = "basic"
    OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"
    OAUTH2_REFRESH_TOKEN = "oauth2_refresh_token"


PATH = "The endpoint's path exactly as the document declares it, e.g. /v1/stations"
METHOD = "The HTTP method: GET, POST, PUT, PATCH or DELETE"


@dataclass
class Param(Output):
    name: Annotated[str, "The query parameter's name"]
    value: Annotated[str, "Its value, as text"]


@dataclass
class Paginator(Output):
    type: Annotated[PaginatorType, "How the endpoint pages: offset, page, cursor or none"]
    param: Annotated[str | None, "The query parameter that moves to the next page; null when type is none"]
    cursor_path: Annotated[str | None, "Where the next cursor sits in the response body, e.g. $.next; cursor only"]


@dataclass
class Endpoint(Output):
    path: Annotated[str, PATH]
    method: Annotated[Method, METHOD]
    params: Annotated[list[Param], "Fixed query parameters sent on every request; the paginator's are not listed"]
    record_selector: Annotated[
        str, "A JSONPath to the response's array of records: $, $.key or $.key.key, [*] optional"
    ]
    paginator: Annotated[Paginator, "How to fetch the next page"]


@dataclass
class SourceSpec(Output):
    """The REST part of Empiric's SourceSpec (src/empiric/contracts/sources.py)."""

    base_url: Annotated[str, "The API's base URL: one of the document's servers"]
    auth: Annotated[AuthKind, "How requests authenticate"]
    auth_ref: Annotated[
        str | None, "The NAME of the credential that holds the key, never the key; null when auth is none"
    ]
    endpoints: Annotated[list[Endpoint], "The endpoints to read"]


@dataclass
class SpecInput(Output):
    document: Annotated[Document, "The OpenAPI document to read"]
    goal: Annotated[Goal, "Which records the spec must read"]


@dataclass
class SpecOutput(Output):
    path: Annotated[str, "The spec file write_spec wrote, relative to the workspace: spec.json"]


@dataclass
class DeclaredParam(Output):
    name: Annotated[str, "The parameter's name"]
    location: Annotated[str, "Where it goes: query, header or path"]
    required: Annotated[bool, "Whether the document requires it"]
    description: Annotated[str, "What the document says it does"]


@dataclass
class Operation(Output):
    path: Annotated[str, PATH]
    method: Annotated[Method, METHOD]
    summary: Annotated[str, "What the document says the operation does"]
    params: Annotated[list[DeclaredParam], "The parameters the document declares for it"]
    security: Annotated[
        list[str] | None,
        "The security schemes the operation itself declares, by name: empty when it needs none, null when it declares"
        " none of its own and the document's default_security applies",
    ]
    response_type: Annotated[str, "The declared 200 response body's JSON type: object or array"]
    response_fields: Annotated[list[str], "The declared top-level fields of an object response; empty for an array"]


@dataclass
class SecurityScheme(Output):
    name: Annotated[str, "The scheme's name in the document"]
    type: Annotated[str, "Its OpenAPI type: apiKey, http, oauth2 or openIdConnect"]
    location: Annotated[str | None, "Where an apiKey goes: header, query or cookie; null for other types"]
    param_name: Annotated[str | None, "The header or query parameter an apiKey goes in; null for other types"]
    scheme: Annotated[str | None, "The http scheme, bearer or basic; null for other types"]
    credential_ref: Annotated[str, "The host-side credential's NAME (x-credential-ref), never a key"]
    description: Annotated[str, "What the document says about it"]


@dataclass
class ReadOpenapiInput(Output):
    document: Annotated[Document, "The OpenAPI document to read: the task's document"]


@dataclass
class Server(Output):
    url: Annotated[str, "The server's base URL"]
    description: Annotated[str, "What the document says about the server"]
    deprecated: Annotated[bool, "Whether the document marks the server deprecated (x-deprecated)"]


@dataclass
class ReadOpenapiOutput(Output):
    title: Annotated[str, "The API's title"]
    servers: Annotated[list[Server], "The servers the document declares, in document order"]
    default_security: Annotated[
        list[str], "The security schemes, by name, of every operation that declares none of its own"
    ]
    operations: Annotated[list[Operation], "Every declared operation, in document order"]
    schemes: Annotated[list[SecurityScheme], "Every declared security scheme"]


@dataclass
class ProbeInput(Output):
    document: Annotated[Document, "The API to probe: the task's document"]
    path: Annotated[str, PATH]
    method: Annotated[Method, METHOD]
    params: Annotated[list[Param], "Query parameters to send, each name once; the API ignores ones it does not honour"]


@dataclass
class ProbeOutput(Output):
    body: Annotated[str, "The response body, as JSON text"]


@dataclass
class WriteSpecInput(Output):
    spec: Annotated[SourceSpec, "The spec to write; it replaces any spec written before"]


@dataclass
class WriteSpecOutput(Output):
    path: Annotated[str, "The spec file, relative to the workspace: spec.json"]
    endpoints: Annotated[int, "How many endpoints it holds"]


@dataclass
class EndpointFacts(Output):
    path: Annotated[str, PATH]
    method: Annotated[Method, METHOD]
    declared_params: Annotated[list[str], "The parameter names the document declares"]
    honoured_params: Annotated[list[str], "The parameter names the mock API acts on"]
    paginator: Annotated[Paginator, "How the mock API really pages"]


@dataclass
class OpenapiIndexOutput(Output):
    servers: Annotated[list[str], "The declared base URLs that are not deprecated: what a spec's base_url may be"]
    endpoints: Annotated[list[EndpointFacts], "Every declared operation and how the mock API serves it"]
    required_path: Annotated[str, "The path of the goal's endpoint"]
    required_method: Annotated[Method, "The method of the goal's endpoint"]
    auth: Annotated[AuthKind, "How the goal's endpoint authenticates"]
    auth_ref: Annotated[str | None, "The credential NAME of the goal's endpoint's scheme; null when it needs none"]
    example_keys: Annotated[list[str], "Key-like example values the document shows, which a spec must never hold"]


TOOLS = {
    Tool.READ_OPENAPI: (ReadOpenapiInput, ReadOpenapiOutput),
    Tool.PROBE: (ProbeInput, ProbeOutput),
    Tool.WRITE_SPEC: (WriteSpecInput, WriteSpecOutput),
    Tool.OPENAPI_INDEX: (SpecInput, OpenapiIndexOutput),
}
TASKS = {Task.SPEC_FROM_OPENAPI: (SpecInput, SpecOutput)}
