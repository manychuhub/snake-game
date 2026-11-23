# Agent

상위 폴더의 README.md와 Start.bat을 사용하세요.

## 공통 AI API 계약 (병렬 작업 기준)

```text
명령/질의 엔드포인트: POST /api/ai/command
  요청: { "message": string, "context": { "view"?: string, "rackId"?: string, "serverId"?: string, "serialNumber"?: string, "ticketId"?: string, "shiftType"?: string } }
  응답(일반 질의/즉시 실행): { "type": "answer" | "action_executed", "reply": string, "action"?: object, "auditLog"?: { "timestamp": string, "actor": string, "command": string, "targetId"?: string, "result": string } }
  응답(2단계 승인 필요): { "type": "pending_confirmation", "confirmationId": string, "summary": string, "target": { "rackId"?: string, "serverId"?: string, "serialNumber"?: string, "ticketId"?: string }, "changes": object, "reply": string }
승인 확정/취소 엔드포인트: POST /api/ai/confirm
  요청: { "confirmationId": string, "approved": boolean }
  응답: { "status": "executed" | "cancelled", "reply": string, "auditLog"?: object }
```

웹 계정으로 로그인한 뒤 같은 사이트에서 `Content-Type: application/json`으로 호출합니다.

`POST /api/ai/command`에는 `message` 문자열과 `context` 객체를 보냅니다. `context`에는 `view`, `rackId`, `serverId`, `serialNumber`, `ticketId`, `shiftType` 문자열을 필요한 경우에만 넣습니다. 화면 정보가 없으면 `{}`를 보냅니다.

| 요청 예시 | 응답 |
| --- | --- |
| `{"message":"이 티켓의 작업 결과를 알려 줘","context":{"ticketId":"TT-12345"}}` | `type: "answer"`, `reply` |
| `{"message":"RACK-01 포트 화면을 열어 줘","context":{}}` | `type: "action_executed"`, `reply`, `action`, `auditLog` |
| `{"message":"이 티켓을 완료로 바꿔 줘","context":{"ticketId":"TT-12345"}}` | `type: "pending_confirmation"`, `confirmationId`, `summary`, `target`, `changes`, `reply` |

`/기록`은 뒤에 입력한 원문과 화면의 장비·티켓 정보를 등록할 승인 요청을 생성합니다. AI 질의는 현재 워크스페이스의 업무 기록과 기술 문서를 참고합니다. 티켓을 한 건으로 특정하면 상태 변경을 제안합니다. 승인 후 상태와 후속 작업을 갱신하고 다음 교대 인계 노트를 추가합니다. `changes.status`는 `from`과 `to`를 포함합니다.

`POST /api/ai/confirm`에 `{"confirmationId":"…","approved":true}`를 보내면 확인된 변경을 실행하고, `approved: false`를 보내면 취소합니다. 응답에는 `status`(`executed` 또는 `cancelled`), `reply`, `auditLog`가 담깁니다. 감사 응답은 `timestamp`, `actor`, `command`, `targetId`, `result`를 제공합니다.

확인 ID는 발급 계정과 워크스페이스에 연결되며 15분 동안 승인할 수 있습니다. 권한은 승인 시 다시 확인합니다. 대상 기록의 식별자나 상태가 바뀌거나 승인 시간이 지나면 `cancelled`를 반환합니다. 재요청에는 기존 처리 결과를 반환합니다. 현재 계정에서 찾을 수 없는 ID에는 HTTP 404를 반환합니다. 감사 기록에는 시각, 요청자, 명령 종류, 대상 ID와 자격 증명을 가린 원문을 저장합니다.

### 워크스페이스 AI 사용

- 상단 명령 바에서 **야간 장애 티켓**과 **미완료 하드웨어 교체**를 선택하면 최근 업무 기록이 필터링됩니다. 야간 시간은 기록의 현지 시각 20:00~07:59입니다. 담당자 알림은 티켓에 기록된 담당자가 활성 웹 계정과 일치할 때 작업 알림함에 등록됩니다.
- 업무 기록의 랙·서버·티켓을 선택하면 우측 챗봇에 대상이 자동으로 전달됩니다. 장비 식별번호에 `RACK:R14 SERVER:svr-kr-a14-03 SN:SN-42 PART:HDD` 형식을 사용할 수 있습니다. 기존의 `R14`와 `svr-…` 형식도 인식합니다. 부품이 확인되면 계약의 `view`를 `ticket/hdd` 또는 `server/ram`처럼 보냅니다.
- 상세에서 SOP·고장 진단·이전 교대 기록·삭제 규정을 질문할 수 있습니다. 티켓에서 `인계 노트 추가: 다음 교대에 SMART 상태 확인`을 입력하고 승인하면 해당 기록에 노트가 추가됩니다.
- **저장 매체 삭제·폐기**에서 시리얼 번호를 입력합니다. 삭제 증적은 해당 시리얼로 등록된 업무 기록 중 최신 `저장 매체 삭제` 유형의 기록을 사용합니다. `결과`가 `삭제 검증 완료`이고 `상태`가 `완료` 또는 `폐기 대기`여야 삭제 검증을 확인할 수 있습니다. 초안에는 기록에서 확인한 정보와 작성자가 채울 증적 항목이 표시됩니다.
- **종합 보고서 → AI 인계 이력**에서 `GET /api/ai/activity`로 가져온 감사 기록과 받은 작업 알림을 확인합니다.
- 기본 연결 모드는 **실제 API**입니다. **모의 실행**에서는 브라우저의 가상 기록과 승인·감사 흐름을 사용합니다. 저장 매체 예시 시리얼은 `SN-DEMO-041`입니다.

### 도구와 운영 설정

| 도구 | 동작 |
| --- | --- |
| 랙·포트 이동 | 등록된 스위치와 포트 정보를 반환하고 웹에서 랙 상세를 엽니다. |
| 스위치 포트 링크 조회 | 지정된 읽기 전용 점검 스크립트를 실행해 `up`, `down`, `unknown` 중 하나를 반환합니다. |
| BMC/IPMI 콘솔 | 승인 후 응답의 마지막 줄에 같은 사이트의 `/api/ai/console/<confirmationId>` 링크가 표시됩니다. 해당 계정과 현재 장비 설정을 검증한 뒤 장비 콘솔로 이동합니다. |
| HDD 재고·반출 요청 | 재고를 조회하고, 승인 시 수량을 예약해 반출 요청서를 저장합니다. 재고는 설정 수량에서 저장된 예약 수량을 뺀 값입니다. |
| 장애 티켓 상태 변경 | 승인 시 상태를 갱신하고 다음 교대 인계 노트를 추가합니다. |
| 디스크 와이핑 등록 | 승인 시 작업을 등록하고 미확인 상태의 폐기 라벨·증적 리포트 초안을 저장합니다. 실제 와이핑·물리 폐기와 전원 제어는 별도 절차입니다. |

장비와 재고 도구에는 공용 워크스페이스의 관리자 계정이 필요합니다. 티켓 및 업무 기록은 로그인 계정의 워크스페이스에서 처리합니다. PostgreSQL 웹 서비스는 `shift_bridge_web`, BridgeCLI는 `shift_bridge_engine` 역할을 검증합니다. BridgeCLI는 기존 내부 Gemini 호출 경로를 제공하며 장비 작업과 업무 트랜잭션은 Agent가 실행합니다.

`SHIFT_BRIDGE_DCO_INVENTORY_JSON`에는 랙, 설치 장비, 초기 HDD 수량을 설정합니다. 식별자는 등록된 대소문자 그대로 사용합니다. 다음은 가상 예시입니다.

```json
{
  "racks": {"RACK-01": {"switches": {"3": ["9", "10"]}}},
  "servers": {"SRV-01": {"rackId": "RACK-01", "serialNumbers": ["SN-9921"], "consoleUrl": "https://bmc.example.invalid/"}},
  "hdd": {"HDD-4TB": 5}
}
```

`SHIFT_BRIDGE_DCO_PORT_SCRIPT`는 관리자가 설치한 읽기 전용 Python 스크립트의 절대 경로입니다. Agent는 `rackId`, `switchId`, `portId`를 순서대로 전달하며 자식 프로세스에 앱 자격 증명을 전달하지 않습니다. 스크립트는 8초 안에 표준 출력으로 `{"link":"up"}`과 같은 JSON 한 건을 반환합니다. 스위치 전체 요청의 세 번째 인수는 `--all`이고 응답 예시는 `{"ports":{"9":"up","10":"down"}}`입니다. 콘솔 주소에는 인증 정보, 쿼리와 프래그먼트가 없는 HTTPS URL을 설정합니다.

PostgreSQL 환경에서는 [마이그레이션 디렉터리](../supabase/migrations)의 파일을 순서대로 적용한 뒤 앱을 시작합니다. AI 승인과 DCO 작업 테이블은 [DCO 도구 마이그레이션](../supabase/migrations/20261123000500_dco_ai_tools.sql)에 포함됩니다.
