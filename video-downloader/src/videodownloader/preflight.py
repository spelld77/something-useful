from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from videodownloader.config import Settings
from videodownloader.engine.process import hidden_subprocess_kwargs
from videodownloader.engine.runtime import inspect_js_runtime, select_js_runtime


@dataclass(frozen=True, slots=True)
class ToolCheck:
    name: str
    found: bool
    required: bool
    path: str | None = None
    version: str | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class PreflightReport:
    tools: tuple[ToolCheck, ...]
    save_dir: Path
    save_dir_ready: bool

    @property
    def required_ok(self) -> bool:
        return self.save_dir_ready and all(check.found for check in self.tools if check.required)

    @property
    def youtube_ready(self) -> bool:
        runtime_ready = any(check.name.startswith("js:") and check.found for check in self.tools)
        ejs_ready = any(check.name == "yt-dlp-ejs" and check.found for check in self.tools)
        return runtime_ready and ejs_ready


def _version(executable: str) -> str | None:
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    first_line = (completed.stdout or completed.stderr).strip().splitlines()
    return first_line[0] if first_line else None


def _tool(name: str, *, required: bool, note: str = "") -> ToolCheck:
    path = shutil.which(name)
    return ToolCheck(
        name=name,
        found=path is not None,
        required=required,
        path=path,
        version=_version(path) if path else None,
        note=note,
    )


def _adjacent_python(executable: str | None) -> Path | None:
    if not executable:
        return None
    scripts_dir = Path(executable).resolve().parent
    if scripts_dir.name.casefold() != "scripts":
        return None
    candidate = scripts_dir.parent / "python.exe"
    return candidate if candidate.exists() else None


def _python_has_module(python: str, module: str) -> bool:
    code = (
        "import importlib.util,sys;"
        f"sys.exit(0 if importlib.util.find_spec({module!r}) is not None else 1)"
    )
    try:
        completed = subprocess.run(
            [python, "-c", code],
            capture_output=True,
            timeout=5,
            check=False,
            shell=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _ejs_check(yt_dlp_path: str | None, *, remote_enabled: bool) -> ToolCheck:
    if remote_enabled:
        return ToolCheck(
            name="yt-dlp-ejs",
            found=True,
            required=False,
            note="GitHub 원격 구성요소 허용",
        )

    found = importlib.util.find_spec("yt_dlp_ejs") is not None
    adjacent = _adjacent_python(yt_dlp_path)
    if not found and adjacent is not None:
        found = _python_has_module(str(adjacent), "yt_dlp_ejs")
    return ToolCheck(
        name="yt-dlp-ejs",
        found=found,
        required=False,
        note="설치형 EJS challenge solver" if found else "yt-dlp[default] 설치 권장",
    )


def _runtime_check(preference: str) -> ToolCheck:
    selected = select_js_runtime(preference)
    if selected is not None:
        return ToolCheck(
            name=f"js:{selected.name}",
            found=True,
            required=False,
            path=selected.executable,
            version=selected.version,
        )

    requested = preference if preference not in {"auto", "none"} else "JavaScript runtime"
    inspected = inspect_js_runtime(preference) if preference not in {"auto", "none"} else None
    note = "사용 안 함" if preference == "none" else f"지원되는 {requested} 없음"
    if inspected is not None and not inspected.supported:
        note = f"지원하지 않는 버전: {inspected.version}"
    return ToolCheck(name="js-runtime", found=False, required=False, note=note)


def _browser_path(browser: str) -> str | None:
    executable_name = "chrome" if browser == "chrome" else "msedge"
    on_path = shutil.which(executable_name)
    if on_path:
        return on_path

    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if browser == "chrome":
        candidates = (
            Path(program_files) / "Google/Chrome/Application/chrome.exe",
            Path(program_files_x86) / "Google/Chrome/Application/chrome.exe",
            Path(local_app_data) / "Google/Chrome/Application/chrome.exe",
        )
    else:
        candidates = (
            Path(program_files_x86) / "Microsoft/Edge/Application/msedge.exe",
            Path(program_files) / "Microsoft/Edge/Application/msedge.exe",
        )
    return str(next((path for path in candidates if path.is_file()), "")) or None


def _browser_capture_checks(settings: Settings) -> tuple[ToolCheck, ...]:
    if not settings.browser_capture.enabled:
        return ()
    selenium_found = importlib.util.find_spec("selenium") is not None
    browser_path = _browser_path(settings.browser_capture.browser)
    return (
        ToolCheck(
            name="selenium",
            found=selenium_found,
            required=True,
            note="브라우저 캡처 선택 의존성",
        ),
        ToolCheck(
            name=f"browser:{settings.browser_capture.browser}",
            found=browser_path is not None,
            required=True,
            path=browser_path,
            note="브라우저 실행 파일",
        ),
    )


def _save_dir_ready(path: Path) -> bool:
    existing_parent = path
    while not existing_parent.exists() and existing_parent != existing_parent.parent:
        existing_parent = existing_parent.parent
    return existing_parent.is_dir() and os.access(existing_parent, os.W_OK)


def run_preflight(settings: Settings) -> PreflightReport:
    yt_dlp = _tool("yt-dlp", required=True)
    tools = (
        yt_dlp,
        _tool("ffmpeg", required=True),
        _tool("ffprobe", required=True),
        _runtime_check(settings.youtube.js_runtime),
        _ejs_check(yt_dlp.path, remote_enabled=settings.youtube.remote_ejs),
        *_browser_capture_checks(settings),
    )
    save_dir = settings.app.save_dir.expanduser().resolve()
    return PreflightReport(
        tools=tools,
        save_dir=save_dir,
        save_dir_ready=_save_dir_ready(save_dir),
    )


def format_report(report: PreflightReport) -> str:
    lines = ["VideoDownloader v5 사전진단", "=" * 32]
    for check in report.tools:
        status = "OK" if check.found else ("필수 누락" if check.required else "선택 누락")
        details = check.path or check.note
        if check.version:
            details = f"{details} ({check.version})"
        lines.append(f"[{status:^9}] {check.name:<8} {details}".rstrip())

    save_status = "OK" if report.save_dir_ready else "쓰기 불가"
    lines.append(f"[{save_status:^9}] 저장경로 {report.save_dir}")
    lines.append("-" * 32)
    lines.append("필수 항목 정상" if report.required_ok else "필수 항목을 먼저 해결해야 합니다.")
    lines.append(
        "YouTube JavaScript 구성 정상"
        if report.youtube_ready
        else "YouTube 사용 전 JavaScript 구성을 보완하세요."
    )
    return "\n".join(lines)
