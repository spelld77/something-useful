from __future__ import annotations

from datetime import datetime
from pathlib import Path

MAX_TITLE_BYTES = 180


def prepare_output_directory(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.is_dir():
        raise NotADirectoryError(f"저장 경로가 폴더가 아닙니다: {resolved}")
    return resolved


def build_output_template(save_dir: Path, *, timestamp: bool = False) -> str:
    """Build a yt-dlp template safe for same-title videos and long Windows paths."""
    prefix = datetime.now().strftime("[%Y%m%d_%H%M] ") if timestamp else ""
    filename = f"{prefix}%(title).{MAX_TITLE_BYTES}B [%(id)s].%(ext)s"
    return str(save_dir / filename)
