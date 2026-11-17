const express = require('express');
const cors = require('cors');
const path = require('path');
const { GoogleGenAI } = require('@google/genai');

const app = express();
const PORT = process.env.PORT || 8080;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname)));

// Gemini API 인스턴스 초기화 (환경 변수 GEMINI_API_KEY 사용)
const apiKey = process.env.GEMINI_API_KEY;
let aiClient = null;

if (apiKey) {
    aiClient = new GoogleGenAI({ apiKey });
    console.log("[*] Google Gemini AI Brain successfully connected!");
} else {
    console.log("[!] Warning: GEMINI_API_KEY environment variable is not set. Running in standby mode.");
}

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

// 🧠 실제 Gemini AI 추론 함수 (장애 대응 솔루션)
async function askGeminiForSolution(rack, detail) {
    if (!aiClient) {
        return "⚠️ [알림]: GEMINI_API_KEY가 아직 등록되지 않았습니다. Render 대시보드의 Environment 설정에 API 키를 등록하면 실시간 최신 AI 두뇌가 활성화됩니다!";
    }

    const prompt = `
너는 20년 경력의 데이터센터(IDC) 수석 시스템 및 인프라 엔지니어 AI 어시스턴트다.
현장 엔지니어가 등록한 다음 인수인계/장애 내역을 면밀히 분석하고, 현장에서 즉시 실행해야 할 가장 전문적이고 안전한 1차/2차 점검 및 조치 절차 3가지를 명확히 작성해줘:

- 장애 위치: ${rack}
- 장애 및 인수인계 내용: ${detail}

작성 가이드:
1. 전문적이고 구체적인 현장 용어(UID LED, PDU Feed 분기, Reseat, Hot-swap, OOB/iDRAC/iLO 로그 등)를 자연스럽게 포함할 것.
2. 각 단계는 "1. [1차 점검]: ...", "2. [원인 격리]: ...", "3. [부품 교체 및 정상화 검증]: ..." 형태로 가독성 높게 작성할 것.
`;

    try {
        const response = await aiClient.models.generateContent({
            model: 'gemini-2.5-flash',
            contents: prompt
        });
        return response.text;
    } catch (err) {
        console.error("Gemini API Error:", err);
        return `[Gemini AI 호출 오류]: ${err.message}`;
    }
}

// 🧠 실제 Gemini AI 추론 함수 (교대 브리핑 리포트)
async function askGeminiForBriefing(pendingItems) {
    if (!aiClient) {
        return "⚠️ [AI 두뇌 대기중]: GEMINI_API_KEY를 등록하시면 실시간 AI 요약 브리핑이 자동 활성화됩니다.";
    }

    if (!pendingItems || pendingItems.length === 0) {
        return "🎉 [AI 브리핑]: 현재 미조치된 인수인계 및 장애 항목이 없습니다. 모든 인프라가 정상 운용 중입니다.";
    }

    const listText = pendingItems.map((item, idx) => 
        `${idx + 1}. [${item.severity}] 위치: ${item.rack} | 카테고리: ${item.category} | 내용: ${item.detail}`
    ).join("\n");

    const prompt = `
너는 데이터센터 총괄 책임자(Operations Lead) AI다.
다음은 교대 근무조로부터 인계받은 미결 장애 및 작업 목록이다:

${listText}

다음 세 가지 항목으로 깔끔하고 명확하게 한국어로 교대 브리핑을 작성해줘:
1. 🚨 [최우선 주간조 착수 액션]
2. ⚠️ [관찰 및 집중 모니터링 포인트]
3. 💡 [수석 엔지니어 현장 조언]
`;

    try {
        const response = await aiClient.models.generateContent({
            model: 'gemini-2.5-flash',
            contents: prompt
        });
        return response.text;
    } catch (err) {
        console.error("Gemini Briefing Error:", err);
        return `[Gemini 브리핑 생성 오류]: ${err.message}`;
    }
}

// API 라우트
app.get('/api/items', (req, res) => {
    res.json(handoverItems);
});

// AI 개별 솔루션 분석 API
app.post('/api/ai_analyze', async (req, res) => {
    const { rack, detail } = req.body;
    const analysis = await askGeminiForSolution(rack, detail);
    res.json({ analysis });
});

// AI 전체 교대 브리핑 API
app.post('/api/ai_briefing', async (req, res) => {
    const pending = handoverItems.filter(i => !i.completed);
    const briefing = await askGeminiForBriefing(pending);
    res.json({ briefing });
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
    console.log(`DC-OPS Real LLM Cloud Server running on port ${PORT}`);
});
