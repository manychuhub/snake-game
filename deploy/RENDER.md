# SHIFT BRIDGE를 Render에 배포하기

## 기존 Web Service를 전환하는 경우

로그에 `branch main`, `Using Node.js`, `npm install`, `package.json` 오류가 함께 나오면 Render 서비스가 기존 Node 실행 설정을 사용 중입니다. **Environment**에서 아래 변수를 먼저 추가하고, **Settings → Build → Source → Edit**에서 소스 설정을 변경하세요. 같은 서비스를 전환하면 이미 사용 중인 이름과 주소를 계속 쓸 수 있습니다. 새 주소를 원하면 **New → Web Service → GitHub**에서 새 서비스를 만드세요. [Render 런타임 변경 안내](https://render.com/docs/native-runtimes#changing-a-services-runtime)

| Render 설정 | 입력값 |
| --- | --- |
| GitHub Repository | `manychuhub/snake-game` |
| Branch | `shift-bridge` |
| Language / Runtime | `Docker` |
| Root Directory | 비워 둠 |
| Dockerfile Path | `./Dockerfile` |
| Docker Command | 비워 둠 |
| Health Check Path | `/healthz` |
| Auto-Deploy | `On Commit` |

## Environment Variables

| 이름 | 값 |
| --- | --- |
| `SHIFT_BRIDGE_WEB_PASSWORD` | 이 서비스 전용 무작위 비밀번호. 24자 이상 |
| `SHIFT_BRIDGE_WEB_USER` | 선택 사항. 기본 사용자 이름 `operator` |
| `GEMINI_API_KEY` | AI 기능을 사용할 때 Render 대시보드에 직접 입력하는 Gemini 키 |
| `GEMINI_MODEL` | 선택 사항. 사용할 모델 ID |

비밀번호는 Windows PowerShell에서 `python -c "import secrets; print(secrets.token_urlsafe(32))"`로 생성해 비밀번호 관리자에 보관할 수 있습니다. `PORT`와 `RENDER_EXTERNAL_URL`은 Render 값을 사용합니다. BridgeCLI 인증 토큰은 서버 시작 시 생성됩니다. Gemini 키와 웹 비밀번호는 Render의 Environment에 입력합니다. [Render 환경변수 안내](https://render.com/docs/configure-environment-variables)

**Deploy**를 누른 뒤 Deploys 화면에서 **Live**를 확인합니다. `onrender.com` 주소를 열면 브라우저 로그인 창이 표시됩니다. 로그인 후 웹 상단의 **BridgeCLI → 연결 테스트**로 Gemini 응답을 확인하세요. 키 설정 전에는 로그인과 웹 화면을 확인할 수 있습니다.

## 기록 저장

무료 서비스는 재배포, 재시작 또는 절전 시 SQLite 기록을 잃을 수 있으므로 가상 데이터로 테스트하세요. 기록을 유지하려면 유료 서비스에 Persistent Disk를 `/var/data`에 마운트합니다. Render 웹 파일럿에는 브라우저 기본 인증을 사용하며 모든 사용자가 하나의 계정을 공유합니다. 실제 DCO 운영 자료를 사용하려면 조직에서 승인한 호스팅, 데이터 보존 정책과 Gemini 사용 범위를 확인하세요. [무료 서비스 제한](https://render.com/docs/free) · [Render Persistent Disk](https://render.com/docs/disks)
