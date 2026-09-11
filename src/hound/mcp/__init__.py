"""Hound Tracer Model Context Protocol (MCP) server package."""
from __future__ import annotations

from hound.mcp.server import PROTOCOL_VERSION, TOOL_DEFINITIONS, MCPServer, run_server
from hound.mcp.tools import (
    tool_analyze,
    tool_check_gate,
    tool_doctor,
    tool_get_insights,
    tool_list_incidents,
    tool_log_command,
)

__all__ = [
    "PROTOCOL_VERSION",
    "TOOL_DEFINITIONS",
    "MCPServer",
    "run_server",
    "tool_analyze",
    "tool_check_gate",
    "tool_doctor",
    "tool_get_insights",
    "tool_list_incidents",
    "tool_log_command",
]
