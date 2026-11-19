from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from videodownloader.models import DownloadResult, ErrorKind


def url_fingerprint(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    timestamp: str
    url_hash: str
    mode: str
    quality: str
    status: str
    output_path: str = ""
    error_kind: str = ""
    engine_version: str = ""
    resolution: str = ""
    video_codec: str = ""
    audio_codec: str = ""

    @classmethod
    def from_result(
        cls,
        url: str,
        mode: str,
        result: DownloadResult,
        *,
        quality: str = "",
        engine_version: str = "",
    ) -> HistoryRecord:
        return cls(
            timestamp=datetime.now(UTC).isoformat(),
            url_hash=url_fingerprint(url),
            mode=mode,
            quality=quality if mode == "video" else "",
            status="completed" if result.success else "failed",
            output_path=str(result.output_path.resolve()) if result.output_path else "",
            error_kind=str(result.error_kind) if result.error_kind else "",
            engine_version=engine_version,
            resolution=result.media_info.resolution if result.media_info else "",
            video_codec=result.media_info.video_codec if result.media_info else "",
            audio_codec=result.media_info.audio_codec if result.media_info else "",
        )


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def append(self, record: HistoryRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as history_file:
            json.dump(asdict(record), history_file, ensure_ascii=False, separators=(",", ":"))
            history_file.write("\n")

    def completed_keys(self) -> set[tuple[str, str, str]]:
        return set(self.completed_paths())

    def clear(self) -> None:
        """Clear job history only; never remove downloaded files."""
        self.path.unlink(missing_ok=True)

    def completed_paths(self) -> dict[tuple[str, str, str], Path]:
        if not self.path.exists():
            return {}
        completed: dict[tuple[str, str, str], Path] = {}
        with self.path.open("r", encoding="utf-8") as history_file:
            for line in history_file:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict) or payload.get("status") != "completed":
                    continue
                url_hash = payload.get("url_hash")
                mode = payload.get("mode")
                quality = payload.get("quality", "")
                output_text = payload.get("output_path")
                if not isinstance(output_text, str) or not output_text:
                    continue
                output = Path(output_text)
                if not output.is_absolute():
                    output = self.path.parent / output
                try:
                    valid = output.is_file() and output.stat().st_size > 0
                except OSError:
                    valid = False
                if valid and isinstance(url_hash, str) and isinstance(mode, str):
                    completed[(url_hash, mode, quality if isinstance(quality, str) else "")] = (
                        output
                    )
        return completed


class FailedUrlStore:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def append(self, url: str, error_kind: ErrorKind | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        reason = str(error_kind or ErrorKind.UNKNOWN)
        timestamp = datetime.now(UTC).isoformat()
        with self.path.open("a", encoding="utf-8", newline="\n") as failed_file:
            failed_file.write(f"# {timestamp} | {reason}\n")
            failed_file.write(f"{url.strip()}\n")
