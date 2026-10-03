# VideoDownloader v5

Windows용 영상 다운로더의 재구현 프로젝트입니다. 기존 단일 스크립트에 결합되어 있던 UI, `yt-dlp`, 브라우저 캡처, 기록 기능을 분리해서 구현합니다.

현재 상태는 **12단계 일반 파일 일괄 다운로드까지 구현 완료**입니다. URL 입력, 최고 화질 영상·오디오 선택, 영상 및 일반 파일 일괄 다운로드, 저장 폴더, 정보 확인, 진행률, 취소, 로그인 프로필과 선택적 브라우저 캡처를 한 화면에서 사용할 수 있으며 콘솔 없는 Windows 실행 파일을 제공합니다.

## 가장 쉬운 사용법: GUI

[GUI 배포 ZIP](https://github.com/spelld77/something-useful/releases/download/video-downloader-v0.5.3/VideoDownloader-GUI-v0.5.3-windows.zip)을 압축 해제하고 다음 파일을 더블클릭합니다.

```text
VideoDownloader\VideoDownloader.exe
```

1. 영상 URL을 붙여 넣습니다.
2. `영상 (MP4)` 또는 `오디오 (MP3)`를 선택합니다.
3. 영상은 `최고 화질`, 최대 4K·1440p·1080p·720p 또는 `MP4 호환 우선` 중 하나를 선택합니다.
4. 필요하면 저장 폴더를 변경합니다.
5. `정보 확인` 또는 `다운로드`를 누릅니다.
6. 완료 후 실제 해상도, FPS, 영상·오디오 코덱과 컨테이너를 결과에서 확인합니다.
7. 여러 영상 URL은 `영상 일괄 다운로드` 탭에 한 줄씩 입력합니다.
8. ZIP, PDF, 이미지, 문서나 직접 파일 URL은 `파일 일괄 다운로드` 탭에 한 줄씩 입력합니다.

로그인이 필요한 콘텐츠는 `로그인 브라우저`와 본인 프로필을 선택합니다. 일반 분석으로 영상을 찾지 못하거나 임시 브라우저에서 로그인·재생해야 하는 웹사이트는 `일반 분석 실패 시 브라우저에서 영상 주소 찾기`를 켭니다. 이 기능은 화면 녹화가 아니라 브라우저의 HLS/DASH 네트워크 요청을 찾는 기능이며 DRM은 우회하지 않습니다. YouTube에는 이 캡처 경로를 적용하지 않습니다.

처음부터 웹페이지를 열어 영상을 재생해야 하는 일반 사이트는 `웹 재생으로 다운로드`를 누릅니다. 열린 임시 브라우저에서 재생하고, 광고가 있으면 광고가 끝나 본편이 실제로 시작된 뒤 GUI의 `본편 재생 중`을 누릅니다. 광고가 없는 사이트에서는 영상이 시작되자마자 누르면 됩니다. 이 선택은 현재 단일 작업에만 적용되며 일반 다운로드, Enter, 정보 확인과 일괄 다운로드에는 영향을 주지 않습니다.

브라우저 주소창에 붙여 넣으면 곧바로 파일이 내려오는 URL이 여러 개라면 `파일 일괄 다운로드` 탭을 사용합니다. URL 목록을 붙여 넣거나 TXT로 불러오고 저장 폴더와 동시 다운로드 수 1~4개를 선택합니다. 서버가 제공한 원본 파일을 변환 없이 저장하며, `.part` 부분 파일, 이어받기, 리다이렉트, 파일명 충돌 방지, 무응답 감지와 자동 재시도, 실패 항목 다시 시도와 항목별 진행 상태를 지원합니다. 완료 후 `완료 항목 지우기` 또는 `작업 초기화`로 앱을 재시작하지 않고 다음 목록을 처리할 수 있습니다. 로그인 쿠키나 JavaScript 실행이 필요한 다운로드 페이지는 초기 일반 파일 경로의 지원 대상이 아닙니다.

## 개발 환경

- Python 3.12 이상
- `yt-dlp` 실행 파일
- `ffmpeg`와 `ffprobe`
- YouTube JavaScript challenge 처리를 위한 Deno 권장
- Node를 사용할 경우 엔진이 `--js-runtimes node`를 자동 명시

## 시작하기

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item config.example.toml config.toml
.\.venv\Scripts\video-downloader doctor
```

브라우저 캡처 기능도 사용할 경우 선택 의존성을 설치합니다.

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev,browser]"
```

소스에서 GUI를 실행하려면 GUI 선택 의존성을 설치합니다.

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev,browser,gui]"
.\.venv\Scripts\video-downloader-gui.exe
```

## Windows 배포판

개발 환경에서 wheel, Windows ZIP, SHA-256 체크섬을 한 번에 생성합니다.

```powershell
.\.venv\Scripts\python scripts\build_release.py
```

생성 결과는 `dist`에 저장됩니다. ZIP을 새 폴더에 푼 다음 기본 설치는 `install.ps1`, 브라우저 캡처 포함 설치는 `install.ps1 -BrowserCapture`로 실행합니다. 설치 스크립트는 배포 폴더 안에 `.venv`를 만들고 `config.toml`이 없을 때만 예제 설정을 복사합니다. `yt-dlp`, FFmpeg, FFprobe는 시스템에서 별도로 사용할 수 있어야 합니다.

GUI 실행 파일과 GUI 배포 ZIP은 다음 명령으로 생성합니다.

```powershell
.\.venv\Scripts\python -m pip install -e ".[browser,gui,packaging]"
.\.venv\Scripts\python scripts\build_gui_release.py
```

설치하지 않고 확인하려면 다음 명령을 사용할 수 있습니다.

```powershell
$env:PYTHONPATH = "src"
python -m videodownloader doctor
python -m unittest discover -s tests -v
```

## 사용법

```powershell
# 실행 환경 확인
.\.venv\Scripts\video-downloader doctor

# 필수 도구와 핵심 보안·오류 처리 정책 종합 점검
.\.venv\Scripts\video-downloader self-check

# 설치된 버전 확인
.\.venv\Scripts\video-downloader --version

# 다운로드 전 제목, 재생시간, 형식 수 확인
.\.venv\Scripts\video-downloader probe "https://example.com/video"

# 최고 품질 영상+오디오 다운로드 후 MP4 병합
.\.venv\Scripts\video-downloader download --video "https://example.com/video"

# 최대 1080p 또는 H.264/AAC 호환 우선 다운로드
.\.venv\Scripts\video-downloader download --video --quality 1080p "https://example.com/video"
.\.venv\Scripts\video-downloader download --video --quality compatible "https://example.com/video"

# 최고 품질 오디오를 MP3로 변환
.\.venv\Scripts\video-downloader download --audio "https://example.com/video"

# 로그인 권한이 필요한 영상에 사용자가 선택한 Chrome 프로필 사용
.\.venv\Scripts\video-downloader probe --browser chrome --profile "Profile 2" "https://example.com/private-video"
.\.venv\Scripts\video-downloader download --video --browser chrome --profile "Profile 2" "https://example.com/private-video"

# 예제 목록을 복사해 일괄 다운로드
Copy-Item urls.example.txt urls.txt
.\.venv\Scripts\video-downloader batch urls.txt --video

# 완료 이력을 무시하고 다시 처리하거나 작업 간격 변경
.\.venv\Scripts\video-downloader batch urls.txt --audio --no-resume --delay 5

# 실패 목록을 그대로 다시 입력
.\.venv\Scripts\video-downloader batch failed_urls.txt --video

# 직접 추출 실패 시 Chrome 임시 프로필에서 로그인·재생 후 HLS/DASH 감지
.\.venv\Scripts\video-downloader download --video --browser-capture --capture-browser chrome "https://example.com/video-page"
```

기본 저장 위치는 `savedVideo`입니다. 같은 제목의 영상은 영상 ID를 파일명에 포함해 충돌을 피하며, 기존 파일은 기본적으로 덮어쓰지 않습니다.

`download.video_quality` 기본값은 `best`입니다. `2160p`, `1440p`, `1080p`, `720p`는 해당 높이를 넘지 않는 최상 형식을 선택하고, `compatible`은 H.264 영상과 AAC 오디오를 우선합니다. 서로 다른 화질의 일괄 작업은 별도 이력으로 취급합니다. 다운로드가 끝나면 FFprobe로 최종 파일을 다시 읽어 실제 해상도와 코덱을 표시합니다.

`youtube.js_runtime = "auto"`는 Deno, Node, QuickJS 순서로 지원 버전을 선택합니다. 원격 EJS 다운로드는 기본적으로 차단하며 `youtube.remote_ejs = true`를 명시한 경우에만 GitHub 구성요소를 허용합니다. 브라우저 쿠키 역시 `--browser` 또는 `[auth]` 설정으로 사용자가 선택한 경우에만 전달하고 쿠키 값은 출력하지 않습니다.

PO Token이 필요한 경우에는 수동 토큰을 로그나 설정에 저장하지 않고 별도 오류로 안내합니다. 자동 처리가 필요하면 신뢰할 수 있는 PO Token provider 플러그인을 별도 검토해야 합니다.

일괄 처리는 기본적으로 한 번에 한 건씩 실행하고 작업 사이에 2초 대기합니다. GUI는 현재 파일의 순번·진행률과 전체 처리 진행률을 분리해 표시하고, 각 URL의 완료·실패·건너뜀·취소 결과를 즉시 기록합니다. 화면 로그의 원본 URL에서는 사용자 정보, 쿼리와 조각 식별자를 제외합니다. 실패가 있어도 목록 끝까지 처리했다면 전체 진행률은 100%가 되며, 취소 시에는 취소된 현재 항목과 아직 시작하지 않은 항목을 구분합니다. `history.jsonl`에는 URL의 SHA-256 해시, 모드, 결과 파일, 오류 종류와 엔진 버전만 기록합니다. `failed_urls.txt`는 주석으로 실패 시각·이유를 적고 다음 줄에 재입력 가능한 URL을 저장하므로 `batch` 입력 파일로 바로 사용할 수 있습니다. Ctrl+C로 중단하면 현재 하위 프로세스를 종료하고 완료된 이력은 유지합니다.

일반 파일 일괄 다운로드의 기본 저장 위치는 `savedFiles`입니다. 파일명은 서버의 `Content-Disposition`, 최종 URL 경로, MIME 형식 순서로 결정하고 Windows에서 사용할 수 없는 문자와 경로 침범 요소를 제거합니다. 완료 이력에는 URL 원문 대신 해시만 저장하고, 실패한 원본 URL은 GUI가 열린 동안에만 다시 시도 목록으로 보관합니다. HTML 로그인·오류 페이지는 정상 파일로 완료 처리하지 않습니다.

브라우저 자동 폴백은 기본적으로 꺼져 있습니다. 사용자가 `--browser-capture`를 지정했거나 `[browser_capture] enabled = true`로 설정한 경우에만, 먼저 `yt-dlp` 직접 추출을 시도하고 실패한 일반 사이트에 한해 Chrome 또는 Edge를 엽니다. GUI의 명시적 `웹 재생으로 다운로드`는 이 설정과 무관하게 현재 단일 작업에만 적용됩니다. 개인 기본 프로필을 열지 않으며 매번 전용 임시 프로필을 생성합니다. 감지된 미디어 도메인에 속하는 쿠키만 권한을 제한한 임시 Netscape 쿠키 파일로 전달하고 즉시 삭제합니다. YouTube에는 이 우회 경로를 적용하지 않으며 DRM 라이선스 요청, `ContentProtection`, Widevine·PlayReady·FairPlay·SAMPLE-AES 신호가 발견되면 중단합니다.

probe와 다운로드에는 기본 30초 소켓 타임아웃, 전체·조각별 재시도, 재시도 간격이 적용됩니다. `[download]`의 `socket_timeout_seconds`, `retries`, `retry_sleep_seconds`로 조정할 수 있습니다. `self-check`는 외부 영상을 다운로드하지 않고 필수 도구, YouTube JavaScript 구성, URL 안전성, 비밀값 마스킹, 파일명 충돌 방지, 오류 분류, 네트워크 제한을 검사합니다.

## 문서

- [아키텍처 결정](docs/architecture.md)
- [구현 체크리스트](docs/implementation-plan.md)
- [인수 검증 절차](docs/acceptance.md)
- [일반 파일 일괄 다운로드 설계](docs/generic-file-batch-design.md)

## 범위

- 공개 영상과 사용자가 접근 권한을 가진 콘텐츠만 지원
- Widevine, FairPlay 등 DRM 우회는 지원하지 않음
- 쿠키는 필요한 경우에만 사용하고 로그에 기록하지 않음
