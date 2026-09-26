"""Locate SUMO binaries and run them with SUMO_HOME set."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def sumo_home() -> Path:
    env = os.environ.get("SUMO_HOME")
    if env:
        path = Path(env)
        if (path / "tools").exists() or (path / "bin").exists():
            return path
    try:
        import sumo

        return Path(sumo.__file__).resolve().parent
    except ImportError:
        pass
    raise RuntimeError(
        "SUMO_HOME is not set and eclipse-sumo is not installed. "
        'Run: pip install -e ".[sim]"'
    )


def sumo_bin(name: str) -> str:
    home = sumo_home()
    for candidate in (
        shutil.which(name),
        str(home / "bin" / name),
        str(Path(shutil.which("python") or "").parent / name) if shutil.which("python") else "",
    ):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError(f"{name} not found on PATH or under {home / 'bin'}")


def sumo_env() -> dict[str, str]:
    env = os.environ.copy()
    home = sumo_home()
    env["SUMO_HOME"] = str(home)
    extra = str(home / "bin")
    env["PATH"] = extra + os.pathsep + env.get("PATH", "")
    return env


def run_sumo(args: list[str], *, cwd: Path | None = None, check: bool = True
             ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, env=sumo_env(), check=check, text=True,
        capture_output=True,
    )


def random_trips_py() -> Path:
    path = sumo_home() / "tools" / "randomTrips.py"
    if not path.is_file():
        raise RuntimeError(f"randomTrips.py not found at {path}")
    return path
