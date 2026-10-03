from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from videodownloader.storage.history import url_fingerprint


@dataclass(frozen=True, slots=True)
class FileHistoryRecord:
    timestamp: str
    url_hash: str
    output_path: str
    size: int

    @classmethod
    def completed(cls, url: str, output_path: Path) -> FileHistoryRecord:
        return cls(
            timestamp=datetime.now(UTC).isoformat(),
            url_hash=url_fingerprint(url),
            output_path=str(output_path),
            size=output_path.stat().st_size,
        )


class FileHistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def append(self, record: FileHistoryRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as history_file:
            json.dump(asdict(record), history_file, ensure_ascii=False, separators=(",", ":"))
            history_file.write("\n")

    def completed_hashes(self) -> set[str]:
        if not self.path.is_file():
            return set()
        completed: set[str] = set()
        with self.path.open("r", encoding="utf-8") as history_file:
            for line in history_file:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                url_hash = payload.get("url_hash")
                output_text = payload.get("output_path")
                size = payload.get("size")
                if not isinstance(url_hash, str) or not isinstance(output_text, str):
                    continue
                if isinstance(size, bool) or not isinstance(size, int):
                    continue
                output_path = Path(output_text)
                try:
                    valid = output_path.is_file() and output_path.stat().st_size == size
                except OSError:
                    valid = False
                if valid:
                    completed.add(url_hash)
        return completed
