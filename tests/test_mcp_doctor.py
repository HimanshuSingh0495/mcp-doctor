"""Tests for mcp-doctor."""

import json
import os
import sys

import pytest

from mcp_doctor import proc as proc_mod
from mcp_doctor.checks import (
    check_handshake,
    check_launch,
    check_schema,
    check_tools,
    run_server_checks,
)
from mcp_doctor.cli import cmd_check, cmd_demo
from mcp_doctor.demo_server import TOOLS
from mcp_doctor.proc import McpError
from mcp_doctor.schema import validate_config


def demo_entry():
    return {
        "command": sys.executable,
        "args": ["-m", "mcp_doctor.demo_server"],
        "env": {},
    }


# --- schema validation -------------------------------------------------------

def test_schema_good_config():
    data = {
        "mcpServers": {
            "demo": {
                "command": "python",
                "args": ["-m", "demo"],
                "env": {"FOO": "bar"},
            }
        }
    }
    result = validate_config(data)
    assert result.ok
    assert not result.errors
    assert not result.warnings
    assert result.servers["demo"]["command"] == "python"


def test_schema_missing_command():
    result = validate_config({"mcpServers": {"bad": {"args": []}}})
    assert not result.ok
    assert any("'command'" in e for e in result.errors)


def test_schema_wrong_types():
    result = validate_config({
        "mcpServers": {
            "bad": {"command": 123, "args": "nope", "env": {"K": 5}},
        }
    })
    assert not result.ok
    assert len(result.errors) == 3


def test_schema_unknown_fields_are_warnings():
    result = validate_config({
        "mcpServers": {"s": {"command": "x", "bogus": True}},
        "topLevelBogus": 1,
    })
    assert result.ok
    assert len(result.warnings) == 2
    assert any("bogus" in w for w in result.warnings)


def test_schema_missing_mcp_servers():
    result = validate_config({})
    assert not result.ok
    assert any("mcpServers" in e for e in result.errors)


def test_schema_non_object():
    result = validate_config([1, 2, 3])
    assert not result.ok


# --- real stdio round-trip against the demo server ----------------------------

def test_handshake_against_demo_server():
    mcp = proc_mod.launch(demo_entry())
    try:
        result = check_handshake(mcp, "demo")
        assert result.passed, result.details
        assert any("demo-server" in d for d in result.details)
    finally:
        mcp.close()


def test_tools_list_returns_fake_tools():
    mcp = proc_mod.launch(demo_entry())
    try:
        handshake = check_handshake(mcp, "demo")
        assert handshake.passed
        result = check_tools(mcp, "demo")
        assert result.passed, result.details
        names = {tool["name"] for tool in TOOLS}
        assert names == {"echo", "add", "reverse"}
        for tool in TOOLS:
            assert any(tool["name"] in d for d in result.details)
    finally:
        mcp.close()


# --- failure paths ------------------------------------------------------------

def test_check_fails_cleanly_on_bogus_command():
    outcome = check_launch("bogus", {"command": "mcp-doctor-no-such-cmd-xyz"})
    assert not outcome.result.passed
    assert outcome.process is None


def test_launch_reports_immediate_exit():
    outcome = check_launch(
        "crasher",
        {"command": sys.executable, "args": ["-c", "import sys; sys.exit(3)"]},
    )
    assert not outcome.result.passed
    assert "code 3" in outcome.result.details[0]


def test_handshake_timeout_on_silent_server():
    # A server that starts but never speaks must fail fast, not hang.
    mcp = proc_mod.launch(
        {"command": sys.executable, "args": ["-c", "import time; time.sleep(30)"]}
    )
    try:
        with pytest.raises(McpError, match="timed out"):
            mcp.recv(0.5)
    finally:
        mcp.close()


# --- end to end -----------------------------------------------------------------

def test_demo_runs_end_to_end(tmp_path, capsys):
    rc = cmd_demo()
    out = capsys.readouterr().out
    assert rc == 0
    assert "[PASS] config schema" in out
    assert "[PASS] launch 'demo'" in out
    assert "[PASS] handshake 'demo'" in out
    assert "[PASS] tools/list 'demo'" in out
    assert "echo" in out and "add" in out and "reverse" in out


def test_check_against_handwritten_config(tmp_path, capsys):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({
        "mcpServers": {
            "demo": {
                "command": sys.executable,
                "args": ["-m", "mcp_doctor.demo_server"],
            }
        }
    }))
    rc = cmd_check(str(path))
    assert rc == 0
    assert "[PASS]" in capsys.readouterr().out


def test_check_schema_fails_on_bad_json(tmp_path, capsys):
    path = tmp_path / "mcp.json"
    path.write_text("{not json")
    rc = cmd_check(str(path))
    assert rc == 1
    assert "[FAIL] config schema" in capsys.readouterr().out


def test_check_schema_fails_on_missing_command(tmp_path, capsys):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"bad": {}}}))
    rc = cmd_check(str(path))
    assert rc == 1
    assert "[FAIL] config schema" in capsys.readouterr().out


def test_check_fails_on_bogus_server(tmp_path, capsys):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({
        "mcpServers": {"bogus": {"command": "mcp-doctor-no-such-cmd-xyz"}}
    }))
    rc = cmd_check(str(path))
    assert rc == 1
    assert "[FAIL] launch 'bogus'" in capsys.readouterr().out


def test_run_server_checks_full_success():
    ok = run_server_checks("demo", demo_entry(), print_fn=lambda *a: None)
    assert ok


def test_demo_server_module_runnable():
    # python -m mcp_doctor.demo_server must speak JSON-RPC on stdio.
    import subprocess

    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_doctor.demo_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        request = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}},
        }) + "\n"
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(request.encode())
        proc.stdin.flush()
        line = proc.stdout.readline().decode()
        response = json.loads(line)
        assert response["result"]["serverInfo"]["name"] == "demo-server"
    finally:
        proc.kill()
