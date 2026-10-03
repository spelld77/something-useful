from __future__ import annotations

import ctypes
import sys
import traceback
from pathlib import Path


def launch() -> int:
    if "--version" in sys.argv[1:]:
        return 0
    try:
        from videodownloader.gui import main

        return main()
    except BaseException:
        message = traceback.format_exc()
        root = (
            Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
        )
        with (root / "startup-error.log").open("w", encoding="utf-8") as log_file:
            log_file.write(message)
        ctypes.windll.user32.MessageBoxW(
            0,
            "프로그램을 시작하지 못했습니다. startup-error.log를 확인하세요.",
            "VideoDownloader",
            0x10,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(launch())
