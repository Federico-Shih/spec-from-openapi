from __future__ import annotations

import json
from pathlib import Path

from slimconfig import plain_output

from contract import WriteSpecInput, WriteSpecOutput

# The spec the agent writes, relative to the workspace: a SourceSpec as JSON.
SPEC = "spec.json"


def write_spec(given: WriteSpecInput, workspace: Path) -> WriteSpecOutput:
    """Write the spec to spec.json, replacing any spec written before. It is checked only when the task ends."""
    (workspace / SPEC).write_text(json.dumps(plain_output(given.spec), indent=2) + "\n", encoding="utf-8")
    return WriteSpecOutput(path=SPEC, endpoints=len(given.spec.endpoints))
