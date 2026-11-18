# SHIFT BRIDGE Portable

Windows에서 SHIFT BRIDGE와 자체 AI 엔진을 한 폴더로 옮겨 실행하는 패키지입니다.

웹앱과 터미널은 BridgeCLI를 통해 Gemini를 사용합니다. CLI는 인수인계, 문서 검색, 초안 승인처럼 DCO 업무에 맞춘 명령을 제공합니다. Windows에서 사용하거나 [Render 웹 파일럿](deploy/RENDER.md) 또는 [AWS 사설 웹 파일럿](deploy/README.md)을 배포할 수 있습니다.

## GitHub 자동 업로드

`Publish.bat`을 열어 두면 저장한 소스를 공개 저장소 `manychuhub/snake-game`의 `shift-bridge` 브랜치로 올립니다. 최초 GitHub 인증은 Git Credential Manager 안내에 따라 완료하세요. `Publish.bat --once`는 한 번 업로드하고 종료하며, 자동 업로드 종료는 `Ctrl+C`입니다. `publish.py`의 파일 목록에 포함된 UTF-8 소스만 처리합니다. 새 소스 파일을 추가할 때는 이 목록에도 해당 경로를 넣으세요.

| 경로 | 용도 |
|---|---|
| Start.bat | 웹앱과 엔진을 함께 시작 |
| Agent/ | 기본 Python 웹앱, 포트 8000 |
| test/ | 별도 검증용 Python 웹앱, 포트 8001 |
| BridgeCLI/ | CLI와 Gemini 호출 서버, 기본 포트 8011 |

## 다른 Windows 장치에서 실행

1. 폴더 전체를 복사 또는 압축 해제하고 Python 3.11 이상을 준비합니다.
2. Start.bat을 실행합니다. 로컬 인증 토큰이 비어 있으면 BridgeCLI/.env에 자동 생성됩니다. 첫 실행에서는 Python 패키지를 설치할 인터넷 연결이 필요합니다.
3. 브라우저에서 http://127.0.0.1:8000 에 접속합니다. Gemini 키를 설정하기 전에도 웹 화면을 확인할 수 있습니다.
4. AI 기능을 사용하려면 BridgeCLI/.env의 `GEMINI_API_KEY`에 본인의 키를 입력하고 Start.bat을 다시 실행합니다. 필요하면 `GEMINI_MODEL`도 지정합니다. 웹 상단의 BridgeCLI 상태 버튼에서 **연결 테스트**를 눌러 실제 Gemini 응답을 확인합니다.
5. 서버가 켜진 동안 별도 PowerShell에서 .\BridgeCLI\bridge.bat status 또는 .\BridgeCLI\bridge.bat chat "Reply with OK."를 실행합니다. 종료는 시작 창에서 Ctrl+C입니다.
6. 검증용 앱은 기본 앱을 끈 뒤 PowerShell에서 .\Start.bat test로 실행하고 http://127.0.0.1:8001 에 접속합니다.

## 웹과 CLI의 연결 범위

웹앱의 생성 요청은 인증된 로컬 API를 거쳐 BridgeCLI에 도착하고, BridgeCLI가 Gemini API를 호출합니다. 각 웹앱은 자체 SQLite에 기록과 보고서를 저장하며 CLI의 업무 명령도 별도 SQLite를 사용합니다. 웹과 CLI의 저장 데이터 및 승인 상태 동기화는 별도 작업입니다.

이 이동본에는 Python 웹앱과 BridgeCLI 소스를 담았습니다. 원본의 Render/Node.js 배포 파일, API 설정, 기존 DB, 업로드, 가상환경과 Git 이력은 제외했습니다. 기존 기록이 필요하면 앱을 종료하고 각 원본의 shift_bridge.db와 uploads, 또는 BridgeCLI의 data를 대응 폴더에 별도로 복사합니다. 첫 실행에서 웹앱은 기존 코드의 데모 데이터를 생성할 수 있습니다.
