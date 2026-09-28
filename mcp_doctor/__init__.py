"""mcp-doctor: validate MCP (Model Context Protocol) server setups.

Checks a config file's schema, that each server command launches, and that
the JSON-RPC 2.0 stdio handshake (initialize + tools/list) succeeds.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
