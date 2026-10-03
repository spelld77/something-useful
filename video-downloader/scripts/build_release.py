from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
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


def _write_zip_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(str(PurePosixPath(name)), FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def build_wheel(version: str) -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    expected = DIST_DIR / f"videodownloader-{version}-py3-none-any.whl"
    expected.unlink(missing_ok=True)
    temp_dir = ROOT / "build" / "pip-temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({name: str(temp_dir) for name in ("TEMP", "TMP", "TMPDIR")})
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(DIST_DIR),
        ],
        cwd=ROOT,
        check=True,
        env=environment,
    )
    if not expected.is_file():
        raise RuntimeError(f"wheel 생성 결과를 찾을 수 없습니다: {expected.name}")
    return expected


def build_bundle(version: str, wheel: Path) -> Path:
    bundle = DIST_DIR / f"VideoDownloader-v{version}-windows.zip"
    bundle.unlink(missing_ok=True)
    manifest = {
        "name": "VideoDownloader v5",
        "version": version,
        "python": ">=3.12",
        "platform": "Windows",
        "external_tools": ["yt-dlp", "ffmpeg", "ffprobe"],
        "wheel": wheel.name,
        "wheel_sha256": sha256(wheel),
    }
    files = {
        wheel.name: wheel,
        "README.md": ROOT / "README.md",
        "config.example.toml": ROOT / "config.example.toml",
        "urls.example.txt": ROOT / "urls.example.txt",
        "install.ps1": ROOT / "scripts" / "install_release.ps1",
        "docs/architecture.md": ROOT / "docs" / "architecture.md",
        "docs/implementation-plan.md": ROOT / "docs" / "implementation-plan.md",
        "docs/acceptance.md": ROOT / "docs" / "acceptance.md",
    }
    with zipfile.ZipFile(bundle, "w") as archive:
        for archive_name, source in sorted(files.items()):
            _write_zip_entry(archive, archive_name, source.read_bytes())
        _write_zip_entry(
            archive,
            "release-manifest.json",
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    return bundle


def write_checksums(artifacts: tuple[Path, ...]) -> Path:
    output = DIST_DIR / "SHA256SUMS.txt"
    lines = [f"{sha256(path)}  {path.name}" for path in artifacts]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return output


def main() -> int:
    version = package_version()
    wheel = build_wheel(version)
    bundle = build_bundle(version, wheel)
    checksums = write_checksums((wheel, bundle))
    print(f"wheel: {wheel}")
    print(f"bundle: {bundle}")
    print(f"checksums: {checksums}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
