from __future__ import annotations

import json
from pathlib import Path

from contract import ProbeInput, ProbeOutput
from plugin.api import serve


def probe(given: ProbeInput, workspace: Path) -> ProbeOutput:
    """One request to the document's mock API; an undeclared path or method, a repeated param or a bad value raises.
    The API ignores params it does not honour, as real APIs do."""
    names = [param.name for param in given.params]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValueError(f"params repeat {', '.join(repeated)}; send each once")
    body = serve(given.document, given.path, given.method, {param.name: param.value for param in given.params})
    return ProbeOutput(body=json.dumps(body, sort_keys=True))
