"""Execute dynamic tool code in an isolated venv subprocess (JSON in / JSON out)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any

from .env_manager import environment_exists, get_tool_python

TIMEOUT_SECONDS = 60
STDERR_CAP = 8000
STDOUT_CAP = 12000

ENTRYPOINT_FUNC = "run"


def execute_in_sandbox(
    tool_name: str,
    code: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Run `code` defining function `run(**args)` using the tool's venv Python.
    Returns a dict with ok/result or ok/error/stderr_tail for the agent.
    """
    if not environment_exists(tool_name):
        return {
            "ok": False,
            "error": f"Virtual environment for tool '{tool_name}' is not ready yet.",
            "env_missing": True,
        }

    runner = f"""
import json, sys
{code}

if __name__ == "__main__":
    raw = sys.stdin.read()
    args = json.loads(raw)
    try:
        result = {ENTRYPOINT_FUNC}(**args)
        out = {{"ok": True, "result": result}}
        print(json.dumps(out, default=str))
    except Exception as e:
        import traceback
        print(json.dumps({{"ok": False, "error": str(e), "traceback": traceback.format_exc()}}))
"""
    proc = None
    script_path = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(runner)
            script_path = f.name

        proc = subprocess.run(
            [get_tool_python(tool_name), script_path],
            input=json.dumps(args),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": "/tmp",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH", ""),
                "LIBRARY_PATH": os.environ.get("LIBRARY_PATH", ""),
                "NIX_LD_LIBRARY_PATH": os.environ.get("NIX_LD_LIBRARY_PATH", ""),
            },
        )
        raw_out = (proc.stdout or "").strip()
        err_tail = (proc.stderr or "")[-STDERR_CAP:]
        if proc.returncode != 0 and not raw_out:
            return {
                "ok": False,
                "error": f"Process exited with code {proc.returncode}",
                "stderr_tail": err_tail,
                "returncode": proc.returncode,
            }
        if not raw_out:
            return {
                "ok": False,
                "error": "No output from tool",
                "stderr_tail": err_tail,
            }
        try:
            parsed = json.loads(raw_out)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": "Unparseable JSON from tool stdout",
                "stdout_preview": raw_out[:500],
                "stderr_tail": err_tail,
            }
        if not parsed.get("ok", True):
            tb = parsed.get("traceback")
            msg = parsed.get("error", "Unknown error")
            return {
                "ok": False,
                "error": msg,
                "traceback": (tb or "")[-STDERR_CAP:],
                "stderr_tail": err_tail,
            }
        if err_tail.strip():
            parsed["stderr_tail"] = err_tail
        return parsed
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Timed out after {TIMEOUT_SECONDS}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if script_path:
            try:
                os.unlink(script_path)
            except OSError:
                pass
