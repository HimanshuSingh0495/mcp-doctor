"""Command-line interface for mcp-doctor."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from .checks import check_schema, run_server_checks
from .schema import validate_config


def cmd_check(config_path: str) -> int:
    """Run all four checks against every server in the config file."""
    schema_result = check_schema(config_path)
    status = "PASS" if schema_result.passed else "FAIL"
    print(f"[{status}] {schema_result.name}")
    for detail in schema_result.details:
        print(f"       {detail}")
    if not schema_result.passed:
        print("\nResult: FAIL (config invalid, skipping server checks)")
        return 1

    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover
        print(f"could not re-read config: {exc}")
        return 1
    servers = validate_config(data).servers

    all_ok = True
    for name, entry in servers.items():
        print(f"\n--- server: {name} ---")
        if not run_server_checks(name, entry):
            all_ok = False

    print("\nResult:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


def cmd_demo() -> int:
    """Check the bundled demo server end to end with zero dependencies."""
    config = {
        "mcpServers": {
            "demo": {
                "command": sys.executable,
                "args": ["-m", "mcp_doctor.demo_server"],
            }
        }
    }
    with tempfile.TemporaryDirectory(prefix="mcp-doctor-demo-") as tmpdir:
        path = os.path.join(tmpdir, "mcp.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
        print(f"demo config: {path}\n")
        return cmd_check(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp-doctor",
        description="Validate MCP (Model Context Protocol) server setups.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="validate the servers in an mcp.json file")
    p_check.add_argument("config", help="path to the MCP config file (mcp.json)")

    sub.add_parser("demo", help="run the full check against the bundled demo server")

    args = parser.parse_args(argv)
    if args.command == "check":
        return cmd_check(args.config)
    if args.command == "demo":
        return cmd_demo()
    parser.print_help()  # pragma: no cover
    return 2  # pragma: no cover
