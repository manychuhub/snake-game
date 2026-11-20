const flows = {
    classify: [
        ["browser", "근무 중에 남긴 메모를 입력합니다", "발생 시각, 증상, 조치 결과, 다음 근무자가 확인할 내용을 적고 AI 자동 분류를 누릅니다."],
        ["web", "웹 서버가 로그인과 입력을 확인합니다", "세션에서 사용자와 작업 공간을 확인한 뒤 분류 요청을 BridgeCLI에 전달합니다."],
        ["bridge", "BridgeCLI가 Gemini를 호출합니다", "서버에 보관한 API 키를 사용해 기록 구조화와 누락 정보 확인을 요청합니다."],
        ["gemini", "업무 항목과 확인 질문을 생성합니다", "장비 ID, 티켓 번호, 후속 조치 등 11개 필드를 채우고, 확인이 필요한 정보를 질문으로 돌려줍니다."],
        ["browser", "담당자가 초안을 확인합니다", "누락된 정보를 보완하고 입력과 조치 결과를 확인한 뒤 업무 기록 저장을 선택합니다."],
        ["sqlite", "검토한 업무 기록을 보관합니다", "웹 서버가 현재 작업 공간의 SQLite에 업무 기록을 저장합니다. 다음 교대 보고서나 기록 검색에서 다시 조회할 수 있습니다."],
    ],
    report: [
        ["browser", "보고서를 만들 교대 기간을 선택합니다", "인계·인수 근무조와 교대 시작·종료 시각을 지정하고 보고서 생성을 누릅니다."],
        ["sqlite", "해당 교대의 업무 기록을 조회합니다", "웹 서버가 현재 작업 공간의 SQLite에서 교대 기간 기록과 이전 미완료 업무를 가져옵니다."],
        ["bridge", "보고서 작성 요청을 보냅니다", "BridgeCLI가 서버 측 키로 업무 기록 요약과 보고서 생성을 Gemini에 요청합니다."],
        ["gemini", "8개 섹션의 초안을 만듭니다", "완료된 업무, 미완료 업무, 긴급 확인과 다음 교대 체크리스트 등을 정리합니다. 웹 서버가 결과를 검토 대기로 저장합니다."],
        ["browser", "담당자가 인수인계 내용을 검토합니다", "티켓 상태와 후속 조치가 맞는지 확인하고, 필요한 부분은 보고서에서 직접 수정합니다."],
        ["sqlite", "승인한 보고서를 보관합니다", "웹 서버가 승인 상태와 승인자를 작업 공간에 기록합니다. 같은 작업 공간의 다음 근무조는 저장된 보고서에서 인계 내용을 확인합니다."],
    ],
    account: [
        ["browser", "계정 설정을 엽니다", "로그인하면 기본 위치와 장소 종류를 확인할 수 있습니다. 값이나 비밀번호를 변경하고, 필요한 경우 계정 탈퇴를 선택합니다."],
        ["web", "세션에서 사용자 ID를 확인합니다", "서버는 로그인 세션의 사용자 ID로 읽기와 쓰기의 범위를 정합니다. 비밀번호 변경과 탈퇴에는 현재 비밀번호를 다시 확인합니다."],
        ["sqlite", "해당 계정의 변경 내용을 저장합니다", "기본 장소는 계정별 행에 저장됩니다. 비밀번호 변경이나 탈퇴가 완료되면 서버가 해당 계정의 모든 세션을 종료합니다."],
        ["browser", "다른 계정의 값이 화면에 남지 않게 지웁니다", "로그아웃이나 계정 전환 시 입력값과 이전 결과를 지웁니다. 다음 로그인에서 현재 계정의 설정을 다시 읽습니다."],
    ],
    migration: [
        ["sqlite", "SQLite 백업 복사본을 만듭니다", "원본을 읽기 전용으로 열어 웹 계정, 회원별 작업 공간, BridgeCLI DB를 복사합니다. 파일 무결성과 SHA-256을 확인합니다."],
        ["postgres", "빈 PostgreSQL 저장소에 데이터를 복원합니다", "계정과 작업 공간의 연결을 유지하고, 원본과 대상의 행 수와 내용이 일치할 때만 복원을 확정합니다. 기존 로그인 세션은 이전에서 제외됩니다."],
        ["postgres", "계정별 읽기와 쓰기를 검증합니다", "웹과 BridgeCLI에는 서로 다른 접속 권한을 부여합니다. 웹 저장소는 행 수준 보안으로 현재 계정과 작업 공간 범위의 조회와 수정을 허용합니다."],
        ["web", "검증된 저장소에서 앱을 시작합니다", "서버는 복원 확인과 행 수준 보안 상태를 검사합니다. 모의 데이터로 재시작 후 조회를 확인했으며, 운영 전환은 원본 백업 확보와 승인 이후 진행합니다."],
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
