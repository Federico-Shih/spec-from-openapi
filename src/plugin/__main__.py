"""The MCP server: each call's input built into its contract class, its output checked against its own."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from slimconfig import build_output, output_schema, plain_output

from contract import TOOLS, Tool
from plugin import openapi_index, probe, read_openapi, write_spec
from plugin.engine import session_for

server = Server("spec-from-openapi")
# NanoAgent names the one folder this plugin may write to.
WORKSPACE_ENV = "NANOAGENT_WORKSPACE"
# Each tool's implementation: (its input, the workspace) -> its output, as contract.TOOLS types them.
IMPLEMENTATIONS = {
    Tool.READ_OPENAPI: read_openapi,
    Tool.PROBE: probe,
    Tool.WRITE_SPEC: write_spec,
    Tool.OPENAPI_INDEX: openapi_index,
}


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(name=tool.value, inputSchema=output_schema(given), outputSchema=output_schema(made))
        for tool, (given, made) in TOOLS.items()
    ]


def run_call(name: str, arguments: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """One tool call, as the server runs it: recorded in the ledger the verifier reads (plugin.engine.LEDGER),
    failed calls too: the verifier finds each endpoint's probed responses there. A failure raises."""
    tool = Tool(name)
    given, made = TOOLS[tool]
    session = session_for(workspace)
    session.begin()
    try:
        output = IMPLEMENTATIONS[tool](build_output(arguments, given), session.workspace)
        if not isinstance(output, made):
            raise TypeError(f"{name} returned {type(output).__name__}, not {made.__name__}")
    except Exception as error:
        session.finish(name, arguments, error=f"{type(error).__name__}: {error}")
        raise
    response = plain_output(output)
    session.finish(name, arguments, response=response)
    return response


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    # A failure raises; the MCP server returns it as an error result.
    return run_call(name, arguments, Path(os.environ[WORKSPACE_ENV]))


def main() -> None:
    if WORKSPACE_ENV not in os.environ:
        raise SystemExit(f"{WORKSPACE_ENV} is not set: NanoAgent passes the plugin's workspace folder")
    if set(IMPLEMENTATIONS) != set(Tool):
        raise SystemExit("IMPLEMENTATIONS must implement every contract.Tool")

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)


if __name__ == "__main__":
    main()
