const express = require('express');
const cors = require('cors');
const path = require('path');
const https = require('https');

const app = express();
const PORT = process.env.PORT || 8080;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname)));

console.log("[*] DC-OPS Real Autonomous Free LLM Engine Loaded (Pollinations AI)");

// 1. 인수인계 데이터 저장소
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

// 2. 감사 로그
let auditLogs = [
    {
        id: 101,
        timestamp: new Date(Date.now() - 3600000 * 5).toLocaleString('ko-KR'),
        user: "이당직 (야간조)",
        action: "ADD",
        actionText: "신규 인수인계 등록",
        target: "Hall-A #R07",
        detail: "웹서버 4호기 파워서플라이(PSU #2) 장애 알람 발생 등록"
    }
];

function recordAudit(user, action, actionText, target, detail) {
    const log = {
        id: Date.now() + Math.floor(Math.random() * 1000),
        timestamp: new Date().toLocaleString('ko-KR', { hour12: false }),
        user: user || "익명 엔지니어",
        action: action,
        actionText: actionText,
        target: target || "구역 미지정",
        detail: detail || ""
    };
    auditLogs.unshift(log);
    if (auditLogs.length > 200) auditLogs = auditLogs.slice(0, 200);
}

// 🧠 [진짜 생성형 LLM AI 호출 함수]
// API Key 없이도 전 세계 오픈소스 최신 LLM(Mistral/Llama/Gemini 계열)을 무료로 자율 추론하는 글로벌 엔드포인트 연동
function callFreeGenerativeLLM(systemPrompt, userQuery) {
    return new Promise((resolve) => {
        const fullPrompt = `${systemPrompt}\n\n사용자 메시지: ${userQuery}`;
        const encodedPrompt = encodeURIComponent(fullPrompt);
        const url = `https://text.pollinations.ai/${encodedPrompt}?model=openai&seed=42`;

        const req = https.get(url, { timeout: 15000 }, (res) => {
            let data = '';
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', () => {
                if (data && data.trim()) {
                    resolve(data.trim());
                } else {
                    resolve("AI 서버 응답을 파싱하지 못했습니다.");
                }
            });
        });

        req.on('error', (e) => {
            console.error("LLM Call Error:", e.message);
            resolve(`[AI 네트워크 통신 지연]: 실시간 클라우드 연결 상태를 확인해 주세요. (${e.message})`);
        });

        req.on('timeout', () => {
            req.destroy();
            resolve("AI 응답 생성 시간이 초과되었습니다. 잠시 후 다시 질문해 주세요.");
        });
    });
}

// 🧠 1. 유능한 AI 챗봇 실시간 생성
async function processIntelligentChat(userMsg) {
    const systemPrompt = `
너는 대한민국 최상위 데이터센터(IDC) 수석 시스템 및 인프라 엔지니어 AI인 'DC-OPS AI'다.
사용자(인프라 엔지니어, 운영자)의 어떠한 질문이나 일상 대화에도 정해진 틀에 얽매이지 않고, 진정한 최신 거대언어모델(LLM)로서 자율적이고 똑똑하게 사고하여 한국어로 답변해야 한다.
- 네트워크, 리눅스 서버 커널, BGP/OSPF, 랙 전력(PDU/UPS), CRAC 공조, 소방 설비 등 인프라 전문 기술 질문에 대해 깊이 있는 실무 노하우를 제공해라.
- 사용자의 일반적인 대화나 농담, 기분, 날씨 등 일상적인 질문에도 아주 자연스럽고 유쾌하며 지능적으로 응답해라.
- 답변은 가독성 높게 마크다운과 이모지를 적절히 활용해라.
`;
    return await callFreeGenerativeLLM(systemPrompt, userMsg);
}

// 🧠 2. 유능한 인수인계 현장 조치 솔루션 실시간 생성
async function processHandoverAnalysis(rack, detail) {
    const systemPrompt = `
너는 20년 경력의 데이터센터 수석 하드웨어/인프라 엔지니어 AI다.
다음 현장 장애 건을 면밀히 분석하고, 엔지니어가 현장에서 즉시 실행해야 할 가장 안전하고 전문적인 1차/2차 점검 및 조치 절차 3단계를 번호 매겨 작성해줘.
실무 현장 전문 용어(UID LED, PDU 분기 차단기, Reseat, 핫스왑, OOB/iDRAC 로그 확인 등)를 자연스럽게 활용해라.
`;
    return await callFreeGenerativeLLM(systemPrompt, `장애 위치: ${rack}\n내용: ${detail}`);
}

// API 라우트
app.get('/api/items', (req, res) => {
    res.json(handoverItems);
});

app.get('/api/audit_logs', (req, res) => {
    res.json(auditLogs);
});

// 🤖 실시간 자율형 AI 챗봇 (진짜 LLM)
app.post('/api/chat', async (req, res) => {
    const { message } = req.body;
    if (!message) return res.status(400).json({ reply: "메시지를 입력해 주세요." });
    const reply = await processIntelligentChat(message);
    res.json({ reply });
});

// 🧠 실시간 자율형 AI 솔루션 분석 (진짜 LLM)
app.post('/api/ai_analyze', async (req, res) => {
    const { rack, detail } = req.body;
    const analysis = await processHandoverAnalysis(rack, detail);
    res.json({ analysis });
});

app.post('/api/add', (req, res) => {
    const item = req.body;
    handoverItems.unshift(item);
    if (handoverItems.length > 50) handoverItems = handoverItems.slice(0, 50);
    recordAudit(item.author, "ADD", "신규 등록", item.rack, `[${item.severity}] ${item.detail}`);
    res.json(handoverItems);
});

app.post('/api/toggle', (req, res) => {
    const { id, user } = req.body;
    const item = handoverItems.find(i => i.id === id);
    if (item) {
        item.completed = !item.completed;
        const actionText = item.completed ? "조치완료 체크" : "체크 해제(재개)";
        recordAudit(user || "교대 엔지니어", item.completed ? "COMPLETE" : "REOPEN", actionText, item.rack, item.detail);
    }
    res.json(handoverItems);
});

app.post('/api/delete', (req, res) => {
    const { id, user } = req.body;
    const target = handoverItems.find(i => i.id === id);
    if (target) {
        recordAudit(user || "교대 엔지니어", "DELETE", "항목 삭제", target.rack, target.detail);
        handoverItems = handoverItems.filter(i => i.id !== id);
    }
    res.json(handoverItems);
});

app.post('/api/trigger_handover', (req, res) => {
    const shift = req.body.shift || '정기 교대';
    const user = req.body.user || '근무조 총괄';
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
    recordAudit(user, "HANDOVER", "근무교대 이관", "통합 관제실", `[${shift}] 미결 ${pending.length}건 공식 이관 체결`);
    res.json(handoverItems);
});

app.listen(PORT, () => {
    console.log(`DC-OPS Real Autonomous Free LLM Server running on port ${PORT}`);
});
