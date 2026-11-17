const express = require('express');
const cors = require('cors');
const path = require('path');
const { GoogleGenerativeAI } = require('@google/generative-ai');

const app = express();
const PORT = process.env.PORT || 8080;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname)));

// Gemini API 인스턴스 초기화 (안정적인 @google/generative-ai SDK 사용)
const apiKey = process.env.GEMINI_API_KEY;
let genAI = null;
let model = null;

if (apiKey) {
    genAI = new GoogleGenerativeAI(apiKey);
    model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });
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

// 🧠 1. 실시간 대화형 AI 챗봇 함수
async function chatWithGemini(userMessage) {
    if (!model) {
        return "⚠️ [AI 두뇌 대기 상태]: Render 대시보드의 'Environment' 메뉴에 'GEMINI_API_KEY'가 아직 등록되지 않았습니다. 키를 등록하시면 즉시 최신 Gemini AI가 지능적으로 답변합니다!";
    }

    const systemInstruction = `
너는 대한민국 최고의 데이터센터(IDC) 수석 인프라 엔지니어이자 AI 어시스턴트인 'DC-OPS AI'다.
사용자(엔지니어, 운영자)의 질문이나 대화에 대해 매우 친절하고, 전문적이며, 신뢰감 있게 한국어로 답변해줘.
서버, 네트워크(BGP/OSPF/LACP/VLAN), 스토리지(SAN/NAS), 전력(UPS/PDU), 공조(CRAC), 소방 등 인프라 전반에 대해 현장 실무 지식을 바탕으로 명쾌하게 조언해줄 수 있어.
일반적인 인사나 질문에도 자연스럽고 똑똑하게 대답해줘.
`;

    try {
        const result = await model.generateContent(`${systemInstruction}\n\n사용자 질문: ${userMessage}`);
        return result.response.text();
    } catch (err) {
        console.error("Gemini Chat Error:", err);
        return `[Gemini AI 통신 오류]: ${err.message}`;
    }
}

// 🧠 2. 장애 대응 솔루션 분석
async function askGeminiForSolution(rack, detail) {
    if (!model) {
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
        const result = await model.generateContent(prompt);
        return result.response.text();
    } catch (err) {
        return `[Gemini AI 호출 오류]: ${err.message}`;
    }
}

// API 라우트
app.get('/api/items', (req, res) => {
    res.json(handoverItems);
});

// 🤖 실시간 AI 챗봇 대화 엔드포인트
app.post('/api/chat', async (req, res) => {
    const { message } = req.body;
    if (!message) {
        return res.status(400).json({ reply: "메시지를 입력해 주세요." });
    }
    const reply = await chatWithGemini(message);
    res.json({ reply });
});

// AI 개별 솔루션 분석 API
app.post('/api/ai_analyze', async (req, res) => {
    const { rack, detail } = req.body;
    const analysis = await askGeminiForSolution(rack, detail);
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
    console.log(`DC-OPS Real LLM Cloud Server running on port ${PORT}`);
});
