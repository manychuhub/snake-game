const express = require('express');
const cors = require('cors');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 8080;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname)));

// 초기 데이터
let handoverItems = [
    {
        id: 1,
        author: "이당직 (야간조)",
        rack: "Hall-A #R07",
        severity: "CRITICAL",
        category: "HW장애",
        time: "03:40 AM",
        detail: "웹서버 4호기 파워서플라이(PSU #2) 장애 알람 발생. 현재 PSU #1으로 리던던트 구동 중이나 여분 파워 모듈 교체 작업 주간조 진행 필요.",
        completed: false
    },
    {
        id: 2,
        author: "박인프라 (야간조)",
        rack: "Hall-C 공조실",
        severity: "WARNING",
        category: "시설/환경",
        time: "05:15 AM",
        detail: "CRAC #3 습도 센서 일시적 68% 상승 후 현재 55%로 안정화. 시설팀 오전 10시 정기 실사 시 필터 점검 요청 권장.",
        completed: false
    }
];

// 클라우드 지능형 AI 솔루션 생성 함수
function generateCloudAiAnalysis(rack, detail) {
    let lower = detail.toLowerCase();
    let guide = `데이터센터 ${rack} 현장 조치 가이드입니다.\n\n`;

    if (lower.includes('psu') || lower.includes('파워') || lower.includes('전원')) {
        guide += "1. [1차 육안 점검]: 장비 후면 UID LED 및 PSU LED 상태(Amber/Dark) 확인 및 C13/C14 전원 코드 체결 상태 점검\n";
        guide += "2. [전원 라인 배제]: 랙 PDU B-Feed 분기 차단기 트립 여부 확인 및 정상 PDU 소켓으로 전원 케이블 교차 테스트\n";
        guide += "3. [무중단 핫스왑]: PSU1 정상 급전 확인 후 결함 파트 Hot-swap 탈거, 동일 P/N 예비 모듈 장착 후 Solid Green 점등 및 BMC 로그 복구 확인";
    } else if (lower.includes('crac') || lower.includes('공조') || lower.includes('온도') || lower.includes('습도')) {
        guide += "1. [센서 원격 텔레메트리 대조]: 해당 Zone Cold Aisle 온습도 센서와 인접 센서값 교차 검증으로 단일 센서 이상 여부 판별\n";
        guide += "2. [공조기 실사]: CRAC 송풍 팬 회전 상태, 필터 차압계 및 냉각수 입출구 밸브 압력 게이지 확인\n";
        guide += "3. [시설팀 핫라인 이관]: 자동 제어 밸브(FCV) 수동 개도율 조절 및 2차 시설 비상 프로토콜 가동";
    } else if (lower.includes('crc') || lower.includes('스위치') || lower.includes('광') || lower.includes('네트워크')) {
        guide += "1. [인터페이스 상태 확인]: switch# show interface 카운터 확인 및 DOM(Digital Optical Monitoring) Rx 수신 광레벨 측정\n";
        guide += "2. [물리 패치 점검]: LC 광패치 코드 클리닝 및 감쇠기 체결 확인 후 인접 스페어 포트로 교차 연결\n";
        guide += "3. [트랜시버 교체]: 100G/40G QSFP28 모듈 핫스왑 교체 및 LACP 번들 정상 링크업(Up/Up) 확인";
    } else {
        guide += "1. [현장 섀시 위치 특정]: 대상 랙 전/후면 UID 램프 점등 후 U-Number(위치) 정확히 식별\n";
        guide += "2. [OOB/IPMI 로그 추출]: 원격 관리 콘솔(iDRAC/iLO) System Event Log(SEL) 다운로드 및 최근 Critical 이벤트 분석\n";
        guide += "3. [부품 교체 및 정상화 검증]: 예비 파트 교체 후 벤더사 진단 툴(Diagnostic Tool) 패스 확인";
    }
    return guide;
}

// API 라우트
app.get('/api/items', (req, res) => {
    res.json(handoverItems);
});

app.post('/api/ai_analyze', (req, res) => {
    const { rack, detail } = req.body;
    const analysis = generateCloudAiAnalysis(rack, detail);
    res.json({ analysis });
});

app.post('/api/add', (req, res) => {
    handoverItems.unshift(req.body);
    if (handoverItems.length > 50) handoverItems = handoverItems.slice(0, 50);
    res.json(handoverItems);
});

app.post('/api/toggle', (req, res) => {
    const { id } = req.body;
    const item = handoverItems.find(i => i.id === id);
    if (item) item.completed = !item.completed;
    res.json(handoverItems);
});

app.post('/api/delete', (req, res) => {
    const { id } = req.body;
    handoverItems = handoverItems.filter(i => i.id !== id);
    res.json(handoverItems);
});

app.post('/api/trigger_handover', (req, res) => {
    const shift = req.body.shift || '정기 교대';
    const pending = handoverItems.filter(i => !i.completed);
    const crit = pending.filter(i => i.severity === 'CRITICAL').length;
    const warn = pending.filter(i => i.severity === 'WARNING').length;

    const summaryItem = {
        id: Date.now(),
        author: `🤖 AI 근무교대 자동화 (${shift})`,
        rack: "클라우드 통합 관제",
        severity: crit > 0 ? "CRITICAL" : (warn > 0 ? "WARNING" : "INFO"),
        category: "정기작업",
        time: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
        detail: `[${shift} 공식 인수인계 체결] 총 미결 건수 ${pending.length}건 (긴급 ${crit}건, 주의 ${warn}건). 인수인계 서명이 완료되어 다음 조로 이관되었습니다.`,
        completed: false
    };

    handoverItems.unshift(summaryItem);
    res.json(handoverItems);
});

app.listen(PORT, () => {
    console.log(`DC-OPS Cloud Server running on port ${PORT}`);
});
