"""Per-dynamic-tool virtualenv under SANDBOX_ENVS_DIR (see .env.example)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
SANDBOX_ENVS_DIR = Path(os.environ.get("SANDBOX_ENVS_DIR", str(_BACKEND_ROOT / ".sandbox-envs")))


def tool_venv_path(tool_name: str) -> Path:
    """Directory name must match registration rules (safe characters only)."""
    return SANDBOX_ENVS_DIR / tool_name


def get_tool_python(tool_name: str) -> str:
    return str(tool_venv_path(tool_name) / "bin" / "python")


def environment_exists(tool_name: str) -> bool:
    return Path(get_tool_python(tool_name)).exists()


def create_tool_environment(tool_name: str, requirements: List[str]) -> dict:
    """Create venv and pip install. Blocking — call from a background thread only."""
    venv_path = tool_venv_path(tool_name)
    try:
        SANDBOX_ENVS_DIR.mkdir(parents=True, exist_ok=True)
        if venv_path.exists():
            shutil.rmtree(venv_path)
        subprocess.run(
            [os.environ.get("PYTHON_EXECUTABLE", "python3"), "-m", "venv", str(venv_path)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        if requirements:
            pip = venv_path / "bin" / "pip"
            subprocess.run(
                [str(pip), "install", "--no-cache-dir", *requirements],
                check=True,
                capture_output=True,
                timeout=600,
            )
        return {"ok": True}
    except subprocess.CalledProcessError as e:
        err = b""
        if e.stderr:
            err += e.stderr
        if e.stdout:
            err += e.stdout
        return {"ok": False, "error": err.decode(errors="replace")[:4000] or str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def delete_tool_environment(tool_name: str) -> None:
    p = tool_venv_path(tool_name)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
