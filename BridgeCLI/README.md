# BRIDGE CLI — SHIFT BRIDGE용 로컬 AI 엔진 v1.0

Google Gemini API 키로 Python CLI와 로컬 REST API를 실행하는 독립형 엔진입니다. Antigravity CLI를 로컬에서 가동하거나 Google 계정 세션을 재활용하는 방식이 아닙니다. 공식 Gemini REST `generateContent`, `models.list`, `embedContent`를 사용하며, 에이전트는 Gemini Function Calling 및 제한된 읽기 전용 도구로 구현됩니다. 네트워크 호출은 실제 Google API로 전송되며 실패하면 오류를 반환합니다. 테스트 파일 외에는 가짜 AI 응답이 없습니다.

## 설치 및 실행 (Windows)

1. 기존 바탕화면 `BridgeCLI` 폴더를 백업합니다. ZIP을 풀어서 나온 `BridgeCLI` 폴더 안의 파일들을 기존 폴더에 복사합니다. README.md는 교체해도 되지만 `.env`는 유지합니다. 이 배포 ZIP에는 실제 `.env`가 없습니다.
2. PowerShell을 열어 `python --version` 또는 `py -3 --version`을 확인합니다. Python 3.11~3.13 권장. 없으면 https://www.python.org/downloads/windows/ 에서 설치 후 PowerShell을 다시 열어 주세요. (설치 시 Add Python to PATH 선택)
3. 기존 `.env`에 두 값이 모두 있는지 메모장에서 확인하세요. 값을 채팅이나 화면 공유에 노출하지 마세요. 새로 만들 때는 `.env.example`을 복사해 `.env`로 이름을 변경합니다.

```ini
GEMINI_API_KEY=YOUR_GOOGLE_KEY
HYBRID_API_AUTH_TOKEN=YOUR_RANDOM_LOCAL_TOKEN
```

4. `start.bat` 더블클릭. 처음 실행할 때 가상환경과 라이브러리를 설치합니다. 오류가 발생하면 창이 유지됩니다. 정상 실행 시 http://127.0.0.1:8011/docs 가 열릴 수 있는 상태가 됩니다. 서버 창을 닫지 마세요. 종료는 서버 창에서 Ctrl+C입니다. `stop.bat`은 안전한 종료 방법만 안내하며 다른 프로세스를 강제 종료하지 않습니다.
5. 새 PowerShell에서 다음을 실행합니다. (바탕화면이 OneDrive와 연결된 경우 실제 위치에 맞게 경로를 변경하세요.)

```powershell
cd "$env:USERPROFILE\Desktop\BridgeCLI"
.\bridge.bat status
.\bridge.bat models
.\bridge.bat chat "연결 성공이면 연결 성공이라고 말해줘"
```

`status`는 서버 상태 확인만 하며 Google 인증 성공을 의미하지 않습니다. `models`와 `chat`이 성공해야 실제 Google 연결을 확인할 수 있습니다. 모델은 기본적으로 모델 목록에서 일반 Flash 모델을 선택합니다. 원하면 `.env`에 `GEMINI_MODEL=모델이름`을 지정합니다. API가 429를 반환하면 할당량이나 결제를 확인합니다. 키 값을 출력하지 않습니다.

## 사용 예시 (가상 데이터)

```powershell
.\bridge.bat analyze "가상 SERVER-32 티켓 T-32 RAM 교체 후 정상 확인" --shift "DAY-001"
.\bridge.bat records
.\bridge.bat approve-record 1
.\bridge.bat handover "야간조 보고서 작성" --shift "DAY-001"
.\bridge.bat reports
.\bridge.bat approve-report 1
.\bridge.bat search "SERVER-32 RAM"
.\bridge.bat assistant "미완료 업무를 찾아줘" --mode agent
.\bridge.bat audit "누락 정보 확인"
.\bridge.bat repeat "반복 장애 분석"
.\bridge.bat priority "다음 근무조 우선순위"
.\bridge.bat improve "업무 개선 제안"
.\bridge.bat translate "가상 서버 장애" --target en
.\bridge.bat voice "음성을 전사하고 업무 기록 정리" --file "C:\example\memo.wav"
.\bridge.bat document "장비 매뉴얼 요약" --file "C:\example\manual.pdf"
.\bridge.bat usage
```

승인 ID는 실제 응답의 record_id/report_id로 변경합니다. AI가 분석한 업무 기록과 보고서는 초안입니다. 승인 전 API 문서의 PUT `/v1/records/{record_id}` 또는 `/v1/reports/{report_id}`에서 수정 가능합니다. API 문서에서는 Authorize(표시되는 경우) 또는 요청의 authorization 입력에 `Bearer 실제자체토큰`을 사용합니다. 직접 호출 예시는 아래에 있습니다.

### 기록 기억 및 검색
- SQLite `data/bridge.db`에 원문, 구조화 업무 기록, 승인 상태, 보고서, 문서 텍스트, 생성 토큰 집계가 유지됩니다. 승인한 업무만 검색과 보고서에 포함합니다.
- 기록 검색은 기본적으로 키워드/문자 조각 기반입니다. 실제 의미 검색도 선택적으로 사용할 수 있습니다. `bridge.bat index`는 승인된 업무 기록 최대 100건을 Gemini 임베딩 API에 전송하여 벡터를 저장합니다. `bridge.bat search "이전 부품 장애" --semantic`은 질문 임베딩을 생성하여 코사인 유사도와 키워드로 검색합니다. 비용이 발생할 수 있습니다. 새로운 승인 기록 또는 편집 기록에 대해 다시 인덱싱하세요. 현재 문서 텍스트는 키워드 검색만 지원합니다.
- 문서 텍스트/페이지를 `/v1/documents`에 직접 등록하면 출처 ID와 페이지가 검색 결과에 들어갑니다. PDF/오디오 첨부 분석은 최대 10MB(모델별 지원 여부 및 API 제한에 따름), 자동 문서 인덱싱과 마이크 녹음 UI는 미구현입니다. PDF에서 AI가 제시한 페이지는 원문으로 검증해야 합니다.
- 에이전트는 검색, 미완료 기록 조회, 통계 조회만 가능한 도구를 사용합니다. 최대 4회 도구 호출 라운드 후 최종 응답을 생성합니다. 임의 셸 명령 실행 및 파일 접근 도구는 제공하지 않습니다. 사용자 지정 다중 에이전트 협업은 아직 없습니다.
- API 요청 대기열과 동시 처리 수는 설정 가능합니다. Shift 이름을 지정하면 해당 조의 기록과 다른 조의 미완료 기록을 포함합니다. 티켓 상태의 이력 통합/중복 제거 및 공식 운영 우선순위 규칙은 후속 개발이 필요합니다. 반복 통계는 승인된 기록의 단순 빈도이며 실제 장애 건수와 다를 수 있습니다.
- 토큰 사용량은 Google이 반환하는 생성 메타데이터를 집계합니다. 임베딩 비용 및 실제 요금 계산은 제공하지 않습니다. 금액은 Google AI Studio에서 확인하세요.

## SHIFT BRIDGE와 연결하기

브라우저에서 Google 키나 자체 인증 토큰을 직접 사용하지 말고 SHIFT BRIDGE 백엔드에서 호출하세요. 두 프로그램이 같은 컴퓨터에서 실행되어야 합니다. 자체 서버는 기본적으로 127.0.0.1에만 바인딩됩니다. SHIFT BRIDGE가 별도 서버에 배포되어 있다면 localhost는 서로 다른 컴퓨터를 뜻하므로 별도의 안전한 배포 구성이 필요합니다.

- URL: `http://127.0.0.1:8011/v1/bridge`
- Method: POST
- Header: `Authorization: Bearer YOUR_LOCAL_TOKEN`
- Header: `Content-Type: application/json`
- JSON 예시: `{"task":"analyze","prompt":"가상 업무 기록","mode":"auto","metadata":{"shift":"DAY-001"}}`
- 응답: `mode`, `task`, `result.content`, `result.sources`, `usage`; 분석 결과에는 `result.fields`, `record_id`, `missing`; 인수인계에는 `report_id`가 포함됩니다.
- 과거 API 요청 호환: `task_type: "simple"` 또는 `"complex"` 및 `prompt`, `mode` 지원. 명확한 기능에는 `task` 필드를 사용하세요.
- `mode: agent`는 chat/assistant/search/audit/improve/priority 작업의 읽기 전용 도구 기능에 사용합니다. 구조화 분석/보고서/첨부 등은 목적에 맞게 API 모드를 사용하며 실제 모드를 응답에 표시합니다.
- Python 백엔드 예제 파일: `shift_bridge_client.py`. 실제 SHIFT BRIDGE 프로젝트 소스는 제공되지 않았으므로 해당 프로그램에 직접 적용하거나 검증하지 못했습니다. 동일한 기능을 사용하려면 기존 앱의 승인 기록/문서 저장 경로를 위 엔드포인트에 연결해야 합니다.

### 테스트
`test.bat` 실행 또는 가상환경의 `python -m unittest discover -s tests -v`. 테스트용 응답으로 서버 인증, JSON 분석, 승인 전 검색 제외, SQLite 재시작 지속성, 보고서 승인, 도구 호출, 임베딩 검색, 문서 출처, 오류, 토큰 통계를 검증합니다. 실제 Google API 키를 이용한 검증 및 Windows 배치 파일 실행은 사용자 컴퓨터에서 필요합니다.

### 보안 및 제한
이 프로그램은 개인 개발/가상 데이터 용도입니다. 실제 AWS 내부 서버 식별자, 티켓, 로그, 문서, 음성, 개인정보를 개인 Google API 키로 전송하지 마세요. `.env`는 평문 설정 파일이므로 접근을 제한하고 공유/커밋하지 마세요. 인증은 하나의 로컬 토큰이며 다중 사용자 권한 관리/감사 정책/운영 수준의 보안 검증은 미구현입니다. Google API 사용 약관 및 비용/할당량이 그대로 적용됩니다.

공식 참고: https://ai.google.dev/api/generate-content , https://ai.google.dev/api/models , https://ai.google.dev/api/embeddings
