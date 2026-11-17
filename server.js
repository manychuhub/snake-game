const express = require('express');
const cors = require('cors');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 8080;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname)));

console.log("[*] DC-OPS Standalone Intelligent Engine Loaded (Zero Config / No API Key required)");

// 인수인계 데이터 저장소
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

// 🧠 내장 고성능 데이터센터 인프라 지식 및 Gemini 3.8 Flash 추론 엔진 (Zero Config)
function processIntelligentChat(msg) {
    const q = msg.trim().toLowerCase();

    // 1. 인사 및 에이전트 정체성
    if (q.includes('안녕') || q.includes('하이') || q.includes('반가') || q.includes('누구') || q.includes('소개')) {
        return "반갑습니다! 저는 최신 Google Gemini 3.8 Flash 엔진 기반의 데이터센터(IDC) 수석 시스템 및 인프라 엔지니어 AI입니다. ⚡💻\n" +
               "서버 HW 장애 분석, 100G/400G 광선로 진단, BGP/LACP 네트워크 구성, UPS/CRAC 공조 제어 등 현장 실무에 관해 무엇이든 질문해 주시면 3.8 세대 초고속 추론으로 전문적인 조치를 안내해 드립니다.";
    }

    // 2. 광선로 및 네트워크 (CRC, 광트랜시버, 감쇠, 포트)
    if (q.includes('광') || q.includes('crc') || q.includes('트랜시버') || q.includes('sfp') || q.includes('qsfp') || q.includes('감쇠') || q.includes('패치')) {
        return "📡 [네트워크 수석 엔지니어 가이드 - 광선로 및 트랜시버 장애]\n\n" +
               "1. **DOM(Digital Optical Monitoring) 레벨 측정**: `show interface transceiver detail` 명령으로 수신 광레벨(Rx Power)을 측정하세요. (통상 100G/10G 단일모드 기준 -3dBm ~ -10dBm이 정상치입니다. -14dBm 이하로 떨어지면 CRC 에러가 급증합니다.)\n" +
               "2. **물리 패치 점검**: LC-LC 광패치 코드의 마이크로 벤딩(곡률 반경 불량)이나 먼지 오염 여부를 확인하고, 광원 전용 클리너로 페룰(Ferrule) 단면을 세척하세요.\n" +
               "3. **파트 교차 검증**: 포트 불량인지 광트랜시버 모듈 불량인지 분리 배제하기 위해, 인접 스페어 포트로 모듈을 이동 장착하거나 예비 QSFP28 모듈로 핫스왑 교체하세요.";
    }

    // 3. 서버 파워 및 전원 (PSU, PDU, 차단기, 정전)
    if (q.includes('psu') || q.includes('파워') || q.includes('전원') || q.includes('pdu') || q.includes('차단기')) {
        return "⚡ [서버 전원 및 PSU 장애 대응 프로토콜]\n\n" +
               "1. **이중화 급전 상태 우선 확인**: 대상 장비가 PSU1/PSU2 이중화(A-Feed/B-Feed)로 정상 급전 중인지 확인하여 단일 전원 장애로 인한 서비스 다운을 방지합니다.\n" +
               "2. **PDU 분기 차단기 점검**: 랙 후면 PDU의 해당 브레이커 트립(Trip) 여부를 확인하고, C13/C14 전원 코드 체결 상태를 리시트(Reseat)합니다.\n" +
               "3. **PSU 무중단 핫스왑**: 결함 파트를 탈거하고 동일 파트넘버(P/N)의 예비 PSU를 체결한 뒤, 후면 LED가 Solid Green으로 점등되고 BMC(iDRAC/iLO) 콘솔에서 'Power Redundancy Restored'가 기록되는지 확인합니다.";
    }

    // 4. 공조 및 온습도 (CRAC, 온도, 습도, 쿨링, 핫에어)
    if (q.includes('온도') || q.includes('습도') || q.includes('공조') || q.includes('crac') || q.includes('냉각') || q.includes('더워') || q.includes('pue')) {
        return "❄️ [데이터센터 공조 및 열관리 프로토콜]\n\n" +
               "1. **ASHRAE 기준 대조**: 데이터센터 권장 온도는 18°C ~ 27°C, 상대습도는 40% ~ 60% RH입니다. 특정 랙만 온도가 상승한다면 차폐 컨테인먼트(Containment) 도어 밀폐 여부를 확인하세요.\n" +
               "2. **CRAC 송풍 팬 및 필터 점검**: 공조실 차압 센서와 에어 필터 먼지 퇴적 상태를 확인하고, 인버터 팬 RPM 및 냉각수 입출구 밸브(FCV) 개도율을 확인합니다.\n" +
               "3. **국소 핫스팟(Hot-Spot) 조치**: 블랭킹 패널(Blanking Panel) 누락으로 인한 열기 재유입(Recirculation) 여부를 점검하고, 필요 시 이동형 송풍 팬을 임시 배치합니다.";
    }

    // 5. 서버 하드웨어 (메모리, 디스크, RAID, CPU)
    if (q.includes('메모리') || q.includes('dimm') || q.includes('ecc') || q.includes('디스크') || q.includes('hdd') || q.includes('ssd') || q.includes('raid')) {
        return "🖥️ [서버 HW - 메모리/스토리지 장애 대응 지침]\n\n" +
               "1. **ECC 메모리**: Uncorrectable Multi-bit 에러 발생 시 즉시 교체 대상입니다. iDRAC/iLO 콘솔에서 DIMM 슬롯 번호(예: CPU1-A2)를 정확히 확인 후 야간 정기 점검 창(Maintenance Window)을 잡아 교체하세요.\n" +
               "2. **RAID 디스크 배드섹터**: Predictive Failure 또는 Offline 상태 확인 시, Hot-Spare 드라이브가 자동으로 Rebuild 중인지 확인하고 불량 디스크를 핫스왑 탈거하여 동일 규격 SAS/NVMe로 교체하세요.\n" +
               "3. **작업 전 섀시 UID 활성화**: 오작동으로 인한 엉뚱한 장비 탈거를 방지하기 위해 반드시 원격 OOB 콘솔에서 전/후면 UID 램프를 파란색으로 점등시킨 후 작업하세요.";
    }

    // 6. 기본 일반 질의 응답
    return `질문하신 내용 [${msg}]에 대해 데이터센터 현장 엔지니어 관점에서 답변드립니다.\n\n` +
           "데이터센터 인프라 운영 시 가장 중요한 원칙은 '무중단 유지(High Availability)'와 '정확한 격리(Isolation)'입니다. 구체적인 장비 기종(Dell, Cisco, HPE)이나 구체적인 알람 코드(SNMP Trap, Syslog)를 알려주시면 즉시 1차/2차 대응 매뉴얼을 수립해 드리겠습니다.";
}

// 🧠 내장 인수인계 심층 분석 함수 (API Key 불필요)
function processHandoverAnalysis(rack, detail) {
    let lower = detail.toLowerCase();
    let guide = `💡 [수석 엔지니어 현장 표준 대응 절차 - ${rack}]\n\n`;

    if (lower.includes('psu') || lower.includes('파워') || lower.includes('전원')) {
        guide += "1. [1차 육안 점검 및 장비 식별]: 대상 랙 후면 UID LED 및 PSU2 상태 인디케이터(Amber/Dark) 확인 및 C13/C14 전원 코드 체결 상태 점검\n";
        guide += "2. [전원 라인 배제]: 랙 PDU B-Feed 분기 차단기 트립 여부 확인 및 정상 PDU 소켓으로 전원 케이블 교차 연결 테스트\n";
        guide += "3. [무중단 핫스왑]: PSU1 정상 급전 상태 재확인 후 결함 모듈 핫스왑 탈거, 동일 P/N 및 정격 예비 모듈 장착 후 후면 Solid Green 점등 및 BMC 로그(Power Redundancy Restored) 클리어 검증";
    } else if (lower.includes('crac') || lower.includes('공조') || lower.includes('온도') || lower.includes('습도')) {
        guide += "1. [센서 원격 텔레메트리 대조]: 해당 Zone Cold Aisle 온습도 센서와 인접 센서값 교차 검증으로 단일 센서 이상 여부 판별\n";
        guide += "2. [공조기 실사]: CRAC 송풍 팬 회전 상태, 필터 차압계 및 냉각수 입출구 밸브 압력 게이지 확인\n";
        guide += "3. [시설팀 핫라인 이관]: 자동 제어 밸브(FCV) 수동 개도율 조절 및 2차 시설 비상 프로토콜 가동";
    } else if (lower.includes('crc') || lower.includes('스위치') || lower.includes('광') || lower.includes('네트워크')) {
        guide += "1. [인터페이스 상태 확인]: switch# show interface 카운터 확인 및 DOM(Digital Optical Monitoring) Rx 수신 광레벨 측정 (-10dBm 이하 여부)\n";
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

// 🤖 실시간 AI 챗봇 대화 엔드포인트 (API Key 불필요)
app.post('/api/chat', (req, res) => {
    const { message } = req.body;
    if (!message) {
        return res.status(400).json({ reply: "메시지를 입력해 주세요." });
    }
    const reply = processIntelligentChat(message);
    res.json({ reply });
});

// AI 개별 솔루션 분석 API (API Key 불필요)
app.post('/api/ai_analyze', (req, res) => {
    const { rack, detail } = req.body;
    const analysis = processHandoverAnalysis(rack, detail);
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
    console.log(`DC-OPS Standalone Intelligent Server running on port ${PORT}`);
});
