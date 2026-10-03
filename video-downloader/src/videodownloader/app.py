from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from videodownloader import __version__
from videodownloader.config import (
    VIDEO_QUALITY_CHOICES,
    AuthConfig,
    BrowserCaptureConfig,
    ConfigError,
    Settings,
    load_config,
)
from videodownloader.engine.base import DownloadEngine
from videodownloader.engine.factory import build_download_engine
from videodownloader.engine.ytdlp_process import (
    DownloadError,
    compact_format_rows,
)
from videodownloader.models import Job
from videodownloader.preflight import format_report, run_preflight
from videodownloader.service.batch import (
    BatchItemEvent,
    BatchItemStatus,
    BatchService,
    parse_url_file,
)
from videodownloader.service.self_check import format_self_check, run_self_check
from videodownloader.storage.history import FailedUrlStore, HistoryStore

BROWSERS = (
    "none",
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "opera",
    "safari",
    "vivaldi",
    "whale",
)


def _add_auth_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--browser",
        choices=BROWSERS,
        default=None,
        help="사용자가 선택한 브라우저의 쿠키 사용",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="선택한 브라우저 프로필 이름 또는 경로",
    )


def _add_capture_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--browser-capture",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="직접 추출 실패 시 전용 임시 브라우저로 미디어 요청 감지",
    )
    parser.add_argument(
        "--capture-browser",
        choices=("chrome", "edge"),
        default=None,
        help="네트워크 캡처에 사용할 브라우저",
    )


def _add_quality_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--quality",
        choices=VIDEO_QUALITY_CHOICES,
        default=None,
        help="영상 화질: best, 2160p, 1440p, 1080p, 720p, compatible",
    )


def _apply_auth_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    browser = args.browser if args.browser is not None else settings.auth.browser
    profile = args.profile if args.profile is not None else settings.auth.profile
    return replace(settings, auth=AuthConfig(browser=browser, profile=profile))


def _apply_capture_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    enabled = (
        args.browser_capture
        if args.browser_capture is not None
        else settings.browser_capture.enabled
    )
    browser = args.capture_browser or settings.browser_capture.browser
    return replace(
        settings,
        browser_capture=BrowserCaptureConfig(
            enabled=enabled,
            browser=browser,
            timeout_seconds=settings.browser_capture.timeout_seconds,
            interactive_timeout_seconds=(settings.browser_capture.interactive_timeout_seconds),
            grace_seconds=settings.browser_capture.grace_seconds,
        ),
    )


def _apply_quality_override(settings: Settings, args: argparse.Namespace) -> Settings:
    quality = args.quality if args.quality is not None else settings.download.video_quality
    return replace(settings, download=replace(settings.download, video_quality=quality))


def _build_download_engine(settings: Settings) -> DownloadEngine:
    return build_download_engine(
        settings,
        status_callback=lambda message: print(f"브라우저 캡처: {message}"),
        runtime_dir=Path.cwd() / ".runtime",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="video-downloader")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--config",
        default="config.toml",
        help="설정 파일 경로 (없으면 기본값 사용)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="필수 도구와 저장 경로를 점검")
    subparsers.add_parser("self-check", help="릴리스 안전성과 핵심 정책을 자체 점검")

    probe_parser = subparsers.add_parser("probe", help="URL의 영상 정보와 형식을 조회")
    probe_parser.add_argument("url", help="분석할 http/https URL")
    _add_auth_arguments(probe_parser)

    download_parser = subparsers.add_parser("download", help="영상 또는 오디오 한 건 다운로드")
    download_parser.add_argument("url", help="다운로드할 http/https URL")
    mode_group = download_parser.add_mutually_exclusive_group()
    mode_group.add_argument("--video", action="store_const", const="video", dest="mode")
    mode_group.add_argument("--audio", action="store_const", const="audio", dest="mode")
    _add_auth_arguments(download_parser)
    _add_capture_arguments(download_parser)
    _add_quality_argument(download_parser)

    batch_parser = subparsers.add_parser("batch", help="텍스트 파일의 URL을 순서대로 처리")
    batch_parser.add_argument("url_file", nargs="?", default="urls.txt", help="URL 목록 파일")
    batch_mode = batch_parser.add_mutually_exclusive_group()
    batch_mode.add_argument("--video", action="store_const", const="video", dest="mode")
    batch_mode.add_argument("--audio", action="store_const", const="audio", dest="mode")
    batch_parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="완료 이력을 기준으로 기존 작업 건너뛰기",
    )
    batch_parser.add_argument("--delay", type=float, default=None, help="작업 사이 대기 시간(초)")
    _add_auth_arguments(batch_parser)
    _add_capture_arguments(batch_parser)
    _add_quality_argument(batch_parser)
    return parser


def _format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "알 수 없음"
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    return (
        f"{hours:02}:{minutes:02}:{seconds_part:02}" if hours else f"{minutes:02}:{seconds_part:02}"
    )


def _print_probe(engine: DownloadEngine, url: str) -> int:
    try:
        result = engine.probe(Job(url=url))
    except DownloadError as exc:
        print(f"분석 실패 [{exc.kind}]: {exc.message}")
        if exc.details:
            print(exc.details)
        return 1

    rows = compact_format_rows(result.formats)
    print(f"제목: {result.title}")
    if result.uploader:
        print(f"게시자: {result.uploader}")
    print(f"재생시간: {_format_duration(result.duration)}")
    print(f"영상 ID: {result.id or '알 수 없음'}")
    print(f"사용 가능한 형식: {len(rows)}개")
    return 0


def _download(engine: DownloadEngine, url: str, mode: str) -> int:
    progress_seen = False

    def show_progress(progress: dict[str, object]) -> None:
        nonlocal progress_seen
        progress_seen = True
        percent = progress.get("percent") or "?"
        speed = progress.get("speed") or "?"
        eta = progress.get("eta") or "?"
        print(f"\r다운로드 {percent} | 속도 {speed} | 남은 시간 {eta}   ", end="", flush=True)

    result = engine.download(Job(url=url, mode=mode), on_progress=show_progress)
    if progress_seen:
        print()
    if not result.success:
        print(f"다운로드 실패 [{result.error_kind}]: {result.message}")
        return 1

    print(result.message)
    if result.output_path:
        print(f"저장 파일: {result.output_path}")
    if result.media_info is not None:
        media = result.media_info
        details = [
            value
            for value in (
                media.resolution,
                media.video_codec,
                media.audio_codec,
                media.container,
            )
            if value
        ]
        if details:
            print(f"실제 결과: {' · '.join(details)}")
    return 0


def _batch(
    engine: DownloadEngine,
    settings: Settings,
    args: argparse.Namespace,
    *,
    engine_version: str,
) -> int:
    if args.delay is not None and args.delay < 0:
        print("작업 사이 대기 시간은 0 이상이어야 합니다.")
        return 2
    try:
        parsed = parse_url_file(Path(args.url_file))
    except OSError as exc:
        print(f"URL 목록을 읽을 수 없습니다: {exc}")
        return 2

    if parsed.invalid_lines:
        lines = ", ".join(str(line) for line in parsed.invalid_lines)
        print(f"유효하지 않아 제외한 줄: {lines}")
    if parsed.duplicate_count:
        print(f"중복 URL {parsed.duplicate_count}개를 제외했습니다.")
    if not parsed.urls:
        print("처리할 URL이 없습니다.")
        return 2

    service = BatchService(
        engine,
        HistoryStore(settings.batch.history_file),
        FailedUrlStore(settings.batch.failed_file),
        delay_seconds=args.delay if args.delay is not None else settings.batch.delay_seconds,
        engine_version=engine_version,
    )
    progress_seen = False
    current_index = 0
    current_total = len(parsed.urls)

    def item_start(index: int, total: int, _url: str) -> None:
        nonlocal current_index, current_total, progress_seen
        if progress_seen:
            print()
            progress_seen = False
        current_index = index
        current_total = total
        print(f"[{index}/{total}] 작업 시작")

    def show_progress(progress: dict[str, object]) -> None:
        nonlocal progress_seen
        progress_seen = True
        percent = progress.get("percent") or "?"
        speed = progress.get("speed") or "?"
        eta = progress.get("eta") or "?"
        print(
            f"\r[{current_index}/{current_total}] 다운로드 {percent} | "
            f"속도 {speed} | 남은 시간 {eta}   ",
            end="",
            flush=True,
        )

    def item_finished(event: BatchItemEvent) -> None:
        nonlocal progress_seen
        if progress_seen:
            print()
            progress_seen = False
        if event.status == BatchItemStatus.SUCCEEDED:
            output = event.result.output_path if event.result is not None else None
            detail = f": {output}" if output is not None else ""
            print(f"[{event.index}/{event.total}] 완료{detail}")
        elif event.status == BatchItemStatus.FAILED:
            result = event.result
            kind = result.error_kind if result is not None else "unknown"
            print(f"[{event.index}/{event.total}] 실패 ({kind})")
        elif event.status == BatchItemStatus.SKIPPED:
            print(f"[{event.index}/{event.total}] 완료 이력으로 건너뜀")
        else:
            print(f"[{event.index}/{event.total}] 사용자 취소")

    resume = args.resume if args.resume is not None else settings.batch.resume
    summary = service.run(
        parsed.urls,
        mode=args.mode or settings.download.mode,
        quality=settings.download.video_quality,
        resume=resume,
        on_item_start=item_start,
        on_item_finished=item_finished,
        on_progress=show_progress,
    )
    if progress_seen:
        print()

    print(
        f"일괄 처리 결과: 처리 {summary.processed}/{summary.total}, "
        f"성공 {summary.succeeded}, 실패 {summary.failed}, 건너뜀 {summary.skipped}"
    )
    for warning in summary.warnings:
        print(f"경고: {warning}")
    if summary.failed:
        print(f"실패 목록: {settings.batch.failed_file.expanduser().resolve()}")
    if summary.cancelled:
        cancelled_detail = (
            f"취소 항목 {summary.cancelled_items}, " if summary.cancelled_items else ""
        )
        print(f"사용자 요청으로 중단했습니다: {cancelled_detail}미처리 {summary.unprocessed}")
        return 130
    return 1 if summary.failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"설정 오류: {exc}")
        return 2

    if args.command == "doctor":
        report = run_preflight(config)
        print(format_report(report))
        return 0 if report.required_ok else 1

    if args.command == "self-check":
        report = run_self_check(config)
        print(format_self_check(report))
        return 0 if report.passed else 1

    config = _apply_auth_overrides(config, args)
    if args.command in {"download", "batch"}:
        config = _apply_capture_overrides(config, args)
        config = _apply_quality_override(config, args)
    engine = _build_download_engine(config)

    if args.command == "probe":
        return _print_probe(engine, args.url)

    if args.command == "download":
        report = run_preflight(config)
        if not report.required_ok:
            print(format_report(report))
            return 1
        return _download(engine, args.url, args.mode or config.download.mode)

    if args.command == "batch":
        report = run_preflight(config)
        if not report.required_ok:
            print(format_report(report))
            return 1
        version = next(
            (check.version or "" for check in report.tools if check.name == "yt-dlp"),
            "",
        )
        return _batch(engine, config, args, engine_version=version)

    return 2
