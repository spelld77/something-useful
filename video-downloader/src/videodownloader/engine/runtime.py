from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import cache

from videodownloader.engine.process import hidden_subprocess_kwargs


@dataclass(frozen=True, slots=True)
class JsRuntime:
    name: str
    executable: str
    version: str
    supported: bool

    @property
    def yt_dlp_value(self) -> str:
        return self.name


RUNTIME_COMMANDS = {
    "deno": "deno",
    "node": "node",
    "quickjs": "qjs",
}

MINIMUM_VERSIONS = {
    "deno": (2, 3, 0),
    "node": (22, 0, 0),
    "quickjs": (2023, 12, 9),
}


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not match:
        return ()
    return tuple(int(part or 0) for part in match.groups())


@cache
def inspect_js_runtime(name: str) -> JsRuntime | None:
    command = RUNTIME_COMMANDS.get(name)
    if command is None:
        return None
    executable = shutil.which(command)
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            encoding="utf-8",
            errors="replace",
            shell=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    first_line = (completed.stdout or completed.stderr).strip().splitlines()
    version = first_line[0] if first_line else "알 수 없음"
    parsed = _version_tuple(version)
    supported = bool(parsed) and parsed >= MINIMUM_VERSIONS[name]
    return JsRuntime(
        name=name,
        executable=executable,
        version=version,
        supported=supported,
    )


@cache
def select_js_runtime(preference: str = "auto") -> JsRuntime | None:
    if preference == "none":
        return None
    names = ("deno", "node", "quickjs") if preference == "auto" else (preference,)
    for name in names:
        runtime = inspect_js_runtime(name)
        if runtime is not None and runtime.supported:
            return runtime
    return None
