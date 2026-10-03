# VideoDownloader v5 아키텍처 결정

## 목표

기존 `05.VideoDownloader.py`를 직접 확장하지 않고 새 엔트리포인트로 재구현한다. 다운로드 엔진, 콘솔 UI, 브라우저 보조 추출, 설정, 기록을 분리하여 사이트나 `yt-dlp` 변경의 영향을 한 곳에 가둔다.

## 확인된 기존 문제

- 최근 실패 기록의 직접 원인은 YouTube 다운로드 중 `HTTP 403 Forbidden`이었다.
- FFmpeg/FFprobe와 기존 Python 문법은 정상이었다.
- YouTube JavaScript challenge용 EJS/runtime 구성이 불완전했다.
- YouTube와 일반 웹 HLS 추출이 한 함수에 결합되어 있었다.
- `except: pass`가 인증, 드라이버, 네트워크, DRM 오류를 숨겼다.
- Selenium과 `webdriver-manager`가 모든 실행의 필수 의존성이었다.
- TLS 검증 해제, FFmpeg 절대경로, 광범위한 쿠키 전달 등 안전하지 않은 기본값이 있었다.

## 핵심 결정

1. `yt-dlp` Python 내부 API가 아니라 외부 프로세스를 기본 엔진으로 사용한다.
2. 원본 페이지 URL을 먼저 `yt-dlp`에 전달한다.
3. 쿠키는 인증이 필요하고 사용자가 브라우저/프로필을 선택한 경우에만 쓴다.
4. 브라우저 네트워크 캡처는 직접 추출이 실패한 일반 사이트에만 선택적으로 사용한다.
5. DRM 보호 콘텐츠는 감지 후 명확히 중단하며 우회하지 않는다.
6. URL, 쿠키, 서명 토큰은 로그에서 마스킹한다.
7. 일괄 다운로드 동시성 기본값은 1이며, 실패가 다음 작업을 막지 않게 한다.

## 패키지 경계

```text
src/videodownloader/
  app.py                 CLI 진입점
  gui.py                 Windows GUI와 화면 상태 관리
  gui_workers.py         백그라운드 probe/download/batch 작업
  config.py              TOML 설정과 검증
  models.py              작업/결과/오류 모델
  preflight.py           도구와 저장 경로 사전진단
  engine/
    base.py              다운로드 엔진 계약
    factory.py           CLI와 GUI가 공유하는 엔진 조립
    ytdlp_process.py     외부 yt-dlp 어댑터
    browser_capture.py   선택적 HLS 감지
  service/
    probe.py             메타데이터/포맷 조회
    download.py          작업 상태 전이
    batch.py             일괄 처리와 재개
  storage/
    history.py           JSONL 이력
    naming.py            안전한 파일명과 중복 처리
```

현재 7단계까지 `app`, `gui`, `config`, `models`, `preflight`, 외부 `yt-dlp` 엔진, JavaScript runtime/EJS 진단, 일괄 처리, JSONL 이력, 실패 목록, 선택적 Chrome/Edge 네트워크 캡처, 릴리스 자체 점검과 Windows GUI 배포 묶음이 구현되어 있다.

브라우저 캡처는 Selenium Manager를 사용해 드라이버를 관리하고 DevTools Network 이벤트에서 HLS/DASH 후보를 수집한다. 개인 브라우저 프로필은 사용하지 않고 전용 임시 프로필을 생성하며, 캡처한 쿠키는 미디어 호스트와 도메인이 일치하는 항목만 임시 Netscape 파일로 전달한다. DRM 신호가 있으면 `DRM_PROTECTED`로 종료한다.

외부 네트워크 작업에는 소켓 타임아웃, 전체 요청 재시도, 조각 재시도를 동일하게 적용한다. `self-check`는 다운로드 없이 환경 의존성과 보안·오류 처리 불변 조건을 확인하므로 설치 직후와 배포 전에 반복 실행할 수 있다.

패키지 버전은 `videodownloader.__version__`을 단일 원본으로 사용한다. 배포 빌더는 wheel, 예제 설정, 설치 스크립트, 운영 문서, release manifest를 고정된 ZIP 항목 시각으로 묶고 wheel과 ZIP의 SHA-256 체크섬을 별도 생성한다. 외부 실행 파일은 라이선스와 업데이트 경계를 명확히 하기 위해 배포 ZIP에 포함하지 않는다.

GUI의 probe, 다운로드, 일괄 처리는 `QThread` 작업자로 실행하고 시그널로만 화면을 갱신해 메인 이벤트 루프가 멈추지 않게 한다. 취소 요청은 실행 중인 외부 프로세스와 브라우저 캡처까지 전달된다. GUI 배포판은 PyInstaller `onedir` 방식으로 만들며 Windows 시스템 ICU 전달 DLL을 잘못 가리는 동명 DLL은 빌드 후 제거한다.

영상 화질은 최고 화질, 높이 상한, MP4 호환 우선 정책 중 하나를 설정한다. 일괄 재개 키에는 URL 해시와 모드뿐 아니라 영상 화질도 포함하여 낮은 화질 작업이 높은 화질 작업을 잘못 건너뛰지 않게 한다. 다운로드 완료 후 FFprobe가 최종 파일을 검사하고 실제 해상도, FPS, 영상·오디오 코덱과 컨테이너를 `DownloadResult`로 반환한다.

일반 웹의 직접 파일은 extractor가 높이 정보를 제공하지 않을 수 있으므로 높이 상한 필터에서 미상 값을 허용하되, 높이가 알려진 형식에는 상한을 그대로 적용한다. 사용자가 브라우저 캡처를 명시적으로 켠 일반 사이트는 미지원 URL, 포맷 부재, HTTP 403뿐 아니라 인증 필요 결과에서도 임시 브라우저로 전환한다. YouTube는 이 전환 대상에서 제외한다.

단일 GUI 작업에서 사용자가 처음부터 임시 브라우저를 여는 `웹 재생으로 다운로드` 기능은 전용 작업자와 전용 캡처 엔진으로 구현되어 있다. 기존 다운로드 모드나 전역 설정에는 포함하지 않아 다운로드·Enter·probe·일괄·CLI 흐름을 변경하지 않는다. 광고가 있는 페이지에서는 사용자가 본편 시작을 확인한 뒤 그 시점에 가까운 비광고 HLS/DASH 후보를 선택한다. 상세 설계와 회귀 조건은 [웹 재생 다운로드 설계](web-playback-download-design.md)를 따른다.

## 처리 흐름

```text
URL 검증
  -> 사전진단
  -> 원본 URL probe
     -> 성공: 포맷 선택
     -> 인증 필요: 사용자 동의 후 쿠키로 1회 재시도
     -> 미지원 일반 사이트: 브라우저 캡처 선택
     -> DRM: 중단
  -> .part 다운로드
  -> FFmpeg 후처리
  -> 최종 파일 확정
  -> 이력 기록
```

## 상태와 오류

작업 상태는 `QUEUED -> PROBING -> WAITING_USER -> DOWNLOADING -> POSTPROCESSING -> COMPLETED`로 진행하며, 어느 단계에서든 `FAILED` 또는 `CANCELLED`로 끝날 수 있다.

주요 오류 코드는 의존성 누락, 미지원 URL, 인증 필요, 토큰 필요, HTTP 403, DRM, 포맷 부재, 일시적 네트워크 오류, 후처리 실패로 구분한다.
