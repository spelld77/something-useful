from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from videodownloader.models import DownloadResult, Job, ProbeResult

ProgressCallback = Callable[[dict[str, object]], None]


class DownloadEngine(Protocol):
    """Stable boundary around a replaceable download implementation."""

    def probe(self, job: Job) -> ProbeResult:
        """Read metadata without downloading media."""
        ...

    def download(
        self,
        job: Job,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> DownloadResult:
        """Download one job and return a classified result."""
        ...

    def cancel(self) -> None:
        """Request cancellation of the current operation."""
        ...
