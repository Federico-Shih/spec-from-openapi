from __future__ import annotations

from pathlib import Path

from contract import ReadOpenapiInput, ReadOpenapiOutput
from plugin.api import read


def read_openapi(given: ReadOpenapiInput, workspace: Path) -> ReadOpenapiOutput:
    """The task's OpenAPI document, typed: servers, operations with their declared params and security, schemes."""
    return read(given.document)
