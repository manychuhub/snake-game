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
| `SHIFT_BRIDGE_ADMIN_PASSWORD` | 이 서비스 전용 무작위 비밀번호. 24자 이상 |
| `SHIFT_BRIDGE_ADMIN_USER` | 선택 사항. 기본 사용자 이름 `admin` |
| `GEMINI_API_KEY` | AI 기능을 사용할 때 Render 대시보드에 직접 입력하는 Gemini 키 |
| `GEMINI_MODEL` | 선택 사항. 사용할 모델 ID |

비밀번호는 Windows PowerShell에서 `python -c "import secrets; print(secrets.token_urlsafe(32))"`로 생성해 비밀번호 관리자에 보관할 수 있습니다. `PORT`와 `RENDER_EXTERNAL_URL`은 Render 값을 사용합니다. BridgeCLI 인증 토큰은 서버 시작 시 생성됩니다. Gemini 키와 웹 비밀번호는 Render의 Environment에 입력합니다. [Render 환경변수 안내](https://render.com/docs/configure-environment-variables)

**Deploy**를 누른 뒤 Deploys 화면에서 **Live**를 확인합니다. `onrender.com`의 첫 화면과 `/about`은 공개 소개 페이지입니다. **업무 화면 둘러보기**를 누르면 `/demo`에서 가상 기록과 보고서로 대시보드를 볼 수 있습니다. **로그인**은 `/workspace`를 열며, 실제 기록과 Gemini 기능은 이 화면에서 사용합니다. 로그인 후 웹 상단의 **BridgeCLI → 연결 테스트**로 Gemini 응답을 확인하세요.

## 기록 저장

관리자는 **계정 설정**에서 비밀번호를 변경할 수 있습니다. SQLite 실행에서 관리자 초기 비밀번호를 관리하는 환경 변수는 `SHIFT_BRIDGE_ADMIN_USER`와 `SHIFT_BRIDGE_ADMIN_PASSWORD`입니다. Supabase 실행에서는 백업에서 가져온 로그인 정보와 사용자별 권한을 사용합니다. 관리자 비밀번호 재설정은 Supabase의 웹앱 연결을 사용해 `Agent/accounts.py <아이디> --reset-password`를 실행합니다. 모든 계정 관련 CLI 작업에서 비밀번호를 프롬프트에 입력합니다.

무료 Render 웹 서비스의 로컬 SQLite는 재배포, 재시작 또는 절전 시 사라질 수 있습니다. 무료 인스턴스에는 SSH와 Shell이 없으며, 현재 앱 API는 관리자에게 보이는 최근 업무 기록과 일부 메타데이터만 내보낼 수 있습니다. 기존 SQLite 파일을 확보하기 전에는 운영 서비스의 재배포나 플랜 변경을 보류합니다. [무료 서비스 제한](https://render.com/docs/free) · [Shell 지원 범위](https://render.com/docs/ssh)

## Supabase로 이전하기

1. 원본 파일에 접근할 수 있는 환경에서 아래 명령으로 복사합니다. Windows에서는 경로를 해당 복사본의 실제 위치로 바꿉니다. SQLite Backup API로 파일마다 일관된 복사본을 만들고 무결성과 SHA-256을 검증합니다. 파일 간 시점을 맞추려면 승인된 쓰기 중지 상태에서 최종 백업을 생성합니다. 백업에는 비밀번호 해시와 업무 데이터가 포함되므로 비공개 저장소에 보관합니다.

   ```bash
   python deploy/sqlite_backup.py --web-db /var/data/web/shift_bridge.db \
     --engine-db /var/data/engine/bridge.db --output /private/shift-bridge-backup
   PYTHONPATH=. python deploy/import_sqlite.py /private/shift-bridge-backup
   ```

2. Supabase의 비어 있는 테스트 프로젝트에서 [스키마 마이그레이션](../supabase/migrations/20261120000100_shift_bridge_storage.sql)을 트랜잭션으로 적용합니다. `shift_bridge_web`과 `shift_bridge_engine`에 각각 `LOGIN`을 부여하고 `psql`의 `\password`로 별도 비밀번호를 설정합니다. HTTPS API 키 대신 PostgreSQL 연결을 사용합니다. IPv4 연결에는 Connect 패널의 **Session pooler**를 선택하고, 역할별 접속으로 `sslmode=verify-full`과 Supabase CA 인증서를 사용합니다. [Supabase Postgres 연결](https://supabase.com/docs/guides/database/connecting-to-postgres)

3. 대상과 원본을 검토한 뒤 스키마 소유자 연결을 `SHIFT_BRIDGE_MIGRATION_DATABASE_URL`에 비공개로 설정하고 복원합니다. 대상 테이블이 비어 있어야 합니다. 계정 ID, 비밀번호 해시, 계정 설정, 관리자 이력, 개인·공용 업무 기록, 보고서, 문서, 감사 이력과 BridgeCLI 데이터를 이전합니다. 이전 SQLite 세션은 제외됩니다. 복원은 원본과 대상의 행 수 및 행별 내용이 일치할 때만 커밋됩니다.

   ```bash
   PYTHONPATH=. python deploy/import_sqlite.py /private/shift-bridge-backup --apply
   ```

4. 승인된 테스트 배포에서 Render Environment에 `SHIFT_BRIDGE_DATABASE_URL`과 `SHIFT_BRIDGE_ENGINE_DATABASE_URL`을 각각 제한된 역할의 연결 문자열로 설정합니다. CA 인증서 파일은 Render Secret File로 제공할 수 있습니다. 앱은 검증된 복원 표시가 없거나 웹 테이블의 RLS가 비활성 상태이면 시작에 실패합니다. SQLite 모드가 필요한 격리된 CI 검증에는 `SHIFT_BRIDGE_STORAGE_MODE=sqlite`를 사용합니다. [Render 환경 변수와 Secret Files](https://render.com/docs/configure-environment-variables)

5. 테스트 계정으로 로그인하고 A·B의 기본 장소와 작업 기록을 확인합니다. 서로의 행을 읽거나 수정할 수 없는지 확인한 후, 테스트 인스턴스 재시작을 거쳐 보고서와 설정을 다시 읽습니다. 운영 전환과 추가 관리자 생성은 이 검증과 승인 후에 진행합니다.

별도의 로컬 PostgreSQL에서 같은 이전 검증을 반복할 수 있습니다. 테스트 전용의 비어 있는 `shift_bridge_test_` 접두사 데이터베이스를 사용합니다.

```bash
PYTHONPATH=.:Agent:BridgeCLI:deploy python deploy/test_postgres_migration.py -v
```

`SHIFT_BRIDGE_TEST_DATABASE_URL`에는 해당 로컬 데이터베이스의 테스트 연결을 설정합니다.
