from __future__ import annotations

import base64
import json
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from videodownloader.engine.ytdlp_process import validate_url
from videodownloader.models import ErrorKind

HLS_MIME_TYPES = {
    "application/mpegurl",
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
}
DASH_MIME_TYPES = {"application/dash+xml"}
DRM_MARKERS = (
    "com.apple.streamingkeydelivery",
    "contentprotection",
    "playready",
    "skd://",
    "urn:uuid:",
    "widevine",
    "#ext-x-key:method=sample-aes",
)
DRM_URL_MARKERS = ("/license", "drm-license", "playready", "widevine", "fairplay")
AD_URL_MARKERS = ("/ads/", "/ad/", "doubleclick", "googlesyndication", "preroll", "vast")

StatusCallback = Callable[[str], None]


class BrowserCaptureError(RuntimeError):
    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True, slots=True)
class CapturedCookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = False
    expires: int = 0
    http_only: bool = False


@dataclass(frozen=True, slots=True)
class MediaCandidate:
    url: str
    mime_type: str = ""
    status: int = 0
    is_master: bool = False
    drm_detected: bool = False
    first_seen_at: float = 0.0
    last_seen_at: float = 0.0
    sequence: int = 0


@dataclass(frozen=True, slots=True)
class CaptureResult:
    source_url: str
    media_url: str
    page_title: str
    user_agent: str
    cookies: tuple[CapturedCookie, ...]

    @property
    def http_headers(self) -> tuple[tuple[str, str], ...]:
        source = urlsplit(self.source_url)
        origin = f"{source.scheme}://{source.netloc}"
        return (
            ("Referer", self.source_url),
            ("Origin", origin),
            ("User-Agent", self.user_agent),
        )


def parse_performance_entry(entry: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    try:
        message = json.loads(entry["message"])["message"]
        method = message["method"]
        params = message["params"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(method, str) or not isinstance(params, dict):
        return None
    return method, params


def contains_drm(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in DRM_MARKERS)


def url_indicates_drm(url: str) -> bool:
    lowered = url.casefold()
    return any(marker in lowered for marker in DRM_URL_MARKERS)


def url_indicates_ad(url: str) -> bool:
    lowered = url.casefold()
    return any(marker in lowered for marker in AD_URL_MARKERS)


def is_capture_blocked_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    blocked_domains = ("youtube.com", "youtu.be", "youtube-nocookie.com")
    return any(host == domain or host.endswith(f".{domain}") for domain in blocked_domains)


def media_candidate(url: str, mime_type: str = "", status: int = 0) -> MediaCandidate | None:
    lowered_url = url.casefold()
    normalized_mime = mime_type.split(";", 1)[0].strip().casefold()
    is_hls = ".m3u8" in lowered_url or normalized_mime in HLS_MIME_TYPES
    is_dash = ".mpd" in lowered_url or normalized_mime in DASH_MIME_TYPES
    if not (is_hls or is_dash) or status >= 400:
        return None
    return MediaCandidate(url=url, mime_type=normalized_mime, status=status)


def select_candidate(candidates: list[MediaCandidate]) -> MediaCandidate | None:
    usable = [candidate for candidate in candidates if not candidate.drm_detected]
    if not usable:
        return None

    def score(candidate: MediaCandidate) -> int:
        lowered = candidate.url.casefold()
        value = 100 if candidate.is_master else 0
        value += 40 if ".m3u8" in lowered else 10
        value += 15 if "master" in lowered else 0
        value -= 200 if any(marker in lowered for marker in AD_URL_MARKERS) else 0
        return value

    return max(usable, key=score)


def select_confirmed_candidate(
    candidates: list[MediaCandidate],
    *,
    confirmed_at: float,
    lookback_seconds: float = 20.0,
    proximity_seconds: float = 3.0,
) -> MediaCandidate | None:
    usable = [
        candidate
        for candidate in candidates
        if not candidate.drm_detected and not url_indicates_ad(candidate.url)
    ]
    if not usable:
        return None

    recent = [
        candidate
        for candidate in usable
        if candidate.last_seen_at == 0 or candidate.last_seen_at >= confirmed_at - lookback_seconds
    ]
    pool = recent or usable
    newest = max(candidate.last_seen_at for candidate in pool)
    nearest = [
        candidate for candidate in pool if newest - candidate.last_seen_at <= proximity_seconds
    ]
    return select_candidate(nearest)


def _cookie_from_selenium(payload: dict[str, Any]) -> CapturedCookie | None:
    try:
        name = str(payload["name"])
        value = str(payload["value"])
        domain = str(payload["domain"])
    except KeyError:
        return None
    if not name or not domain or any(character in name + value + domain for character in "\t\r\n"):
        return None
    expiry = payload.get("expiry")
    return CapturedCookie(
        name=name,
        value=value,
        domain=domain,
        path=str(payload.get("path") or "/"),
        secure=bool(payload.get("secure", False)),
        expires=int(expiry) if isinstance(expiry, (int, float)) else 0,
        http_only=bool(payload.get("httpOnly", False)),
    )


def cookies_for_url(
    cookies: tuple[CapturedCookie, ...], target_url: str
) -> tuple[CapturedCookie, ...]:
    parsed = urlsplit(target_url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path or "/"
    secure_request = parsed.scheme == "https"
    matched: list[CapturedCookie] = []
    for cookie in cookies:
        domain = cookie.domain.lstrip(".").casefold()
        domain_matches = host == domain or host.endswith(f".{domain}")
        path_matches = path.startswith(cookie.path or "/")
        secure_matches = not cookie.secure or secure_request
        if domain_matches and path_matches and secure_matches:
            matched.append(cookie)
    return tuple(matched)


@contextmanager
def scoped_cookie_file(
    cookies: tuple[CapturedCookie, ...],
    target_url: str,
    directory: Path,
) -> Iterator[Path | None]:
    scoped = cookies_for_url(cookies, target_url)
    if not scoped:
        yield None
        return

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f".browser-cookies-{uuid.uuid4().hex}.txt"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as cookie_file:
            cookie_file.write("# Netscape HTTP Cookie File\n")
            for cookie in scoped:
                domain = f"#HttpOnly_{cookie.domain}" if cookie.http_only else cookie.domain
                include_subdomains = "TRUE" if cookie.domain.startswith(".") else "FALSE"
                secure = "TRUE" if cookie.secure else "FALSE"
                cookie_file.write(
                    "\t".join(
                        (
                            domain,
                            include_subdomains,
                            cookie.path or "/",
                            secure,
                            str(cookie.expires),
                            cookie.name,
                            cookie.value,
                        )
                    )
                    + "\n"
                )
        path.chmod(0o600)
        yield path
    finally:
        path.unlink(missing_ok=True)
        with suppress(OSError):
            directory.rmdir()


class BrowserCapture:
    def __init__(
        self,
        *,
        browser: str = "chrome",
        timeout_seconds: int = 90,
        interactive_timeout_seconds: int = 180,
        grace_seconds: float = 3.0,
        status_callback: StatusCallback | None = None,
        headless: bool = False,
        profile_root: Path | None = None,
    ) -> None:
        self.browser = browser
        self.timeout_seconds = timeout_seconds
        self.interactive_timeout_seconds = interactive_timeout_seconds
        self.grace_seconds = grace_seconds
        self.status_callback = status_callback
        self.headless = headless
        self.profile_root = profile_root or Path.cwd() / ".browser-profiles"
        self._cancel_requested = threading.Event()
        self._driver_lock = threading.Lock()
        self._current_driver: Any | None = None

    def cancel(self) -> None:
        self._cancel_requested.set()
        with self._driver_lock:
            driver = self._current_driver
        if driver is not None:
            with suppress(Exception):
                driver.quit()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested.is_set():
            raise BrowserCaptureError(
                ErrorKind.CANCELLED,
                "사용자 요청으로 브라우저 캡처를 취소했습니다.",
            )

    def capture(
        self,
        source_url: str,
        *,
        confirmation_event: threading.Event | None = None,
        ready_callback: Callable[[], None] | None = None,
    ) -> CaptureResult:
        self._cancel_requested.clear()
        source_url = validate_url(source_url)
        driver: Any | None = None
        self.profile_root.mkdir(parents=True, exist_ok=True)
        profile_dir = Path(tempfile.mkdtemp(prefix="capture-", dir=self.profile_root))
        try:
            driver = self._create_driver(profile_dir)
            with self._driver_lock:
                self._current_driver = driver
            driver.set_page_load_timeout(min(self.timeout_seconds, 30))
            driver.execute_cdp_cmd("Network.enable", {})
            self._status("브라우저에서 필요한 로그인 후 영상을 재생하세요.")
            try:
                driver.get(source_url)
            except Exception as exc:
                self._raise_if_cancelled()
                if exc.__class__.__name__ != "TimeoutException":
                    raise

            self._raise_if_cancelled()
            if ready_callback is not None:
                ready_callback()
            candidates, confirmed_at = self._collect_candidates(
                driver,
                confirmation_event=confirmation_event,
            )
            selected = (
                select_confirmed_candidate(
                    list(candidates.values()),
                    confirmed_at=confirmed_at,
                )
                if confirmed_at is not None
                else select_candidate(list(candidates.values()))
            )
            if selected is None:
                message = (
                    "광고가 아닌 본편 HLS/DASH 요청을 찾지 못했습니다."
                    if confirmation_event is not None
                    else "브라우저에서 HLS/DASH 미디어 요청을 찾지 못했습니다."
                )
                raise BrowserCaptureError(
                    ErrorKind.UNSUPPORTED_URL,
                    message,
                )
            if selected.drm_detected:
                raise BrowserCaptureError(
                    ErrorKind.DRM_PROTECTED,
                    "DRM 보호 신호가 감지되어 다운로드를 중단했습니다.",
                )

            raw_cookies = driver.get_cookies()
            cookies = tuple(
                cookie
                for payload in raw_cookies
                if isinstance(payload, dict)
                if (cookie := _cookie_from_selenium(payload)) is not None
            )
            user_agent = str(driver.execute_script("return navigator.userAgent") or "")
            return CaptureResult(
                source_url=source_url,
                media_url=selected.url,
                page_title=str(driver.title or ""),
                user_agent=user_agent,
                cookies=cookies,
            )
        except BrowserCaptureError:
            raise
        except Exception as exc:
            self._raise_if_cancelled()
            raise BrowserCaptureError(
                ErrorKind.DEPENDENCY_MISSING,
                f"브라우저 캡처를 시작할 수 없습니다: {exc}",
            ) from exc
        finally:
            with self._driver_lock:
                self._current_driver = None
            if driver is not None:
                with suppress(Exception):
                    driver.quit()
            shutil.rmtree(profile_dir, ignore_errors=True)
            with suppress(OSError):
                self.profile_root.rmdir()

    def _create_driver(self, profile_dir: Path) -> Any:
        try:
            from selenium import webdriver
        except ImportError as exc:
            raise BrowserCaptureError(
                ErrorKind.DEPENDENCY_MISSING,
                "브라우저 캡처에는 selenium 선택 의존성이 필요합니다.",
            ) from exc

        if self.browser == "chrome":
            options = webdriver.ChromeOptions()
            driver_factory = webdriver.Chrome
        elif self.browser == "edge":
            options = webdriver.EdgeOptions()
            driver_factory = webdriver.Edge
        else:
            raise BrowserCaptureError(ErrorKind.DEPENDENCY_MISSING, "지원하지 않는 브라우저입니다.")

        options.page_load_strategy = "eager"
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--mute-audio")
        options.add_argument("--disable-notifications")
        options.add_argument("--no-first-run")
        if self.headless:
            options.add_argument("--headless=new")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        return driver_factory(options=options)

    def _collect_candidates(
        self,
        driver: Any,
        *,
        confirmation_event: threading.Event | None = None,
    ) -> tuple[dict[str, MediaCandidate], float | None]:
        timeout = (
            self.interactive_timeout_seconds
            if confirmation_event is not None
            else self.timeout_seconds
        )
        deadline = time.monotonic() + timeout
        first_candidate_at: float | None = None
        confirmed_at: float | None = None
        candidates: dict[str, MediaCandidate] = {}
        request_candidates: dict[str, MediaCandidate] = {}
        sequence = 0

        while time.monotonic() < deadline:
            self._raise_if_cancelled()
            now = time.monotonic()
            if (
                confirmation_event is not None
                and confirmed_at is None
                and confirmation_event.is_set()
            ):
                confirmed_at = now
                self._status("본편 미디어 요청을 확인하고 있습니다...")
            for entry in driver.get_log("performance"):
                parsed = parse_performance_entry(entry)
                if parsed is None:
                    continue
                method, params = parsed

                if method == "Network.requestWillBeSent":
                    request = params.get("request", {})
                    request_url = request.get("url", "") if isinstance(request, dict) else ""
                    if isinstance(request_url, str) and url_indicates_drm(request_url):
                        raise BrowserCaptureError(
                            ErrorKind.DRM_PROTECTED,
                            "DRM 라이선스 요청이 감지되어 다운로드를 중단했습니다.",
                        )

                if method == "Network.responseReceived":
                    response = params.get("response", {})
                    if not isinstance(response, dict):
                        continue
                    response_url = response.get("url", "")
                    if not isinstance(response_url, str):
                        continue
                    if url_indicates_drm(response_url):
                        raise BrowserCaptureError(
                            ErrorKind.DRM_PROTECTED,
                            "DRM 라이선스 응답이 감지되어 다운로드를 중단했습니다.",
                        )
                    candidate = media_candidate(
                        response_url,
                        str(response.get("mimeType") or ""),
                        int(response.get("status") or 0),
                    )
                    request_id = params.get("requestId")
                    if candidate is not None and isinstance(request_id, str):
                        sequence += 1
                        seen_at = time.monotonic()
                        previous = candidates.get(candidate.url)
                        candidate = replace(
                            candidate,
                            first_seen_at=(
                                previous.first_seen_at if previous is not None else seen_at
                            ),
                            last_seen_at=seen_at,
                            sequence=sequence,
                        )
                        candidates[candidate.url] = candidate
                        request_candidates[request_id] = candidate
                        first_candidate_at = first_candidate_at or time.monotonic()

                if method == "Network.loadingFinished":
                    request_id = params.get("requestId")
                    if not isinstance(request_id, str) or request_id not in request_candidates:
                        continue
                    candidate = request_candidates.pop(request_id)
                    body = self._response_body(driver, request_id)
                    updated = replace(
                        candidate,
                        is_master="#EXT-X-STREAM-INF" in body.upper(),
                        drm_detected=contains_drm(body),
                    )
                    if updated.drm_detected:
                        raise BrowserCaptureError(
                            ErrorKind.DRM_PROTECTED,
                            "미디어 manifest에서 DRM 보호 정보가 감지되었습니다.",
                        )
                    candidates[updated.url] = updated

            now = time.monotonic()
            if confirmation_event is None:
                if (
                    first_candidate_at is not None
                    and now - first_candidate_at >= self.grace_seconds
                ):
                    break
            elif confirmed_at is not None and now - confirmed_at >= self.grace_seconds:
                break
            time.sleep(0.25)
        if confirmation_event is not None and confirmed_at is None:
            raise BrowserCaptureError(
                ErrorKind.UNSUPPORTED_URL,
                "본편 재생 확인을 기다리는 시간이 초과되었습니다.",
            )
        return candidates, confirmed_at

    @staticmethod
    def _response_body(driver: Any, request_id: str) -> str:
        try:
            payload = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        except Exception:
            return ""
        body = payload.get("body", "") if isinstance(payload, dict) else ""
        if not isinstance(body, str):
            return ""
        if isinstance(payload, dict) and payload.get("base64Encoded"):
            try:
                return base64.b64decode(body).decode("utf-8", errors="replace")
            except (ValueError, UnicodeError):
                return ""
        return body

    def _status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)
