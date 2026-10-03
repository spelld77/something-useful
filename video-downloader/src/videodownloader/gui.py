from __future__ import annotations

import argparse
import os
import sys
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from videodownloader import __version__
from videodownloader.config import (
    AuthConfig,
    BrowserCaptureConfig,
    ConfigError,
    FileDownloadConfig,
    Settings,
    load_config,
)
from videodownloader.engine.browser_capture import is_capture_blocked_url
from videodownloader.engine.http_file import format_bytes
from videodownloader.engine.ytdlp_process import (
    DownloadError,
    compact_format_rows,
    redact_sensitive,
    validate_url,
)
from videodownloader.gui_workers import (
    BatchThread,
    DownloadThread,
    FileBatchThread,
    OperationThread,
    ProbeThread,
    WebPlaybackDownloadThread,
)
from videodownloader.models import DownloadResult, ErrorKind, MediaInfo, ProbeResult
from videodownloader.preflight import format_report, run_preflight
from videodownloader.service.batch import BatchItemEvent, BatchItemStatus, BatchSummary

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
QUALITY_OPTIONS = (
    ("최고 화질", "best"),
    ("최대 4K (2160p)", "2160p"),
    ("최대 QHD (1440p)", "1440p"),
    ("최대 Full HD (1080p)", "1080p"),
    ("최대 HD (720p)", "720p"),
    ("MP4 호환 우선 (H.264/AAC)", "compatible"),
)
CODEC_LABELS = {
    "av1": "AV1",
    "avc1": "H.264 (AVC)",
    "h264": "H.264 (AVC)",
    "hevc": "H.265 (HEVC)",
    "h265": "H.265 (HEVC)",
    "vp9": "VP9",
    "aac": "AAC",
    "mp3": "MP3",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "flac": "FLAC",
}


def parse_url_text(text: str) -> tuple[tuple[str, ...], tuple[int, ...], int]:
    urls: list[str] = []
    invalid: list[int] = []
    seen: set[str] = set()
    duplicates = 0
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        value = raw_line.strip()
        if not value or value.startswith("#"):
            continue
        try:
            normalized = validate_url(value)
        except DownloadError:
            invalid.append(line_number)
            continue
        if normalized in seen:
            duplicates += 1
            continue
        seen.add(normalized)
        urls.append(normalized)
    return tuple(urls), tuple(invalid), duplicates


def format_media_summary(media_info: MediaInfo) -> str:
    details: list[str] = []
    if media_info.resolution:
        details.append(media_info.resolution)
    if media_info.fps is not None:
        fps = (
            str(int(media_info.fps))
            if media_info.fps.is_integer()
            else f"{media_info.fps:.2f}".rstrip("0").rstrip(".")
        )
        details.append(f"{fps} fps")
    if media_info.video_codec:
        details.append(CODEC_LABELS.get(media_info.video_codec.casefold(), media_info.video_codec))
    if media_info.audio_codec:
        details.append(CODEC_LABELS.get(media_info.audio_codec.casefold(), media_info.audio_codec))
    if media_info.container:
        details.append(media_info.container.upper())
    return " · ".join(details)


def format_url_for_display(url: str, *, max_length: int = 88) -> str:
    """Return a useful URL label without credentials, query values, or fragments."""
    parsed = urlsplit(url)
    host = parsed.hostname or "웹 주소"
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        port = ""
    label = f"{host}{port}{parsed.path or '/'}"
    if len(label) > max_length:
        return label[: max_length - 1] + "…"
    return label


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.base_settings = settings
        self.worker: OperationThread | None = None
        self._batch_index = 0
        self._batch_total = 0
        self._batch_processed = 0
        self._batch_succeeded = 0
        self._batch_failed = 0
        self._batch_skipped = 0
        self._batch_cancelled = 0
        self._file_rows: dict[int, int] = {}
        self._file_urls_by_index: dict[int, str] = {}
        self._file_progress_values: dict[int, float] = {}
        self._file_failed_urls: list[str] = []
        self.setWindowTitle(f"VideoDownloader v5 · {__version__}")
        self.resize(920, 760)
        self.setMinimumSize(760, 620)
        self._build_ui()
        self._apply_style()
        self._initial_state()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(18, 16, 18, 16)
        root_layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("VideoDownloader")
        title.setObjectName("title")
        subtitle = QLabel("URL을 붙여 넣고 원하는 형식으로 저장하세요")
        subtitle.setObjectName("subtitle")
        title_box = QVBoxLayout()
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        title_row.addLayout(title_box)
        title_row.addStretch()
        self.environment_button = QPushButton("환경 점검")
        self.environment_button.clicked.connect(self.check_environment)
        title_row.addWidget(self.environment_button)
        root_layout.addLayout(title_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._single_tab(), "단일 다운로드")
        self.tabs.addTab(self._batch_tab(), "영상 일괄 다운로드")
        self.tabs.addTab(self._file_batch_tab(), "파일 일괄 다운로드")
        self.tabs.currentChanged.connect(self._update_tab_visibility)
        root_layout.addWidget(self.tabs, 1)
        self.download_settings_group = self._settings_group()
        root_layout.addWidget(self.download_settings_group)
        root_layout.addWidget(self._progress_group())

        self.setCentralWidget(root)
        self.statusBar().showMessage("준비됨")

    def _single_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)

        url_label = QLabel("영상 URL")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=... 또는 영상 페이지 URL")
        self.url_edit.returnPressed.connect(self.start_download)
        layout.addWidget(url_label)
        layout.addWidget(self.url_edit)

        button_row = QHBoxLayout()
        self.probe_button = QPushButton("정보 확인")
        self.probe_button.clicked.connect(self.start_probe)
        self.web_download_button = QPushButton("웹 재생으로 다운로드")
        self.web_download_button.setToolTip(
            "일반 웹사이트를 임시 브라우저로 열어 본편 HLS/DASH 주소를 찾습니다."
        )
        self.web_download_button.clicked.connect(self.start_web_download)
        self.download_button = QPushButton("다운로드")
        self.download_button.setObjectName("primaryButton")
        self.download_button.clicked.connect(self.start_download)
        button_row.addStretch()
        button_row.addWidget(self.probe_button)
        button_row.addWidget(self.web_download_button)
        button_row.addWidget(self.download_button)
        layout.addLayout(button_row)

        self.info_output = QPlainTextEdit()
        self.info_output.setReadOnly(True)
        self.info_output.setPlaceholderText("정보 확인 결과와 다운로드 결과가 여기에 표시됩니다.")
        layout.addWidget(self.info_output, 1)
        return tab

    def _batch_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)

        heading = QHBoxLayout()
        heading.addWidget(QLabel("URL 목록 · 한 줄에 하나씩 입력"))
        heading.addStretch()
        load_button = QPushButton("파일 불러오기")
        load_button.clicked.connect(self.load_url_file)
        clear_button = QPushButton("비우기")
        clear_button.clicked.connect(lambda: self.batch_urls.clear())
        heading.addWidget(load_button)
        heading.addWidget(clear_button)
        layout.addLayout(heading)

        self.batch_urls = QPlainTextEdit()
        self.batch_urls.setPlaceholderText(
            "https://example.com/video-1\n"
            "https://example.com/video-2\n\n"
            "# 주석도 사용할 수 있습니다"
        )
        layout.addWidget(self.batch_urls, 2)

        batch_button_row = QHBoxLayout()
        self.resume_checkbox = QCheckBox("완료한 항목 건너뛰기")
        self.resume_checkbox.setChecked(self.base_settings.batch.resume)
        self.batch_button = QPushButton("일괄 다운로드 시작")
        self.batch_button.setObjectName("primaryButton")
        self.batch_button.clicked.connect(self.start_batch)
        batch_button_row.addWidget(self.resume_checkbox)
        batch_button_row.addStretch()
        batch_button_row.addWidget(self.batch_button)
        layout.addLayout(batch_button_row)

        self.batch_log = QPlainTextEdit()
        self.batch_log.setReadOnly(True)
        self.batch_log.setMaximumBlockCount(500)
        self.batch_log.setPlaceholderText("일괄 처리 진행 상황이 표시됩니다.")
        layout.addWidget(self.batch_log, 1)
        return tab

    def _file_batch_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)

        heading = QHBoxLayout()
        heading.addWidget(QLabel("파일 URL 목록 · 한 줄에 하나씩 입력"))
        heading.addStretch()
        load_button = QPushButton("TXT 불러오기")
        load_button.clicked.connect(self.load_file_url_list)
        clear_button = QPushButton("비우기")
        clear_button.clicked.connect(lambda: self.file_urls.clear())
        heading.addWidget(load_button)
        heading.addWidget(clear_button)
        layout.addLayout(heading)

        self.file_urls = QPlainTextEdit()
        self.file_urls.setPlaceholderText(
            "https://example.com/report.pdf\n"
            "https://example.com/archive.zip\n\n"
            "# 브라우저에서 바로 파일이 내려오는 HTTP/HTTPS 주소"
        )
        layout.addWidget(self.file_urls, 2)

        options = QGridLayout()
        self.file_save_dir_edit = QLineEdit(str(self.base_settings.file_download.save_dir))
        file_browse_button = QPushButton("찾아보기")
        file_browse_button.clicked.connect(self.choose_file_save_dir)
        options.addWidget(QLabel("저장 폴더"), 0, 0)
        options.addWidget(self.file_save_dir_edit, 0, 1, 1, 3)
        options.addWidget(file_browse_button, 0, 4)

        self.file_concurrency = QSpinBox()
        self.file_concurrency.setRange(1, 4)
        self.file_concurrency.setValue(self.base_settings.file_download.concurrency)
        self.file_concurrency.setToolTip("서버 차단을 줄이려면 1개부터 사용하세요.")
        self.file_resume_checkbox = QCheckBox("완료 파일 건너뛰기 · 부분 파일 이어받기")
        self.file_resume_checkbox.setChecked(self.base_settings.file_download.resume_partial)
        options.addWidget(QLabel("동시 다운로드"), 1, 0)
        options.addWidget(self.file_concurrency, 1, 1)
        options.addWidget(self.file_resume_checkbox, 1, 2, 1, 3)
        layout.addLayout(options)

        button_row = QHBoxLayout()
        self.file_retry_button = QPushButton("실패 항목 다시 시도")
        self.file_retry_button.setEnabled(False)
        self.file_retry_button.clicked.connect(self.retry_failed_files)
        self.file_clear_completed_button = QPushButton("완료 항목 지우기")
        self.file_clear_completed_button.setEnabled(False)
        self.file_clear_completed_button.clicked.connect(self.clear_completed_file_items)
        self.file_reset_button = QPushButton("작업 초기화")
        self.file_reset_button.setToolTip(
            "입력 목록과 화면 상태만 지웁니다. 받은 파일과 완료 이력은 유지합니다."
        )
        self.file_reset_button.clicked.connect(self.reset_file_batch_state)
        self.file_open_folder_button = QPushButton("저장 폴더 열기")
        self.file_open_folder_button.clicked.connect(self.open_file_save_dir)
        self.file_batch_button = QPushButton("파일 다운로드 시작")
        self.file_batch_button.setObjectName("primaryButton")
        self.file_batch_button.clicked.connect(self.start_file_batch)
        button_row.addWidget(self.file_retry_button)
        button_row.addWidget(self.file_clear_completed_button)
        button_row.addWidget(self.file_reset_button)
        button_row.addWidget(self.file_open_folder_button)
        button_row.addStretch()
        button_row.addWidget(self.file_batch_button)
        layout.addLayout(button_row)

        self.file_table = QTableWidget(0, 5)
        self.file_table.setHorizontalHeaderLabels(("#", "파일", "상태", "진행률", "속도"))
        self.file_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.file_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.file_table, 2)

        note = QLabel(
            "서버가 파일을 직접 반환하는 주소용입니다. 로그인·JavaScript가 필요한 주소나 "
            "영상 페이지는 기존 영상 다운로드를 사용하세요."
        )
        note.setWordWrap(True)
        note.setObjectName("hint")
        layout.addWidget(note)
        return tab

    def _settings_group(self) -> QGroupBox:
        group = QGroupBox("다운로드 설정")
        grid = QGridLayout(group)

        self.save_dir_edit = QLineEdit(str(self.base_settings.app.save_dir))
        browse_button = QPushButton("찾아보기")
        browse_button.clicked.connect(self.choose_save_dir)
        save_row = QHBoxLayout()
        save_row.addWidget(self.save_dir_edit, 1)
        save_row.addWidget(browse_button)
        grid.addWidget(QLabel("저장 폴더"), 0, 0)
        grid.addLayout(save_row, 0, 1, 1, 3)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("영상 (MP4)", "video")
        self.mode_combo.addItem("오디오 (MP3)", "audio")
        self.mode_combo.setCurrentIndex(0 if self.base_settings.download.mode == "video" else 1)
        self.mode_combo.currentIndexChanged.connect(self._update_quality_state)
        grid.addWidget(QLabel("저장 형식"), 1, 0)
        grid.addWidget(self.mode_combo, 1, 1)

        self.auth_browser_combo = QComboBox()
        for browser in BROWSERS:
            self.auth_browser_combo.addItem("사용 안 함" if browser == "none" else browser, browser)
        auth_index = self.auth_browser_combo.findData(self.base_settings.auth.browser)
        self.auth_browser_combo.setCurrentIndex(max(0, auth_index))
        self.auth_browser_combo.currentIndexChanged.connect(self._update_auth_state)
        self.profile_edit = QLineEdit(self.base_settings.auth.profile)
        self.profile_edit.setPlaceholderText("예: Default 또는 Profile 2")
        grid.addWidget(QLabel("로그인 브라우저"), 1, 2)
        grid.addWidget(self.auth_browser_combo, 1, 3)
        grid.addWidget(QLabel("브라우저 프로필"), 2, 0)
        grid.addWidget(self.profile_edit, 2, 1)

        self.quality_combo = QComboBox()
        for label, value in QUALITY_OPTIONS:
            self.quality_combo.addItem(label, value)
        quality_index = self.quality_combo.findData(self.base_settings.download.video_quality)
        self.quality_combo.setCurrentIndex(max(0, quality_index))
        grid.addWidget(QLabel("영상 화질"), 3, 0)
        grid.addWidget(self.quality_combo, 3, 1)

        self.capture_checkbox = QCheckBox("일반 분석 실패 시 브라우저에서 영상 주소 찾기")
        self.capture_checkbox.setChecked(self.base_settings.browser_capture.enabled)
        self.capture_browser_combo = QComboBox()
        self.capture_browser_combo.addItem("Chrome", "chrome")
        self.capture_browser_combo.addItem("Edge", "edge")
        capture_index = self.capture_browser_combo.findData(
            self.base_settings.browser_capture.browser
        )
        self.capture_browser_combo.setCurrentIndex(max(0, capture_index))
        grid.addWidget(QLabel("웹 재생 브라우저"), 3, 2)
        grid.addWidget(self.capture_browser_combo, 3, 3)
        grid.addWidget(self.capture_checkbox, 4, 2, 1, 2)

        note = QLabel(
            "브라우저 캡처는 화면 녹화가 아니라 재생 중인 HLS/DASH "
            "네트워크 주소를 찾는 기능입니다. "
            "DRM 콘텐츠는 다운로드하지 않습니다."
        )
        note.setWordWrap(True)
        note.setObjectName("hint")
        grid.addWidget(note, 5, 0, 1, 4)
        return group

    def _progress_group(self) -> QGroupBox:
        group = QGroupBox("작업 상태")
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self.progress_label = QLabel("대기 중")
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_operation)
        self.confirm_content_button = QPushButton("본편 재생 중")
        self.confirm_content_button.setToolTip(
            "광고가 끝나고 본편 영상이 실제로 재생되기 시작하면 누르세요."
        )
        self.confirm_content_button.setVisible(False)
        self.confirm_content_button.setEnabled(False)
        self.confirm_content_button.clicked.connect(self.confirm_main_content)
        row.addWidget(self.progress_label, 1)
        row.addWidget(self.confirm_content_button)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.batch_progress_label = QLabel("전체 진행")
        self.batch_progress_bar = QProgressBar()
        self.batch_progress_bar.setRange(0, 100)
        self.batch_progress_bar.setValue(0)
        self.batch_progress_label.setVisible(False)
        self.batch_progress_bar.setVisible(False)
        layout.addWidget(self.batch_progress_label)
        layout.addWidget(self.batch_progress_bar)
        return group

    def _apply_style(self) -> None:
        style_sheet = """
            QMainWindow { background: #f5f7fb; }
            QWidget { font-family: "Malgun Gothic"; font-size: 10pt; color: #172033; }
            QDialog, QMessageBox { background-color: #f5f7fb; }
            QMessageBox QLabel { color: #172033; background-color: transparent; }
            QLabel#title { font-size: 22pt; font-weight: 700; color: #14213d; }
            QLabel#subtitle, QLabel#hint { color: #667085; }
            QGroupBox { background: white; border: 1px solid #d9e0ea; border-radius: 9px;
                        margin-top: 10px; padding: 12px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QTableWidget {
                background-color: #ffffff; color: #172033; border: 1px solid #cdd5df;
                border-radius: 6px; padding: 7px; selection-background-color: #dbe7ff;
                selection-color: #14213d;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus,
            QTableWidget:focus { border: 1px solid #356ae6; }
            QTableWidget {
                gridline-color: #d9e0ea; padding: 0;
                alternate-background-color: #f8fafc;
            }
            QTableWidget::item { background-color: #ffffff; color: #172033; padding: 5px; }
            QTableWidget::item:alternate { background-color: #f8fafc; }
            QTableWidget::item:selected { background-color: #dbe7ff; color: #14213d; }
            QHeaderView::section { background-color: #e9eef5; color: #172033;
                                   border: none; border-right: 1px solid #cdd5df;
                                   border-bottom: 1px solid #cdd5df; padding: 6px;
                                   font-weight: 600; }
            QTableCornerButton::section { background-color: #e9eef5;
                                          border: 1px solid #cdd5df; }
            QPushButton { background: #eef2f7; border: 1px solid #cdd5df; border-radius: 6px;
                          padding: 7px 13px; }
            QPushButton:hover { background: #e1e8f2; }
            QPushButton:disabled { color: #98a2b3; background: #f2f4f7; }
            QPushButton#primaryButton { background: #356ae6; color: white; border: none;
                                        font-weight: 600; padding: 8px 18px; }
            QPushButton#primaryButton:hover { background: #2857c5; }
            QProgressBar { border: 1px solid #cdd5df; border-radius: 6px; text-align: center;
                           background: #eef2f7; min-height: 20px; }
            QProgressBar::chunk { background: #356ae6; border-radius: 5px; }
            QTabWidget::pane { background: white; border: 1px solid #d9e0ea; border-radius: 8px; }
            QTabBar::tab { padding: 8px 18px; background: #e9eef5; margin-right: 2px; }
            QTabBar::tab:selected { background: white; color: #2857c5; font-weight: 600; }
            """
        application = QApplication.instance()
        if application is not None:
            application.setStyleSheet(style_sheet)
        else:
            self.setStyleSheet(style_sheet)

    def _initial_state(self) -> None:
        self._update_auth_state()
        self._update_quality_state()
        self._update_tab_visibility(self.tabs.currentIndex())

    @Slot(int)
    def _update_tab_visibility(self, index: int) -> None:
        self.download_settings_group.setVisible(index != 2)

    def current_settings(self) -> Settings:
        save_dir_text = self.save_dir_edit.text().strip() or "savedVideo"
        browser = str(self.auth_browser_combo.currentData())
        profile = self.profile_edit.text().strip() if browser != "none" else ""
        capture = BrowserCaptureConfig(
            enabled=self.capture_checkbox.isChecked(),
            browser=str(self.capture_browser_combo.currentData()),
            timeout_seconds=self.base_settings.browser_capture.timeout_seconds,
            interactive_timeout_seconds=(
                self.base_settings.browser_capture.interactive_timeout_seconds
            ),
            grace_seconds=self.base_settings.browser_capture.grace_seconds,
        )
        return replace(
            self.base_settings,
            app=replace(self.base_settings.app, save_dir=Path(save_dir_text)),
            download=replace(
                self.base_settings.download,
                mode=str(self.mode_combo.currentData()),
                video_quality=str(self.quality_combo.currentData()),
            ),
            auth=AuthConfig(browser=browser, profile=profile),
            browser_capture=capture,
            batch=replace(self.base_settings.batch, resume=self.resume_checkbox.isChecked()),
            file_download=FileDownloadConfig(
                save_dir=Path(self.file_save_dir_edit.text().strip() or "savedFiles"),
                history_file=self.base_settings.file_download.history_file,
                concurrency=self.file_concurrency.value(),
                retries=self.base_settings.file_download.retries,
                connect_timeout_seconds=(self.base_settings.file_download.connect_timeout_seconds),
                read_timeout_seconds=self.base_settings.file_download.read_timeout_seconds,
                resume_partial=self.file_resume_checkbox.isChecked(),
            ),
        )

    @Slot()
    def choose_save_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "저장 폴더 선택",
            str(Path(self.save_dir_edit.text() or ".").expanduser().resolve()),
        )
        if selected:
            self.save_dir_edit.setText(selected)

    @Slot()
    def load_url_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "URL 목록 불러오기", "", "텍스트 (*.txt);;모든 파일 (*)"
        )
        if not path:
            return
        try:
            self.batch_urls.setPlainText(Path(path).read_text(encoding="utf-8-sig"))
        except OSError as exc:
            self._show_error(f"파일을 읽을 수 없습니다: {exc}")

    @Slot()
    def choose_file_save_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "일반 파일 저장 폴더 선택",
            str(Path(self.file_save_dir_edit.text() or ".").expanduser().resolve()),
        )
        if selected:
            self.file_save_dir_edit.setText(selected)

    @Slot()
    def load_file_url_list(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "파일 URL 목록 불러오기", "", "텍스트 (*.txt);;모든 파일 (*)"
        )
        if not path:
            return
        try:
            self.file_urls.setPlainText(Path(path).read_text(encoding="utf-8-sig"))
        except OSError as exc:
            self._show_error(f"파일을 읽을 수 없습니다: {exc}")

    @Slot()
    def open_file_save_dir(self) -> None:
        directory = Path(self.file_save_dir_edit.text().strip() or "savedFiles")
        try:
            directory = directory.expanduser().resolve()
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._show_error(f"저장 폴더를 열 수 없습니다: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    @Slot()
    def retry_failed_files(self) -> None:
        if not self._file_failed_urls:
            self._show_error("다시 시도할 실패 항목이 없습니다.")
            return
        self.file_urls.setPlainText("\n".join(self._file_failed_urls))
        self.start_file_batch()

    @Slot()
    def clear_completed_file_items(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        completed_statuses = {"완료", "완료 이력으로 건너뜀"}
        removed = 0
        for row in range(self.file_table.rowCount() - 1, -1, -1):
            status_item = self.file_table.item(row, 2)
            if status_item is None or status_item.text() not in completed_statuses:
                continue
            index_item = self.file_table.item(row, 0)
            if index_item is not None:
                with suppress(ValueError):
                    index = int(index_item.text())
                    self._file_urls_by_index.pop(index, None)
                    self._file_progress_values.pop(index, None)
            self.file_table.removeRow(row)
            removed += 1
        self._rebuild_file_row_map()
        self.file_clear_completed_button.setEnabled(self._has_completed_file_items())
        message = (
            f"완료 항목 {removed}개를 화면에서 지웠습니다."
            if removed
            else "화면에 지울 완료 항목이 없습니다."
        )
        self.statusBar().showMessage(message)

    @Slot()
    def reset_file_batch_state(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.file_urls.clear()
        self.file_table.setRowCount(0)
        self._file_rows.clear()
        self._file_urls_by_index.clear()
        self._file_progress_values.clear()
        self._file_failed_urls.clear()
        self._batch_index = 0
        self._batch_total = 0
        self._batch_processed = 0
        self._batch_succeeded = 0
        self._batch_failed = 0
        self._batch_skipped = 0
        self._batch_cancelled = 0
        self.progress_label.setText("대기 중")
        self.progress_bar.setValue(0)
        self.batch_progress_label.setText("전체 진행")
        self.batch_progress_bar.setValue(0)
        self.batch_progress_label.setVisible(False)
        self.batch_progress_bar.setVisible(False)
        self.file_retry_button.setEnabled(False)
        self.file_clear_completed_button.setEnabled(False)
        self.statusBar().showMessage(
            "파일 일괄 작업을 초기화했습니다. 받은 파일과 완료 이력은 유지됩니다."
        )

    def _rebuild_file_row_map(self) -> None:
        self._file_rows.clear()
        for row in range(self.file_table.rowCount()):
            item = self.file_table.item(row, 0)
            if item is None:
                continue
            with suppress(ValueError):
                self._file_rows[int(item.text())] = row

    def _has_completed_file_items(self) -> bool:
        completed_statuses = {"완료", "완료 이력으로 건너뜀"}
        return any(
            (item := self.file_table.item(row, 2)) is not None and item.text() in completed_statuses
            for row in range(self.file_table.rowCount())
        )

    @Slot()
    def start_probe(self) -> None:
        url = self.url_edit.text().strip()
        if not self._valid_url_or_warn(url):
            return
        worker = ProbeThread(self.current_settings(), url)
        worker.probe_ready.connect(self._probe_finished)
        worker.error.connect(self._operation_error)
        self._start_worker(worker, "영상 정보를 확인하고 있습니다...")

    @Slot()
    def start_download(self) -> None:
        url = self.url_edit.text().strip()
        if not self._valid_url_or_warn(url):
            return
        settings = self.current_settings()
        worker = DownloadThread(settings, url, str(self.mode_combo.currentData()))
        worker.progress_changed.connect(self._update_progress)
        worker.result_ready.connect(self._download_finished)
        self._start_worker(worker, "다운로드를 시작합니다...")

    @Slot()
    def start_web_download(self) -> None:
        url = self.url_edit.text().strip()
        if not self._valid_url_or_warn(url):
            return
        if is_capture_blocked_url(url):
            self._show_error("YouTube는 일반 다운로드를 사용하세요.")
            return
        if self.worker is not None and self.worker.isRunning():
            self._show_error("이미 실행 중인 작업이 있습니다.")
            return
        settings = self.current_settings()
        worker = WebPlaybackDownloadThread(
            settings,
            url,
            str(self.mode_combo.currentData()),
        )
        worker.browser_ready.connect(self._web_browser_ready)
        worker.progress_changed.connect(self._update_progress)
        worker.result_ready.connect(self._download_finished)
        self.confirm_content_button.setVisible(True)
        self.confirm_content_button.setEnabled(False)
        self._start_worker(worker, "웹 재생 브라우저를 준비하고 있습니다...")

    @Slot()
    def _web_browser_ready(self) -> None:
        if not isinstance(self.worker, WebPlaybackDownloadThread):
            return
        self.confirm_content_button.setEnabled(True)
        message = "브라우저에서 영상을 재생하세요. 광고가 있으면 본편이 시작될 때까지 기다리세요."
        self.progress_label.setText(message)
        self.statusBar().showMessage(message)

    @Slot()
    def confirm_main_content(self) -> None:
        if not isinstance(self.worker, WebPlaybackDownloadThread):
            return
        self.confirm_content_button.setEnabled(False)
        self.worker.confirm_main_content()

    @Slot()
    def start_batch(self) -> None:
        urls, invalid, duplicates = parse_url_text(self.batch_urls.toPlainText())
        if invalid:
            self._show_error("유효하지 않은 URL 줄: " + ", ".join(map(str, invalid)))
            return
        if not urls:
            self._show_error("다운로드할 URL을 한 개 이상 입력하세요.")
            return
        self.batch_log.clear()
        if duplicates:
            self.batch_log.appendPlainText(f"중복 URL {duplicates}개를 제외했습니다.")
        settings = self.current_settings()
        worker = BatchThread(settings, urls, str(self.mode_combo.currentData()))
        worker.item_started.connect(self._batch_item_started)
        worker.item_finished.connect(self._batch_item_finished)
        worker.progress_changed.connect(self._update_progress)
        worker.summary_ready.connect(self._batch_finished)
        self._reset_batch_progress(len(urls))
        self.batch_log.appendPlainText(f"처리 대상 {len(urls)}개를 확인했습니다.")
        if settings.browser_capture.enabled:
            self.batch_log.appendPlainText(
                "안내: 일반 분석에 실패한 항목에서는 웹 재생 브라우저가 열릴 수 있습니다."
            )
        self._start_worker(worker, f"일괄 다운로드 {len(urls)}개를 시작합니다...")

    @Slot()
    def start_file_batch(self) -> None:
        urls, invalid, duplicates = parse_url_text(self.file_urls.toPlainText())
        if invalid:
            self._show_error("유효하지 않은 URL 줄: " + ", ".join(map(str, invalid)))
            return
        if not urls:
            self._show_error("다운로드할 파일 URL을 한 개 이상 입력하세요.")
            return
        if self.worker is not None and self.worker.isRunning():
            self._show_error("이미 실행 중인 작업이 있습니다.")
            return

        self._prepare_file_table(urls)
        self._file_failed_urls = []
        self.file_retry_button.setEnabled(False)
        settings = self.current_settings()
        worker = FileBatchThread(settings, urls)
        worker.item_started.connect(self._file_item_started)
        worker.progress_changed.connect(self._file_progress_changed)
        worker.item_finished.connect(self._file_item_finished)
        worker.summary_ready.connect(self._file_batch_finished)
        self._reset_batch_progress(len(urls))
        message = f"일반 파일 {len(urls)}개 다운로드를 시작합니다."
        if duplicates:
            message += f" 중복 {duplicates}개 제외"
        self._start_worker(worker, message)

    def _start_worker(self, worker: OperationThread, message: str) -> None:
        if self.worker is not None and self.worker.isRunning():
            self._show_error("이미 실행 중인 작업이 있습니다.")
            return
        self.worker = worker
        worker.status_changed.connect(self._status_changed)
        worker.finished.connect(self._worker_finished)
        self._set_busy(True)
        self.progress_bar.setValue(0)
        if not isinstance(worker, (BatchThread, FileBatchThread)):
            self.batch_progress_label.setVisible(False)
            self.batch_progress_bar.setVisible(False)
        self.progress_label.setText(message)
        self.statusBar().showMessage(message)
        worker.start()

    @Slot()
    def cancel_operation(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.cancel_button.setEnabled(False)
            self.worker.cancel()

    @Slot(object)
    def _probe_finished(self, result: ProbeResult) -> None:
        formats = compact_format_rows(result.formats)
        duration = "알 수 없음" if result.duration is None else f"{int(result.duration)}초"
        self.info_output.setPlainText(
            "\n".join(
                (
                    f"제목: {result.title}",
                    f"게시자: {result.uploader or '알 수 없음'}",
                    f"재생시간: {duration}",
                    f"영상 ID: {result.id or '알 수 없음'}",
                    f"사용 가능한 형식: {len(formats)}개",
                )
            )
        )
        self.progress_label.setText("정보 확인 완료")

    @Slot(object)
    def _download_finished(self, result: DownloadResult) -> None:
        if result.success:
            self.progress_bar.setValue(100)
            path_text = str(result.output_path) if result.output_path else "저장 경로를 확인하세요."
            lines = ["다운로드 완료", path_text]
            if result.media_info is not None:
                summary = format_media_summary(result.media_info)
                if summary:
                    lines.append(f"실제 결과: {summary}")
            message = "\n".join(lines)
            self.info_output.appendPlainText(message)
            self.progress_label.setText("다운로드 완료")
            self.statusBar().showMessage(message.replace("\n", " · "))
            return
        if result.error_kind == ErrorKind.CANCELLED:
            self.progress_label.setText("작업이 취소되었습니다.")
            self.statusBar().showMessage(result.message)
            return
        self._operation_error(f"[{result.error_kind}] {result.message}")

    @Slot(int, int, str)
    def _batch_item_started(self, index: int, total: int, url: str) -> None:
        self._batch_index = index
        self._batch_total = total
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"현재 {index}/{total} · 다운로드 준비 중")
        self.batch_log.appendPlainText(f"[{index}/{total}] 시작: {format_url_for_display(url)}")
        self._update_batch_overall_progress()

    @Slot(object)
    def _batch_item_finished(self, event: BatchItemEvent) -> None:
        self._batch_index = event.index
        self._batch_total = event.total
        self._batch_processed += 1
        url_label = format_url_for_display(event.url)

        if event.status == BatchItemStatus.SUCCEEDED:
            self._batch_succeeded += 1
            self.progress_bar.setValue(100)
            output = event.result.output_path if event.result is not None else None
            detail = str(output) if output is not None else url_label
            self.batch_log.appendPlainText(f"[{event.index}/{event.total}] 완료: {detail}")
        elif event.status == BatchItemStatus.FAILED:
            self._batch_failed += 1
            result = event.result
            kind = result.error_kind if result is not None else ErrorKind.UNKNOWN
            raw_message = result.message if result is not None else "원인을 확인할 수 없습니다."
            message = redact_sensitive(raw_message, source_url=event.url)
            self.batch_log.appendPlainText(
                f"[{event.index}/{event.total}] 실패 ({kind}): {message}"
            )
        elif event.status == BatchItemStatus.SKIPPED:
            self._batch_skipped += 1
            self.batch_log.appendPlainText(
                f"[{event.index}/{event.total}] 완료 이력으로 건너뜀: {url_label}"
            )
        else:
            self._batch_cancelled += 1
            self.batch_log.appendPlainText(f"[{event.index}/{event.total}] 사용자 취소")

        self._update_batch_overall_progress()

    @Slot(object)
    def _batch_finished(self, summary: BatchSummary) -> None:
        self._batch_processed = summary.processed
        self._batch_succeeded = summary.succeeded
        self._batch_failed = summary.failed
        self._batch_skipped = summary.skipped
        self._batch_cancelled = summary.cancelled_items
        message = (
            f"처리 {summary.processed}/{summary.total} · 성공 {summary.succeeded} · "
            f"실패 {summary.failed} · 건너뜀 {summary.skipped}"
        )
        if summary.cancelled:
            message += " · 사용자 취소"
            if summary.cancelled_items:
                message += f" · 취소 항목 {summary.cancelled_items}"
            message += f" · 미처리 {summary.unprocessed}"
        else:
            message = "완료: " + message
        self.batch_log.appendPlainText(message)
        for warning in summary.warnings:
            self.batch_log.appendPlainText(f"경고: {warning}")
        self.progress_label.setText(message)
        self._update_batch_overall_progress(force_complete=not summary.cancelled)

    def _prepare_file_table(self, urls: tuple[str, ...]) -> None:
        self.file_table.setRowCount(len(urls))
        self._file_rows = {}
        self._file_urls_by_index = {}
        self._file_progress_values = {}
        for row, url in enumerate(urls):
            index = row + 1
            self._file_rows[index] = row
            self._file_urls_by_index[index] = url
            self._file_progress_values[index] = 0.0
            values = (
                str(index),
                format_url_for_display(url),
                "대기",
                "0%",
                "",
            )
            for column, value in enumerate(values):
                self.file_table.setItem(row, column, QTableWidgetItem(value))

    @Slot(int, int, str)
    def _file_item_started(self, index: int, total: int, _url: str) -> None:
        self._set_file_table_text(index, 2, "연결 중")
        self.progress_label.setText(f"파일 일괄 다운로드 · 처리 {self._batch_processed}/{total}")

    @Slot(object)
    def _file_progress_changed(self, progress: dict[str, object]) -> None:
        index = int(progress.get("index") or 0)
        if index not in self._file_rows:
            return
        phase = str(progress.get("phase") or "downloading")
        attempt = int(progress.get("attempt") or 1)
        max_attempts = int(progress.get("max_attempts") or 1)
        if phase == "connecting":
            status = f"연결 중 ({attempt}/{max_attempts})"
        elif phase == "waiting":
            idle_seconds = int(progress.get("idle_seconds") or 0)
            status = f"응답 대기 {idle_seconds}초"
        elif phase == "retrying":
            retry_in = progress.get("retry_in_seconds")
            suffix = f" · {retry_in}초 후" if retry_in is not None else ""
            status = f"재시도 대기 ({attempt}/{max_attempts}){suffix}"
        else:
            status = "받는 중"
        filename = str(progress.get("filename") or "")
        if filename:
            self._set_file_table_text(index, 1, filename)
        self._set_file_table_text(index, 2, status)
        percent_value = progress.get("percent")
        downloaded = progress.get("downloaded_bytes")
        if isinstance(percent_value, (int, float)):
            percent = max(0.0, min(100.0, float(percent_value)))
            progress_text = f"{percent:.0f}%"
            self._file_progress_values[index] = percent
            self._set_file_table_text(index, 3, progress_text)
        elif isinstance(downloaded, int):
            self._set_file_table_text(index, 3, format_bytes(downloaded))
        if "speed" in progress:
            self._set_file_table_text(index, 4, str(progress.get("speed") or ""))
        self._update_file_overall_progress()

    @Slot(object)
    def _file_item_finished(self, event: BatchItemEvent) -> None:
        self._batch_processed += 1
        self._file_progress_values[event.index] = 100.0
        result = event.result
        if event.status == BatchItemStatus.SUCCEEDED:
            self._batch_succeeded += 1
            self._set_file_table_text(event.index, 2, "완료")
            self._set_file_table_text(event.index, 3, "100%")
            if result is not None and result.output_path is not None:
                self._set_file_table_text(event.index, 1, result.output_path.name)
                item = self.file_table.item(self._file_rows[event.index], 1)
                if item is not None:
                    item.setToolTip(str(result.output_path))
        elif event.status == BatchItemStatus.SKIPPED:
            self._batch_skipped += 1
            self._set_file_table_text(event.index, 2, "완료 이력으로 건너뜀")
            self._set_file_table_text(event.index, 3, "100%")
        elif event.status == BatchItemStatus.CANCELLED:
            self._batch_cancelled += 1
            self._set_file_table_text(event.index, 2, "취소")
        else:
            self._batch_failed += 1
            self._file_failed_urls.append(event.url)
            self._set_file_table_text(event.index, 2, "실패")
            if result is not None:
                item = self.file_table.item(self._file_rows[event.index], 2)
                if item is not None:
                    item.setToolTip(redact_sensitive(result.message, source_url=event.url))
        self._update_file_overall_progress()

    @Slot(object)
    def _file_batch_finished(self, summary: BatchSummary) -> None:
        self._batch_processed = summary.processed
        self._batch_succeeded = summary.succeeded
        self._batch_failed = summary.failed
        self._batch_skipped = summary.skipped
        self._batch_cancelled = summary.cancelled_items
        message = (
            f"파일 처리 {summary.processed}/{summary.total} · 성공 {summary.succeeded} · "
            f"실패 {summary.failed} · 건너뜀 {summary.skipped}"
        )
        if summary.cancelled:
            message += f" · 사용자 취소 · 미처리 {summary.unprocessed}"
        else:
            message = "완료: " + message
        if summary.warnings:
            warning = redact_sensitive(summary.warnings[0])
            message += f" · 경고: {warning}"
        for index, row in self._file_rows.items():
            item = self.file_table.item(row, 2)
            if item is None or item.text() not in {"대기", "연결 중"}:
                continue
            if summary.cancelled:
                item.setText("미처리")
            else:
                item.setText("실패")
                url = self._file_urls_by_index.get(index)
                if url and url not in self._file_failed_urls:
                    self._file_failed_urls.append(url)
        self.progress_label.setText(message)
        self.statusBar().showMessage(message)
        self._update_file_overall_progress(force_complete=not summary.cancelled)
        self.file_clear_completed_button.setEnabled(self._has_completed_file_items())

    def _set_file_table_text(self, index: int, column: int, value: str) -> None:
        row = self._file_rows.get(index)
        if row is None:
            return
        item = self.file_table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            self.file_table.setItem(row, column, item)
        item.setText(value)

    def _update_file_overall_progress(self, *, force_complete: bool = False) -> None:
        total = self._batch_total
        if force_complete:
            percent = 100
        elif total:
            percent = int(sum(self._file_progress_values.values()) / total)
        else:
            percent = 0
        self.progress_bar.setValue(percent)
        self.batch_progress_bar.setValue(percent)
        label = (
            f"전체 {self._batch_processed}/{total} · 성공 {self._batch_succeeded} · "
            f"실패 {self._batch_failed} · 건너뜀 {self._batch_skipped}"
        )
        if self._batch_cancelled:
            label += f" · 취소 {self._batch_cancelled}"
        self.batch_progress_label.setText(label)

    def _reset_batch_progress(self, total: int) -> None:
        self._batch_index = 0
        self._batch_total = total
        self._batch_processed = 0
        self._batch_succeeded = 0
        self._batch_failed = 0
        self._batch_skipped = 0
        self._batch_cancelled = 0
        self.batch_progress_label.setVisible(True)
        self.batch_progress_bar.setVisible(True)
        self._update_batch_overall_progress()

    def _update_batch_overall_progress(
        self,
        *,
        current_percent: int = 0,
        force_complete: bool = False,
    ) -> None:
        total = self._batch_total
        if force_complete:
            percent = 100
        elif total:
            fractional_item = current_percent / 100 if self._batch_index else 0.0
            percent = int(min(100, (self._batch_processed + fractional_item) * 100 / total))
        else:
            percent = 0
        self.batch_progress_bar.setValue(percent)
        label = (
            f"전체 {self._batch_processed}/{total} · 성공 {self._batch_succeeded} · "
            f"실패 {self._batch_failed} · 건너뜀 {self._batch_skipped}"
        )
        if self._batch_cancelled:
            label += f" · 취소 {self._batch_cancelled}"
        self.batch_progress_label.setText(label)

    @Slot(object)
    def _update_progress(self, progress: dict[str, object]) -> None:
        percent_text = str(progress.get("percent") or "").strip().removesuffix("%")
        try:
            percent = max(0, min(100, int(float(percent_text))))
        except ValueError:
            percent = self.progress_bar.value()
        self.progress_bar.setValue(percent)
        speed = str(progress.get("speed") or "알 수 없음")
        eta = str(progress.get("eta") or "알 수 없음")
        if isinstance(self.worker, BatchThread):
            self.progress_label.setText(
                f"현재 {self._batch_index}/{self._batch_total} · {percent}% · "
                f"속도 {speed} · 남은 시간 {eta}"
            )
            self._update_batch_overall_progress(current_percent=percent)
        else:
            self.progress_label.setText(f"{percent}% · 속도 {speed} · 남은 시간 {eta}")

    @Slot(str)
    def _status_changed(self, message: str) -> None:
        if isinstance(self.worker, BatchThread) and self._batch_index:
            self.progress_label.setText(f"현재 {self._batch_index}/{self._batch_total} · {message}")
        else:
            self.progress_label.setText(message)
        self.statusBar().showMessage(message)

    @Slot(str)
    def _operation_error(self, message: str) -> None:
        self.progress_label.setText("작업 실패")
        self.info_output.appendPlainText(message)
        self.statusBar().showMessage(message)

    @Slot()
    def _worker_finished(self) -> None:
        worker = self.worker
        self.worker = None
        self.confirm_content_button.setEnabled(False)
        self.confirm_content_button.setVisible(False)
        self._set_busy(False)
        self.file_retry_button.setEnabled(bool(self._file_failed_urls))
        self.file_clear_completed_button.setEnabled(self._has_completed_file_items())
        if worker is not None:
            worker.deleteLater()

    def _set_busy(self, busy: bool) -> None:
        self.probe_button.setEnabled(not busy)
        self.download_button.setEnabled(not busy)
        self.web_download_button.setEnabled(not busy)
        self.batch_button.setEnabled(not busy)
        self.file_batch_button.setEnabled(not busy)
        self.file_retry_button.setEnabled(not busy and bool(self._file_failed_urls))
        self.file_clear_completed_button.setEnabled(not busy and self._has_completed_file_items())
        self.file_reset_button.setEnabled(not busy)
        self.file_open_folder_button.setEnabled(not busy)
        self.file_concurrency.setEnabled(not busy)
        self.file_resume_checkbox.setEnabled(not busy)
        self.environment_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def _valid_url_or_warn(self, url: str) -> bool:
        try:
            validate_url(url)
        except DownloadError as exc:
            self._show_error(exc.message)
            return False
        return True

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "VideoDownloader", message)

    @Slot()
    def check_environment(self) -> None:
        report = run_preflight(self.current_settings())
        text = format_report(report)
        if report.required_ok:
            QMessageBox.information(self, "환경 점검", text)
        else:
            QMessageBox.warning(self, "환경 점검", text)

    @Slot()
    def _update_auth_state(self) -> None:
        enabled = self.auth_browser_combo.currentData() != "none"
        self.profile_edit.setEnabled(enabled)
        if not enabled:
            self.profile_edit.clear()

    @Slot()
    def _update_quality_state(self) -> None:
        self.quality_combo.setEnabled(self.mode_combo.currentData() == "video")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "작업 취소",
                "실행 중인 작업을 취소하고 종료할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.cancel()
            if not self.worker.wait(5000):
                event.ignore()
                self.statusBar().showMessage(
                    "작업 종료를 기다리고 있습니다. 잠시 후 다시 시도하세요."
                )
                return
        event.accept()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="video-downloader-gui")
    parser.add_argument("--config", default="config.toml", help="설정 파일 경로")
    parser.add_argument("--version", action="store_true", help="버전 표시")
    return parser


def main(argv: list[str] | None = None) -> int:
    if getattr(sys, "frozen", False):
        os.chdir(Path(sys.executable).resolve().parent)
    args = build_parser().parse_args(argv)
    if args.version:
        if sys.stdout is not None:
            print(f"video-downloader-gui {__version__}")
        return 0
    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("VideoDownloader")
    application.setApplicationVersion(__version__)
    try:
        settings = load_config(args.config)
    except ConfigError as exc:
        QMessageBox.critical(None, "설정 오류", str(exc))
        return 2
    window = MainWindow(settings)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
