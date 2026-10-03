from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any


class ProcessStartError(RuntimeError):
    """Raised when an external process cannot be started."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    cancelled: bool = False


LineCallback = Callable[[str], None]


def hidden_subprocess_kwargs() -> dict[str, Any]:
    """Keep console child processes from flashing a window in the Windows GUI."""
    if sys.platform != "win32":
        return {}
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startup_info,
    }


class ProcessRunner:
    """Run subprocesses without a command shell."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_process: subprocess.Popen[str] | None = None
        self._cancel_requested = threading.Event()

    def cancel_current(self) -> None:
        self._cancel_requested.set()
        with self._lock:
            process = self._current_process
        if process is not None and process.poll() is None:
            with suppress(OSError):
                process.terminate()

    def run(self, args: Sequence[str], *, timeout: float | None = None) -> CommandResult:
        self._cancel_requested.clear()
        try:
            process = subprocess.Popen(
                list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                **hidden_subprocess_kwargs(),
            )
        except OSError as exc:
            raise ProcessStartError(str(exc)) from exc

        with self._lock:
            self._current_process = process
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            with suppress(OSError):
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                with suppress(OSError):
                    process.kill()
                process.wait()
            raise ProcessStartError(str(exc)) from exc
        finally:
            with self._lock:
                if self._current_process is process:
                    self._current_process = None

        return CommandResult(
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
            cancelled=self._cancel_requested.is_set(),
        )

    def stream(self, args: Sequence[str], *, on_line: LineCallback) -> CommandResult:
        self._cancel_requested.clear()
        try:
            process = subprocess.Popen(
                list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                shell=False,
                **hidden_subprocess_kwargs(),
            )
        except OSError as exc:
            raise ProcessStartError(str(exc)) from exc

        with self._lock:
            self._current_process = process

        output_lines: list[str] = []
        assert process.stdout is not None
        try:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                output_lines.append(line)
                on_line(line)
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        finally:
            with self._lock:
                if self._current_process is process:
                    self._current_process = None

        return CommandResult(
            returncode=process.wait(),
            stdout="\n".join(output_lines),
            cancelled=self._cancel_requested.is_set(),
        )
