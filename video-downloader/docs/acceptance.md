# 인수 검증 절차

이 문서는 공개 콘텐츠와 사용자가 접근 권한을 가진 콘텐츠만 대상으로 한다. DRM 우회나 타인의 로그인 정보 사용은 검증 범위에 포함하지 않는다.

## 자동 검증

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\ruff.exe format --check src tests
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\python -m pytest --cov=videodownloader --cov-report=term-missing
.\.venv\Scripts\video-downloader doctor
.\.venv\Scripts\video-downloader self-check
.\.venv\Scripts\video-downloader --version
```

GUI 자동 테스트는 동일한 pytest 실행에 포함된다. 화면을 직접 띄우지 않는 CI 환경에서는 Qt의 offscreen 플랫폼을 사용한다.

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python -m pytest
Remove-Item Env:QT_QPA_PLATFORM
```

## 배포 산출물 검증

```powershell
.\.venv\Scripts\python scripts\build_release.py
Get-Content dist\SHA256SUMS.txt
Get-FileHash -Algorithm SHA256 dist\*.whl, dist\*.zip
```

ZIP에는 wheel, `install.ps1`, 예제 설정과 URL 목록, README, 운영 문서, `release-manifest.json`이 있어야 한다. 빈 폴더에 ZIP을 푼 뒤 `install.ps1`을 실행하고 `.\.venv\Scripts\video-downloader.exe --version`과 `self-check`가 성공하는지 확인한다.

GUI 배포판은 별도로 빌드하고 실행 여부를 확인한다.

```powershell
.\.venv\Scripts\python scripts\build_gui_release.py
Test-Path build\gui\dist\VideoDownloader\VideoDownloader.exe
Test-Path dist\VideoDownloader\_internal\icuuc.dll  # False여야 함
$process = Start-Process build\gui\dist\VideoDownloader\VideoDownloader.exe -PassThru
Start-Sleep -Seconds 4
$process.Refresh()
$process.Responding
Stop-Process -Id $process.Id
```

`VideoDownloader-GUI-v<버전>-windows.zip`에는 `VideoDownloader/VideoDownloader.exe`, 기본 설정, 예제 URL, README, release manifest가 있어야 한다. GUI에서 환경 점검을 실행해 외부 `yt-dlp`, FFmpeg, FFprobe 설치 상태를 확인한다.

자동 테스트가 검증하는 완료 기준:

| 완료 기준 | 검증 위치 |
| --- | --- |
| 인증 필요 콘텐츠 | 인증 오류 분류와 사용자 선택 브라우저·프로필 인자 테스트 |
| 지원되지 않는 URL | URL 검증과 `UNSUPPORTED_URL` 결과 테스트 |
| DRM 콘텐츠 | manifest·라이선스 감지와 다운로드 중단 테스트 |
| 네트워크 중단 | `NETWORK_TRANSIENT` 분류와 CLI 실패 종료 코드 테스트 |
| FFmpeg 누락·후처리 실패 | 사전진단 및 오류 분류 테스트 |
| 중복 파일명 | 영상 ID 포함 템플릿과 덮어쓰기 방지 인자 테스트 |
| 일괄 실패 격리·재개 | 성공·실패 혼합 처리와 완료 이력 건너뛰기 테스트 |
| 화질 선택 | 최고 화질·높이 상한·MP4 호환 우선 포맷 선택 테스트 |
| 실제 결과 정보 | FFprobe JSON 파싱과 GUI 해상도·코덱 표시 테스트 |
| 명시적 웹 재생 | 사용자 확인 전 다운로드 금지, 광고 후보 제외, YouTube 사전 차단 테스트 |
| 일괄 진행 가시성 | 현재/전체 진행률 분리, 항목별 결과, 취소·미처리 집계와 URL 마스킹 테스트 |
| 일반 파일 일괄 다운로드 | 직접 파일·리다이렉트·이어받기·충돌·HTML 오인·취소와 동시 처리 테스트 |

## 실제 미디어 점검

아래 `<...>` 값은 검증자가 접근 권한을 가진 URL로 바꾼다. 저장 결과를 쉽게 정리할 수 있도록 별도의 임시 설정 파일에서 `app.save_dir`을 지정하는 것을 권장한다.

```powershell
# 공개 YouTube 메타데이터와 영상
.\.venv\Scripts\video-downloader probe "<PUBLIC_YOUTUBE_URL>"
.\.venv\Scripts\video-downloader download --video "<PUBLIC_YOUTUBE_URL>"

# 사용자가 로그인 권한을 가진 콘텐츠
.\.venv\Scripts\video-downloader download --video --browser chrome --profile "<PROFILE>" "<AUTHORIZED_URL>"

# 직접 HLS manifest
.\.venv\Scripts\video-downloader download --video "<DIRECT_M3U8_URL>"

# 직접 MPEG-DASH manifest
.\.venv\Scripts\video-downloader download --video "<DIRECT_MPD_URL>"

# 일반 웹페이지의 선택적 HLS/DASH 캡처
.\.venv\Scripts\video-downloader download --video --browser-capture --capture-browser chrome "<AUTHORIZED_PAGE_URL>"
```

GUI에서 처음부터 웹 재생이 필요한 일반 페이지를 검증한다.

1. URL을 입력하고 `웹 재생으로 다운로드`를 누른다.
2. 열린 임시 브라우저에서 재생 버튼을 누른다.
3. 광고가 있으면 광고가 끝나 본편이 실제로 시작될 때까지 기다린다.
4. GUI에서 `본편 재생 중`을 누른다.
5. 브라우저가 닫힌 뒤 본편 다운로드와 실제 결과 정보 표시를 확인한다.

YouTube URL에서는 임시 브라우저가 열리지 않고 일반 다운로드를 사용하라는 안내가 나와야 한다. 광고가 없는 사이트는 영상 시작 직후 `본편 재생 중`을 누른다. DRM 신호가 있는 콘텐츠는 다운로드하지 않아야 한다.

GUI의 `파일 일괄 다운로드` 탭에서는 공개 직접 파일 URL 여러 개를 한 줄에 하나씩 입력한다. 저장 폴더와 동시 다운로드 수를 선택한 뒤 시작하고, 항목 표에 파일명·상태·진행률·속도가 개별 표시되는지 확인한다. 같은 파일명을 반환하는 두 URL은 서로 다른 이름으로 저장되어야 한다. 작업을 취소했다가 같은 목록을 다시 시작하면 `.part`를 이어받고, 실패 항목 다시 시도 버튼에는 실패한 URL만 들어가야 한다. 서버 응답이 지연되면 `응답 대기`와 `재시도 대기` 상태가 표시되어야 한다. 완료 후 `완료 항목 지우기`와 `작업 초기화`가 앱 재시작 없이 동작해야 하며, 초기화해도 받은 파일과 완료 이력은 유지되어야 한다. 로그인 HTML을 반환하는 URL은 정상 파일로 완료 처리하지 않아야 한다.

성공 시 종료 코드는 `0`이고 최종 저장 경로가 출력되어야 한다. 실패 시 종료 코드는 `1`이며 인증, DRM, 네트워크, 포맷, 의존성 중 해당 오류 종류가 출력되어야 한다. 검증 후 임시 저장 폴더, `history.jsonl`, `failed_urls.txt`를 확인하고 필요한 결과만 보관한다.
