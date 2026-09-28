"""The four mcp-doctor checks: schema, launch, handshake, tools/list."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import proc as proc_mod
from .proc import McpError, McpProcess
from .schema import validate_config

PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "mcp-doctor"
CLIENT_VERSION = "0.1.0"
HANDSHAKE_TIMEOUT = 10.0


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: List[str]


def check_schema(config_path: str) -> CheckResult:
    """Check 1: config parses as JSON and matches the expected schema."""
    details: List[str] = []
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return CheckResult("config schema", False, [f"file not found: {config_path}"])
    except json.JSONDecodeError as exc:
        return CheckResult("config schema", False, [f"invalid JSON: {exc}"])
    except OSError as exc:
        return CheckResult("config schema", False, [f"cannot read file: {exc}"])

    result = validate_config(data)
    for warning in result.warnings:
        details.append(f"warning: {warning}")
    if result.ok:
        details.append(f"found {len(result.servers)} server(s): "
                       + ", ".join(sorted(result.servers)))
    else:
        details.extend(result.errors)
    return CheckResult("config schema", result.ok, details)


def check_launch(name: str, entry: Dict[str, Any]) -> "_LaunchOutcome":
    """Check 2: the server command exists and launches without dying.

    The launched process is carried in the returned outcome so the caller can
    keep using it for the handshake. On failure the process is cleaned up and
    the outcome has ``process`` set to None.
    """
    try:
        mcp = proc_mod.launch(entry)
    except McpError as exc:
        return _LaunchOutcome(
            result=CheckResult(f"launch '{name}'", False, [str(exc)]),
            process=None,
        )
    command = entry["command"]
    # Absolute paths (e.g. sys.executable) are noisy in reports; show the base.
    cmd_display = os.path.basename(command) if os.path.isabs(command) else command
    detail = (f"launched pid={mcp.process.pid}: "
              f"{cmd_display} {' '.join(entry.get('args', []))}".rstrip())
    return _LaunchOutcome(result=CheckResult(f"launch '{name}'", True, [detail]),
                          process=mcp)


@dataclass
class _LaunchOutcome:
    result: CheckResult
    process: Optional[McpProcess]


def check_handshake(mcp: McpProcess, name: str) -> CheckResult:
    """Check 3: JSON-RPC initialize handshake over stdio."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        },
    }
    try:
        mcp.send(request)
        response = mcp.recv(HANDSHAKE_TIMEOUT)
    except McpError as exc:
        return CheckResult(f"handshake '{name}'", False, [str(exc)])

    if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
        return CheckResult(f"handshake '{name}'", False,
                           [f"response is not a JSON-RPC 2.0 object: {response!r}"])
    if "error" in response:
        return CheckResult(f"handshake '{name}'", False,
                           [f"server returned error: {response['error']}"])
    result = response.get("result")
    if not isinstance(result, dict):
        return CheckResult(f"handshake '{name}'", False,
                           ["response has no 'result' object"])
    server_info = result.get("serverInfo")
    if not isinstance(server_info, dict):
        return CheckResult(f"handshake '{name}'", False,
                           ["'result' has no 'serverInfo' object"])
    details = [f"server: {server_info.get('name', '?')} "
               f"{server_info.get('version', '')}".rstrip()]
    if "protocolVersion" in result:
        details.append(f"protocol version: {result['protocolVersion']}")
    return CheckResult(f"handshake '{name}'", True, details)


def check_tools(mcp: McpProcess, name: str) -> CheckResult:
    """Check 4: send notifications/initialized, then tools/list."""
    try:
        mcp.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        mcp.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        response = mcp.recv(HANDSHAKE_TIMEOUT)
    except McpError as exc:
        return CheckResult(f"tools/list '{name}'", False, [str(exc)])

    if "error" in response:
        return CheckResult(f"tools/list '{name}'", False,
                           [f"server returned error: {response['error']}"])
    result = response.get("result") or {}
    tools = result.get("tools")
    if not isinstance(tools, list):
        return CheckResult(f"tools/list '{name}'", False,
                           ["'result.tools' is missing or not a list"])
    details: List[str] = []
    for tool in tools:
        if isinstance(tool, dict) and "name" in tool:
            desc = tool.get("description") or "(no description)"
            details.append(f"- {tool['name']}: {desc}")
        else:
            details.append(f"- (malformed tool entry: {tool!r})")
    if not details:
        details.append("(server exposes no tools)")
    return CheckResult(f"tools/list '{name}'", True, details)


def run_server_checks(name: str, entry: Dict[str, Any],
                      print_fn=print) -> bool:
    """Run checks 2-4 for one server entry. Returns True if all passed."""
    outcome = check_launch(name, entry)
    _print_result(outcome.result, print_fn)
    if not outcome.result.passed:
        return False
    mcp = outcome.process
    assert mcp is not None
    try:
        handshake = check_handshake(mcp, name)
        _print_result(handshake, print_fn)
        if not handshake.passed:
            return False
        tools = check_tools(mcp, name)
        _print_result(tools, print_fn)
        return tools.passed
    finally:
        mcp.close()


def _print_result(result: CheckResult, print_fn) -> None:
    status = "PASS" if result.passed else "FAIL"
    print_fn(f"[{status}] {result.name}")
    for detail in result.details:
        print_fn(f"       {detail}")
