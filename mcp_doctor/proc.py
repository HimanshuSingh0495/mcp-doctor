"""Subprocess launch + stdio JSON-RPC framing for mcp-doctor.

Every read carries a timeout so a hung server can never hang the CLI.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class McpError(Exception):
    """Raised when a server process cannot be used."""


@dataclass
class McpProcess:
    """A launched MCP server with timeout-guarded stdio JSON-RPC I/O."""

    process: subprocess.Popen
    stderr_hint: str = ""
    _queue: "queue.Queue[str]" = field(default_factory=queue.Queue, repr=False)
    _reader: Optional[threading.Thread] = field(default=None, repr=False)
    closed: bool = False

    def send(self, payload: Dict[str, Any]) -> None:
        """Write one JSON-RPC message (newline-delimited) to stdin."""
        if self.process.stdin is None:
            raise McpError("server stdin is not a pipe")
        line = json.dumps(payload) + "\n"
        try:
            self.process.stdin.write(line.encode("utf-8"))
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpError(f"failed to write to server stdin: {exc}") from exc

    def recv(self, timeout: float) -> Dict[str, Any]:
        """Read one JSON-RPC message from stdout, waiting at most `timeout`."""
        try:
            line = self._queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise McpError(
                f"timed out after {timeout:g}s waiting for server response"
            ) from exc
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise McpError(f"server sent invalid JSON: {line[:120]!r}") from exc
        if not isinstance(message, dict):
            raise McpError(f"server sent a non-object message: {message!r}")
        return message

    def close(self, timeout: float = 2.0) -> None:
        """Terminate the server, escalating to kill if it does not exit."""
        if self.closed:
            return
        self.closed = True
        try:
            self.process.terminate()
            self.process.wait(timeout=timeout)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass


def _drain_stdout(proc: subprocess.Popen, out: "queue.Queue[str]") -> None:
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            out.put(line.decode("utf-8", errors="replace"))
    except Exception:
        pass


def launch(entry: Dict[str, Any], launch_timeout: float = 5.0) -> McpProcess:
    """Spawn a server entry; verify it stays alive through the launch window.

    Raises McpError on FileNotFoundError, immediate non-zero exit, or a
    missing executable.
    """
    command = entry["command"]
    args = entry.get("args", []) or []
    env = entry.get("env", {}) or {}

    if os.sep not in command and not os.path.isabs(command):
        # Bare command name: must be on PATH, else Popen raises FileNotFoundError
        if shutil.which(command) is None:
            raise McpError(f"command {command!r} not found on PATH")

    merged_env = dict(os.environ)
    merged_env.update(env)

    try:
        proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
        )
    except FileNotFoundError as exc:
        raise McpError(f"command {command!r} not found: {exc}") from exc
    except OSError as exc:
        raise McpError(f"could not launch {command!r}: {exc}") from exc

    mcp = McpProcess(process=proc)
    reader = threading.Thread(
        target=_drain_stdout, args=(proc, mcp._queue), daemon=True
    )
    reader.start()
    mcp._reader = reader

    # Give the process a moment: if it exits immediately, surface stderr.
    deadline = time.time() + launch_timeout
    time.sleep(0.25)
    code = proc.poll()
    if code is not None and code != 0:
        stderr = _read_stderr(proc)
        mcp.close()
        hint = f" (stderr: {stderr[:300]})" if stderr else ""
        raise McpError(f"server exited immediately with code {code}{hint}")

    # Wait out the rest of the window in case it dies slowly at startup.
    while time.time() < deadline:
        code = proc.poll()
        if code is not None and code != 0:
            stderr = _read_stderr(proc)
            mcp.close()
            hint = f" (stderr: {stderr[:300]})" if stderr else ""
            raise McpError(f"server exited during launch with code {code}{hint}")
        if code is not None:
            break
        time.sleep(0.1)

    return mcp


def _read_stderr(proc: subprocess.Popen) -> str:
    try:
        assert proc.stderr is not None
        data = proc.stderr.read()
        return (data or b"").decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
