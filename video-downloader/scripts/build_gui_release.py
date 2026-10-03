from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build" / "gui"
APP_DIR = BUILD_DIR / "dist" / "VideoDownloader"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def package_version() -> str:
    source = (ROOT / "src" / "videodownloader" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    if match is None:
        raise RuntimeError("videodownloader.__version__을 찾을 수 없습니다.")
    return match.group(1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_generated_path(path: Path) -> Path:
    resolved = path.resolve()
    allowed = (ROOT / "build").resolve(), DIST_DIR.resolve()
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise RuntimeError(f"안전하지 않은 생성 경로입니다: {resolved}")
    return resolved


def build_executable() -> Path:
    if BUILD_DIR.exists():
        shutil.rmtree(_safe_generated_path(BUILD_DIR))
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    temp_dir = BUILD_DIR / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({name: str(temp_dir) for name in ("TEMP", "TMP", "TMPDIR")})
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onedir",
            "--name",
            "VideoDownloader",
            "--paths",
            str(ROOT / "src"),
            "--distpath",
            str(APP_DIR.parent),
            "--workpath",
            str(BUILD_DIR / "work"),
            "--specpath",
            str(BUILD_DIR / "spec"),
            "--collect-submodules",
            "selenium",
            str(ROOT / "scripts" / "gui_launcher.py"),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    # QtCore uses the Windows ICU forwarding DLLs. PyInstaller may resolve those
    # forwarders to a WinSxS implementation and copy it under the same basename,
    # which shadows the system DLL and causes a procedure mismatch at startup.
    internal_dir = APP_DIR / "_internal"
    for pattern in ("icuuc.dll", "icudt*.dll"):
        for shadow_dll in internal_dir.glob(pattern):
            shadow_dll.unlink()
    executable = APP_DIR / "VideoDownloader.exe"
    if not executable.is_file():
        raise RuntimeError("VideoDownloader.exe 생성 결과를 찾을 수 없습니다.")
    return executable


def prepare_application(version: str, executable: Path) -> None:
    shutil.copy2(ROOT / "config.example.toml", APP_DIR / "config.example.toml")
    shutil.copy2(ROOT / "config.example.toml", APP_DIR / "config.toml")
    shutil.copy2(ROOT / "urls.example.txt", APP_DIR / "urls.example.txt")
    shutil.copy2(ROOT / "README.md", APP_DIR / "README.md")
    manifest = {
        "name": "VideoDownloader GUI",
        "version": version,
        "platform": "Windows",
        "entrypoint": executable.name,
        "external_tools": ["yt-dlp", "ffmpeg", "ffprobe"],
        "browser_capture": True,
    }
    (APP_DIR / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_bundle(version: str) -> Path:
    bundle = DIST_DIR / f"VideoDownloader-GUI-v{version}-windows.zip"
    bundle.unlink(missing_ok=True)
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(APP_DIR.rglob("*")):
            if not source.is_file():
                continue
            relative = PurePosixPath("VideoDownloader") / PurePosixPath(
                source.relative_to(APP_DIR).as_posix()
            )
            info = zipfile.ZipInfo(str(relative), FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())
    return bundle


def write_checksums() -> Path:
    artifacts = sorted((*DIST_DIR.glob("*.whl"), *DIST_DIR.glob("*.zip")))
    output = DIST_DIR / "SHA256SUMS.txt"
    output.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in artifacts),
        encoding="utf-8",
        newline="\n",
    )
    return output


def main() -> int:
    version = package_version()
    executable = build_executable()
    prepare_application(version, executable)
    bundle = build_bundle(version)
    checksums = write_checksums()
    print(f"executable: {executable}")
    print(f"bundle: {bundle}")
    print(f"checksums: {checksums}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
