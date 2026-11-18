const flows = {
    classify: [
        ["browser", "근무 중에 남긴 메모를 입력합니다", "발생 시각, 증상, 조치 결과, 다음 근무자가 확인할 내용을 적고 AI 자동 분류를 누릅니다."],
        ["web", "웹 서버가 기록을 받습니다", "입력값을 확인한 뒤 업무 항목을 분류할 요청을 BridgeCLI에 전달합니다."],
        ["bridge", "BridgeCLI가 Gemini를 호출합니다", "서버에 보관한 API 키를 사용해 기록 구조화와 누락 정보 확인을 요청합니다."],
        ["gemini", "업무 항목과 확인 질문을 생성합니다", "장비 ID, 티켓 번호, 후속 조치 등 11개 필드를 채우고, 확인이 필요한 정보를 질문으로 돌려줍니다."],
        ["browser", "담당자가 초안을 확인합니다", "누락된 정보를 보완하고 입력과 조치 결과를 확인한 뒤 업무 기록 저장을 선택합니다."],
        ["sqlite", "검토한 업무 기록을 보관합니다", "웹 서버가 업무 기록을 SQLite에 저장합니다. 다음 교대 보고서나 기록 검색에서 다시 조회할 수 있습니다."],
    ],
    report: [
        ["browser", "보고서를 만들 교대 기간을 선택합니다", "인계·인수 근무조와 교대 시작·종료 시각을 지정하고 보고서 생성을 누릅니다."],
        ["sqlite", "해당 교대의 업무 기록을 조회합니다", "웹 서버가 교대 기간의 기록과 그 전에 등록된 미완료 업무를 SQLite에서 가져옵니다."],
        ["bridge", "보고서 작성 요청을 보냅니다", "BridgeCLI가 서버 측 키로 업무 기록 요약과 보고서 생성을 Gemini에 요청합니다."],
        ["gemini", "8개 섹션의 초안을 만듭니다", "완료된 업무, 미완료 업무, 긴급 확인과 다음 교대 체크리스트 등을 정리합니다. 웹 서버가 결과를 검토 대기로 저장합니다."],
        ["browser", "담당자가 인수인계 내용을 검토합니다", "티켓 상태와 후속 조치가 맞는지 확인하고, 필요한 부분은 보고서에서 직접 수정합니다."],
        ["sqlite", "승인한 보고서를 보관합니다", "웹 서버가 최종 승인 상태와 승인자를 보관하며, 다음 근무조는 저장된 보고서에서 인계 내용을 확인합니다."],
    ],
};

const modes = document.querySelectorAll("[data-flow]");
const nodes = new Map([...document.querySelectorAll("[data-node]")].map(node => [node.dataset.node, node]));
const progress = document.getElementById("flow-progress");
const previous = document.getElementById("flow-prev");
const next = document.getElementById("flow-next");
const play = document.getElementById("flow-play");
const count = document.getElementById("step-count");
const nodeName = document.getElementById("step-node");
const title = document.getElementById("step-title");
const text = document.getElementById("step-text");

let flow = flows.classify;
let step = 0;
let timer = null;

function updatePlayback() {
    const playing = timer !== null;
    play.setAttribute("aria-pressed", String(playing));
    play.querySelector("span").textContent = playing ? "일시정지" : "재생";
    play.querySelector("i").classList.toggle("fa-play", !playing);
    play.querySelector("i").classList.toggle("fa-pause", playing);
}

function pause() {
    window.clearInterval(timer);
    timer = null;
    updatePlayback();
}

function showStep(index) {
    step = index;
    const [activeNode, heading, description] = flow[index];
    for (const [name, element] of nodes) {
        element.classList.toggle("active", name === activeNode);
    }
    for (const [position, button] of [...progress.children].entries()) {
        button.classList.toggle("past", position < index);
        if (position === index) button.setAttribute("aria-current", "step");
        else button.removeAttribute("aria-current");
    }
    count.textContent = `${String(index + 1).padStart(2, "0")} / ${String(flow.length).padStart(2, "0")}`;
    nodeName.textContent = nodes.get(activeNode).textContent.trim();
    title.textContent = heading;
    text.textContent = description;
    previous.disabled = index === 0;
    next.disabled = index === flow.length - 1;
}

function chooseFlow(button) {
    pause();
    flow = flows[button.dataset.flow];
    for (const mode of modes) mode.setAttribute("aria-pressed", String(mode === button));
    progress.replaceChildren(...flow.map(([, heading], index) => {
        const marker = document.createElement("button");
        marker.type = "button";
        marker.setAttribute("aria-label", `${index + 1}단계. ${heading}`);
        marker.title = heading;
        marker.addEventListener("click", () => {
            pause();
            showStep(index);
        });
        return marker;
    }));
    showStep(0);
}

for (const mode of modes) mode.addEventListener("click", () => chooseFlow(mode));
previous.addEventListener("click", () => {
    pause();
    showStep(step - 1);
});
next.addEventListener("click", () => {
    pause();
    showStep(step + 1);
});
play.addEventListener("click", () => {
    if (timer !== null) {
        pause();
        return;
    }
    if (next.disabled) showStep(0);
    timer = window.setInterval(() => {
        showStep(step + 1);
        if (next.disabled) pause();
    }, 3400);
    updatePlayback();
});
document.addEventListener("visibilitychange", () => {
    if (document.hidden) pause();
});
chooseFlow(modes[0]);
