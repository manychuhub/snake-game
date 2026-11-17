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

// API 엔드포인트
app.get('/api/items', (req, res) => {
    res.json(handoverItems);
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
