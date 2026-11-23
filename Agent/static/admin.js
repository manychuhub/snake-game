const tabs = [...document.querySelectorAll("[data-category]")];
const rows = document.getElementById("records");
const columns = document.getElementById("columns");
const message = document.getElementById("message");
const search = document.getElementById("search");
const query = document.getElementById("query");
const more = document.getElementById("more");
const engineStatus = document.getElementById("engine-status");
const testEngine = document.getElementById("test-engine");
const dateFormat = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", dateStyle: "short", timeStyle: "medium"
});
const results = {success: "성공", failed: "실패", started: "요청 시작", limited: "일일 한도 초과"};
const features = {
    "/api/logs": "업무 기록 조회", "/api/logs/classify": "업무 기록 자동 분류",
    "/api/logs/create": "업무 기록 등록", "/api/logs/update": "업무 기록 편집", "/api/logs/delete": "업무 기록 삭제",
    "/api/reports": "인수인계 보고서 조회", "/api/reports/generate": "인수인계 보고서 생성",
    "/api/reports/approve": "인수인계 보고서 승인",
    "/api/voice/process": "음성 기록 정리", "/api/voice/upload": "음성 파일 분석",
    "/api/docs": "기술 문서 조회", "/api/docs/upload": "기술 문서 등록", "/api/docs/qa": "기술 문서 질의",
    "/api/rag/query": "업무 지식 검색", "/api/anomalies/stats": "장애 통계 조회",
    "/api/anomalies/explain": "이상 징후 분석", "/api/priority/evaluate": "업무 우선순위 평가",
    "/api/improvements": "업무 개선 제안", "/api/translate": "보고서 번역", "/api/agent/command": "에이전트 명령",
    "/api/ai/command": "AI 명령", "/api/ai/confirm": "AI 명령 승인·취소",
    "/api/audit": "감사 기록 조회", "/api/settings/status": "Gemini 설정 확인", "/api/settings/test": "AI 생성 테스트"
};
let category = "login";
let selectedQuery = "";
let cursor = null;
let requestId = 0;

async function api(path, options) {
    const response = await fetch(path, options);
    if (response.status === 401) location.replace("/login");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "요청에 실패했습니다.");
    return data;
}

async function checkEngine() {
    try {
        const data = await api("/api/settings/status");
        testEngine.disabled = !(data.engine_ready && data.api_key_configured);
        if (!data.engine_ready) engineStatus.textContent = "BridgeCLI에 연결할 수 없습니다.";
        else if (!data.api_key_configured) engineStatus.textContent = "서버에 Gemini API 키를 설정하세요.";
        else engineStatus.textContent = "키 설정 완료. 생성 테스트로 응답을 확인할 수 있습니다.";
    } catch (error) {
        engineStatus.textContent = error.message;
    }
}

function cell(row, tag, value) {
    const element = document.createElement(tag);
    element.textContent = value;
    row.append(element);
    return element;
}

async function load(append = false) {
    const id = ++requestId;
    const isMembers = category === "members";
    const params = new URLSearchParams();
    if (append && cursor) params.set("before", cursor);
    if (selectedQuery) params.set("q", selectedQuery);
    if (!append) {
        cursor = null;
        rows.replaceChildren();
        columns.replaceChildren();
        const headings = isMembers ? ["아이디", "화이트리스트", "관리"] : ["한국 시간", "아이디", "기능", "결과"];
        for (const heading of headings) cell(columns, "th", heading).scope = "col";
    }
    more.hidden = true;
    message.textContent = "불러오는 중…";
    try {
        const data = await api(`/api/admin/${category}?${params}`);
        if (id !== requestId) return;
        cursor = data.next;
        more.hidden = !cursor;
        const entries = isMembers ? data.users : data.events;
        for (const entry of entries) {
            const row = document.createElement("tr");
            if (isMembers) {
                cell(row, "td", entry.username);
                cell(row, "td", entry.whitelisted ? "한도 면제" : "일일 3회");
                const button = document.createElement("button");
                button.textContent = entry.whitelisted ? "해제" : "추가";
                button.setAttribute("aria-label", `${entry.username} 화이트리스트 ${button.textContent}`);
                button.addEventListener("click", async () => {
                    const memberQuery = selectedQuery;
                    button.disabled = true;
                    try {
                        await api("/api/admin/whitelist", {
                            method: "POST",
                            headers: {"Content-Type": "application/json"},
                            body: JSON.stringify({user_id: entry.id, enabled: !entry.whitelisted})
                        });
                        if (category === "members" && selectedQuery === memberQuery) await load();
                    } catch (error) {
                        if (rows.contains(row)) message.textContent = error.message;
                        button.disabled = false;
                    }
                });
                cell(row, "td", "").append(button);
            } else {
                cell(row, "td", dateFormat.format(new Date(entry.created_at.replace(" ", "T") + "Z")));
                cell(row, "td", entry.username || "미입력");
                const feature = cell(row, "td", features[entry.feature] || entry.feature);
                if (features[entry.feature]) feature.title = entry.feature;
                cell(row, "td", results[entry.result] || entry.result);
            }
            rows.append(row);
        }
        message.textContent = entries.length ? "" : "표시할 기록이 없습니다.";
    } catch (error) {
        if (id === requestId) {
            more.hidden = !cursor;
            message.textContent = error.message;
        }
    }
}

for (const tab of tabs) {
    tab.addEventListener("click", () => {
        category = tab.dataset.category;
        for (const other of tabs) other.setAttribute("aria-pressed", String(other === tab));
        document.getElementById("section-title").textContent = tab.textContent;
        load();
    });
}
search.addEventListener("submit", (event) => {
    event.preventDefault();
    selectedQuery = query.value.trim();
    load();
});
document.getElementById("refresh").addEventListener("click", () => load());
more.addEventListener("click", () => load(true));
testEngine.addEventListener("click", async () => {
    testEngine.disabled = true;
    engineStatus.textContent = "Gemini 응답 확인 중…";
    try {
        const data = await api("/api/settings/test", {
            method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"
        });
        engineStatus.textContent = data.success ? `생성 성공 (${data.latency_ms}ms)` : data.error;
    } catch (error) {
        engineStatus.textContent = error.message;
    } finally {
        testEngine.disabled = false;
        if (["ai", "feature"].includes(category)) load();
    }
});
load();
checkEngine();
