"""Shared MCP connection config so every agent talks to the same server process."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client.stdio import get_default_environment
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The MCP SDK only forwards a curated "safe" env subset to the subprocess by
# default (PATH, HOME, etc.) -- not custom secrets. mcp_server/server.py is
# our own trusted code, so explicitly add the one extra var it needs.
EXTRA_ENV_VARS = ["DATA_GOV_API_KEY"]


def mcp_connection_params(timeout: float = 10.0) -> StdioConnectionParams:
    """Connection params for the local agro-advisor MCP server (mcp_server/server.py)."""
    env = get_default_environment()
    for key in EXTRA_ENV_VARS:
        value = os.environ.get(key)
        if value:
            env[key] = value

    return StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server"],
            cwd=str(PROJECT_ROOT),
            env=env,
        ),
        timeout=timeout,
    )
