"""Config-file schema validation for mcp-doctor.

An mcp.json file must look like::

    {
        "mcpServers": {
            "my-server": {
                "command": "npx",
                "args": ["-y", "some-mcp-server"],
                "env": {"API_KEY": "secret"}
            }
        }
    }

Only ``mcpServers`` is recognized at the top level. Each server entry needs
``command`` (string); ``args`` (list of strings) and ``env`` (map of
string->string) are optional. Anything else is reported as a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ValidationResult:
    """Outcome of validating one config file."""

    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    servers: Dict[str, Dict[str, Any]] = field(default_factory=dict)


_TOP_LEVEL_KNOWN = {"mcpServers"}
_SERVER_KNOWN = {"command", "args", "env"}


def _is_str_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    )


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_config(data: Any) -> ValidationResult:
    """Validate decoded JSON config data; return errors and warnings."""
    errors: List[str] = []
    warnings: List[str] = []
    servers: Dict[str, Dict[str, Any]] = {}

    if not isinstance(data, dict):
        return ValidationResult(
            ok=False, errors=["top-level JSON must be an object, "
                             f"got {type(data).__name__}"]
        )

    for key in data:
        if key not in _TOP_LEVEL_KNOWN:
            warnings.append(f"unknown top-level field {key!r} (ignored)")

    raw_servers = data.get("mcpServers")
    if not isinstance(raw_servers, dict):
        return ValidationResult(
            ok=False,
            errors=["missing or invalid 'mcpServers': expected an object "
                    f"mapping names to server entries, got "
                    f"{type(raw_servers).__name__}"],
            warnings=warnings,
        )

    if not raw_servers:
        errors.append("'mcpServers' is empty: nothing to check")

    for name, entry in raw_servers.items():
        entry_errors: List[str] = []
        if not isinstance(entry, dict):
            errors.append(f"server {name!r}: entry must be an object, "
                          f"got {type(entry).__name__}")
            continue
        for key in entry:
            if key not in _SERVER_KNOWN:
                warnings.append(
                    f"server {name!r}: unknown field {key!r} (ignored)")
        command = entry.get("command")
        if not isinstance(command, str) or not command:
            entry_errors.append(f"server {name!r}: 'command' must be a non-empty "
                                f"string, got {command!r}")
        args = entry.get("args", [])
        if not _is_str_list(args):
            entry_errors.append(f"server {name!r}: 'args' must be a list of strings, "
                                f"got {args!r}")
        env = entry.get("env", {})
        if not _is_str_map(env):
            entry_errors.append(f"server {name!r}: 'env' must be a map of "
                                f"string->string, got {env!r}")
        errors.extend(entry_errors)
        if not entry_errors:
            servers[name] = {"command": command, "args": args, "env": env}

    return ValidationResult(
        ok=not errors, errors=errors, warnings=warnings, servers=servers
    )
