"use strict";

(() => {
    if (demoMode) return;

    const byId = id => document.getElementById(id);
    const labels = {
        rackId: "랙", serverId: "서버", serialNumber: "시리얼 번호", ticketId: "티켓",
        part: "부품", status: "상태", operator: "담당자", handoverNote: "다음 교대 인계",
        rawText: "업무 원문", sku: "품목 코드", quantity: "수량", request: "요청",
        console: "콘솔", wipe: "와이핑", artifacts: "생성할 초안"
    };
    const filters = {night_incidents: "야간 장애 티켓", open_replacements: "미완료 하드웨어 교체"};
    const commands = {
        create_work_log: "업무 기록 등록", update_work_log_status: "티켓 상태 변경",
        append_handover_note: "인계 노트 추가", queue_media_disposal: "폐기 대기 전환",
        notify_replacement_owners: "교체 담당자 알림", navigate_rack_ports: "랙·포트 화면 열기",
        check_switch_port_link: "포트 링크 상태 확인", query_hdd_stock: "HDD 재고 조회",
        request_hdd_release: "HDD 반출 요청", register_disk_wipe: "와이핑 작업 등록",
        open_bmc_console: "BMC/IPMI 콘솔 승인", launch_bmc_console: "BMC/IPMI 콘솔 열기"
    };
    const resultLabels = {executed: "실행됨", cancelled: "취소됨", target_changed: "대상 변경",
        redirected: "콘솔 이동", expired: "승인 만료", unavailable: "사용 불가"};
    const viewLabels = {rack: "랙 상세", server: "서버 상세", ticket: "장애 티켓 상세", media: "저장 매체 상세"};
    const errorMessages = {
        400: "메시지 또는 화면 식별자 형식을 확인하세요.",
        401: "로그인이 필요합니다.",
        403: "이 요청을 실행할 권한이 없습니다.",
        404: "요청 대상을 찾을 수 없습니다.",
        409: "대상이 변경되었습니다. 다시 요청해 주세요.",
        429: "오늘의 AI 생성 한도를 사용했습니다."
    };

    const api = {
        command: body => callApi("/api/ai/command", body),
        confirm: body => callApi("/api/ai/confirm", body),
        activity: () => callApi("/api/ai/activity")
    };
    const mock = globalThis.createWorkspaceAiMock();
    let transport = api;
    let modeVersion = 0;
    let activityRequest = 0;
    let renderedLogs = [];
    let detailRecord = null;
    let detailContext = {};
    let mediaContext = {};
    let logFilter = null;
    const busy = new Map();

    function safeText(value) {
        return String(value ?? "")
            .replace(/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/g, "[가림]")
            .replace(/(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis(?:s)?):\/\/[^\s<>"']+/gi, "[가림]")
            .replace(/https?:\/\/[^\s/@]+:[^\s/@]+@[^\s<>"']+/gi, "[가림]")
            .replace(/\b(?:(?:Bearer|Basic)\s+[\w.+/=-]+|AIza[\w-]{35}|gh[pousr]_[\w]{30,}|github_pat_\w{30,}|(?:AKIA|ASIA)[A-Z0-9]{16}|sk-[\w-]{20,})(?=$|[^\w=])/gi, "[가림]")
            .replace(/\b[\w-]*?(?:password|passwd|pwd|secret|api[_ -]?key|token|credential|authorization|dsn|database[_ -]?url|[\w-]+key)["']?\s*[:=]\s*(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)|(?:비밀번호|토큰|API\s*키)\s*[:=]\s*\S+/gi, "[가림]");
    }

    async function callApi(path, body) {
        const response = await requestApi(path, body ? {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body)
        } : undefined);
        if (!response.ok) {
            const error = new Error(errorMessages[response.status] || "AI 서버가 요청을 처리하지 못했습니다.");
            error.status = response.status;
            throw error;
        }
        return response.json();
    }

    function shiftType() {
        const label = byId("currentShiftText").textContent.split("→")[0].trim();
        return label ? {shiftType: label} : {};
    }

    function activeContext() {
        return {view: document.querySelector(".tab-pane.active")?.id || "workspace", ...shiftType()};
    }

    function deviceContext(row) {
        const device = safeText(row.device_id);
        const target = {};
        for (const [key, tag, pattern] of [
            ["rackId", "rack|랙", "RACK-[\\w.-]+|R\\d+(?![\\w-])"],
            ["serverId", "server|서버", "(?:SRV|SVR)-[\\w.-]+"],
            ["serialNumber", "sn|serial|시리얼", "SN-[\\w.-]+"]
        ]) {
            const match = device.match(new RegExp(`(?:^|[^\\w-])(?:${tag})\\s*[:=]\\s*([\\w.-]+)`, "i"))
                || device.match(new RegExp(`(?:^|[^\\w-])(${pattern})`, "i"));
            if (match) target[key] = match[1];
        }
        if (!Object.keys(target).length && /^[A-Za-z0-9][\w.-]{0,127}$/.test(device)) target.serverId = device;
        const ticket = safeText(row.ticket_no).trim();
        if (ticket && !["-", "미확인", "[가림]"].includes(ticket)) target.ticketId = ticket;
        const part = device.match(/\bPART\s*[:=]\s*(HDD|SSD|NVMe|RAM|PSU|DIMM)\b/i)?.[1]
            || safeText(row.incident_type).match(/HDD|SSD|NVMe|RAM|DIMM|PSU|디스크|메모리|전원|파워/i)?.[0];
        const aliases = {"디스크": "HDD", "메모리": "RAM", "전원": "PSU", "파워": "PSU", DIMM: "RAM"};
        return {target, part: part && (aliases[part.toUpperCase()] || part.toUpperCase())};
    }

    function renderDetails(list, values) {
        list.replaceChildren();
        for (const [name, value] of Object.entries(values)) {
            if (!value) continue;
            const label = document.createElement("dt");
            label.textContent = labels[name] || name;
            const description = document.createElement("dd");
            description.textContent = safeText(value);
            list.append(label, description);
        }
    }

    function showDetail(row, kind) {
        const {target, part} = deviceContext(row);
        detailRecord = {id: row.id, kind};
        const view = part && kind !== "rack" ? `${kind}/${part.toLowerCase()}` : kind;
        detailContext = {...(kind === "rack" ? {rackId: target.rackId} : target), view, ...shiftType()};
        const heading = byId("dcoDetailTitle");
        heading.textContent = viewLabels[kind];
        const note = byId("dcoDetailNote");
        note.textContent = kind === "rack" || row.follow_up === "미확인" ? "" : safeText(row.follow_up);
        note.hidden = !note.textContent;
        renderDetails(byId("dcoDetailContext"), kind === "rack" ? {rackId: target.rackId}
            : {...target, part, status: row.status, operator: row.operator});
        for (const button of byId("dcoDetailActions").querySelectorAll("[data-requires]")) {
            button.hidden = !detailContext[button.dataset.requires];
        }
        byId("dcoDetailInput").value = "";
        byId("dcoDetailLog").replaceChildren();
        if (!byId("dcoDetail").open) byId("dcoDetail").showModal();
        byId("dcoDetailInput").focus();
    }

    function refreshDetail() {
        if (!detailRecord || !byId("dcoDetail").open) return;
        const row = renderedLogs.find(item => item.id === detailRecord.id);
        if (!row || detailRecord.kind === "rack") return;
        const {target, part} = deviceContext(row);
        renderDetails(byId("dcoDetailContext"), {...target, part, status: row.status, operator: row.operator});
        const note = byId("dcoDetailNote");
        note.textContent = row.follow_up === "미확인" ? "" : safeText(row.follow_up);
        note.hidden = !note.textContent;
    }

    function openMedia(context = {}) {
        mediaContext = context;
        byId("dcoMediaSerial").value = context.serialNumber || "";
        byId("dcoMediaInput").value = "";
        byId("dcoMediaLog").replaceChildren();
        if (byId("dcoDetail").open) byId("dcoDetail").close();
        byId("dcoMedia").showModal();
        byId("dcoMediaSerial").focus();
    }

    function setLogFilter(filter) {
        logFilter = Object.hasOwn(filters, filter) ? filter : null;
        const badge = byId("dcoWorkLogFilter");
        badge.hidden = !logFilter;
        badge.textContent = logFilter === "night_incidents"
            ? "야간 장애 티켓 · 기록 시각 20:00~07:59" : filters[logFilter] || "";
    }

    function showFilteredLogs(filter) {
        if (!Object.hasOwn(filters, filter)) return;
        setLogFilter(filter);
        for (const button of byId("workLogFilters").querySelectorAll("button")) button.classList.remove("active");
        switchTab("tab-classify", document.querySelector('[aria-controls="tab-classify"]'));
        loadWorkLogs(null);
        byId("workLogsTable").scrollIntoView({block: "nearest"});
    }

    function replyNode(value, className) {
        const node = document.createElement("div");
        node.className = className;
        node.textContent = safeText(value);
        return node;
    }

    function renderAction(action) {
        if (action?.name === "filter_work_logs") {
            showFilteredLogs(action.filter);
        }
        if (action?.name === "navigate_rack_ports" && action.view === "tab-rack-ports") {
            showDetail({device_id: "rack:" + action.rackId}, "rack");
            byId("dcoDetailTitle").textContent = "랙·포트 상세";
            const note = byId("dcoDetailNote");
            const rows = (action.switches || []).map(item => {
                const ports = item.ports.map(port => port === action.portId ? port + " (선택)" : port);
                return "스위치 " + item.id + " · 포트 " + (ports.join(", ") || "미등록");
            });
            note.textContent = safeText(rows.join("\n") || "등록된 스위치가 없습니다.");
            note.style.whiteSpace = "pre-line";
            note.hidden = false;
        }

    }

    function afterExecution() {
        loadWorkLogs();
        if (byId("tab-report").classList.contains("active")) refreshActivity();
    }

    function renderConfirmationResult(status, confirmed, proposal, provider) {
        const reply = safeText(confirmed.reply);
        status.textContent = reply;
        const id = proposal.confirmationId;
        if (provider !== api || confirmed.status !== "executed" || confirmed.auditLog?.command !== "open_bmc_console"
                || !/^[a-f0-9]{32}$/.test(id)) return;
        const path = "/api/ai/console/" + id;
        if (!reply.endsWith("\n" + path)) return;
        status.textContent = reply.slice(0, -(path.length + 1)) + " ";
        const link = document.createElement("a");
        link.className = "dco-link";
        link.textContent = "BMC/IPMI 콘솔 열기";
        link.href = path;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        status.append(link);
    }

    function renderConfirmation(bubble, proposal, provider, version) {
        const card = document.createElement("section");
        card.className = "dco-confirmation";
        const heading = document.createElement("strong");
        heading.textContent = "변경 승인 필요";
        card.append(heading, replyNode(proposal.summary, "agent-reply"));
        const details = document.createElement("dl");
        details.className = "dco-context";
        const changes = Object.fromEntries(Object.entries(proposal.changes || {}).map(([key, value]) => [
            key, value && typeof value === "object" && "from" in value && "to" in value
                ? `${value.from ?? "미지정"} → ${value.to ?? "미지정"}`
                : typeof value === "string" ? value : JSON.stringify(value)
        ]));
        renderDetails(details, {...proposal.target, ...changes});
        card.append(details);

        const controls = document.createElement("div");
        controls.className = "dco-shortcuts";
        const status = replyNode("", "dco-notice");
        status.setAttribute("role", "status");
        status.tabIndex = -1;
        for (const approved of [true, false]) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = approved ? "btn-primary" : "btn-sample";
            button.textContent = approved ? "승인" : "취소";
            button.addEventListener("click", async () => {
                if (version !== modeVersion || button.disabled) return;
                for (const control of controls.children) control.disabled = true;
                status.textContent = "처리 중…";
                try {
                    const confirmed = await provider.confirm({confirmationId: proposal.confirmationId, approved});
                    if (version !== modeVersion) return;
                    renderConfirmationResult(status, confirmed, proposal, provider);
                    controls.remove();
                    if (card.isConnected) status.focus();
                    if (confirmed.status === "executed") afterExecution();
                    else if (byId("tab-report").classList.contains("active")) refreshActivity();
                } catch (error) {
                    if (version !== modeVersion) return;
                    status.textContent = safeText(error.message || "처리 결과를 가져오지 못했습니다.");
                    if ([401, 403, 404, 409, 410].includes(error.status)) controls.remove();
                    else for (const control of controls.children) control.disabled = false;
                }
            });
            controls.append(button);
        }
        card.append(controls, status);
        bubble.append(card);
    }

    async function send(input, log, context, prompt) {
        const message = safeText((prompt ?? input.value).trim());
        if (!message || busy.get(log) === modeVersion) return;
        if (message === "인계 노트 추가:") {
            input.focus();
            return;
        }
        if (prompt === undefined) input.value = "";
        const provider = transport;
        const version = modeVersion;
        busy.set(log, version);
        const pending = replyNode("응답을 준비하고 있습니다…", "chat-bubble ai");
        log.append(replyNode(message, "chat-bubble user"), pending);
        log.scrollTop = log.scrollHeight;
        try {
            const response = await provider.command({message, context});
            if (version !== modeVersion || !pending.isConnected) return;
            if (!["answer", "action_executed", "pending_confirmation"].includes(response.type)) {
                throw new Error("AI 응답 형식을 확인할 수 없습니다.");
            }
            pending.replaceChildren(replyNode(response.reply, "agent-reply"));
            if (response.type === "pending_confirmation") renderConfirmation(pending, response, provider, version);
            if (response.type === "action_executed") {
                renderAction(response.action);
                if (response.auditLog) afterExecution();
            }
        } catch (error) {
            if (version === modeVersion) pending.textContent = safeText(error.message || "AI 요청을 처리하지 못했습니다.");
        } finally {
            if (busy.get(log) === version) busy.delete(log);
            log.scrollTop = log.scrollHeight;
        }
    }

    function timeLabel(stamp) {
        const date = new Date(stamp);
        return Number.isNaN(date.getTime()) ? safeText(stamp) : date.toLocaleString("ko-KR");
    }

    async function refreshActivity() {
        const provider = transport;
        const request = ++activityRequest;
        const status = byId("dcoAuditStatus");
        status.textContent = "AI 인계 이력을 불러오는 중…";
        try {
            const {auditLogs, notifications} = await provider.activity();
            if (request !== activityRequest) return;
            const list = byId("dcoNotifications");
            list.replaceChildren();
            for (const notice of notifications) {
                const entry = document.createElement("li");
                entry.textContent = safeText(`${timeLabel(notice.timestamp)} · ${notice.sender} · ${notice.ticketId} 교체 확인 요청`);
                list.append(entry);
            }
            if (!list.childElementCount) {
                const empty = document.createElement("li");
                empty.textContent = "받은 작업 알림이 없습니다.";
                list.append(empty);
            }

            const rows = byId("dcoAuditRows");
            rows.replaceChildren();
            for (const event of auditLogs) {
                const row = rows.insertRow();
                for (const value of [timeLabel(event.timestamp), event.actor, commands[event.command] || event.command,
                    event.targetId || "—", resultLabels[event.result] || event.result]) {
                    row.insertCell().textContent = safeText(value);
                }
            }
            status.textContent = auditLogs.length ? "" : "표시할 AI 감사 로그가 없습니다.";
        } catch {
            if (request === activityRequest) status.textContent = "AI 인계 이력을 불러오지 못했습니다.";
        }
    }

    function bindSurface(form, area, input, log, context) {
        byId(form).addEventListener("submit", event => {
            event.preventDefault();
            send(byId(input), byId(log), context());
        });
        byId(area).addEventListener("click", event => {
            const button = event.target.closest("[data-prompt]");
            if (!button) return;
            const field = byId(input);
            if (button.hasAttribute("data-fill")) {
                field.value = button.dataset.prompt;
                field.focus();
            } else {
                send(field, byId(log), context(), button.dataset.prompt);
            }
        });
    }

    function setMode(mockEnabled) {
        transport = mockEnabled ? mock : api;
        modeVersion++;
        byId("dcoMockNotice").hidden = !mockEnabled;
        byId("dcoMode").value = mockEnabled ? "mock" : "api";
        for (const id of ["dcoCommandLog", "dcoDetailLog", "dcoMediaLog", "agentChatContainer",
            "dcoNotifications", "dcoAuditRows"]) byId(id).replaceChildren();
        for (const id of ["dcoCommandInput", "dcoDetailInput", "dcoMediaInput", "agentInput"]) byId(id).value = "";
        for (const id of ["dcoDetail", "dcoMedia"]) if (byId(id).open) byId(id).close();
        renderedLogs = [];
        setLogFilter(null);
        document.querySelector("#workLogFilters .active")?.classList.remove("active");
        document.querySelector("#workLogFilters button")?.classList.add("active");
        loadWorkLogs(null);
        refreshActivity();
    }

    globalThis.workspaceAi = {
        get logFilter() { return logFilter; },
        get isMock() { return transport === mock; },
        mockLogs: status => transport === mock ? mock.logs(status, logFilter) : null,
        setLogFilter,
        setLogs(logs) { renderedLogs = logs; refreshDetail(); },
        refreshActivity,
        sendFromAgent: () => send(byId("agentInput"), byId("agentChatContainer"), activeContext()),
        logLinks(row, index) {
            const {target} = deviceContext(row);
            const link = (kind, label) =>
                `<button type="button" class="dco-record-link" data-log-index="${index}" data-detail="${kind}">${label}</button>`;
            const deviceLinks = [];
            if (target.rackId) deviceLinks.push(link("rack", escapeHtml(target.rackId)));
            if (target.serverId) deviceLinks.push(link("server", escapeHtml(target.serverId)));
            if (target.serialNumber && !target.serverId) deviceLinks.push(link("media", escapeHtml(target.serialNumber)));
            return {device: deviceLinks.join(" ") || escapeHtml(safeText(row.device_id || "-")),
                ticket: target.ticketId ? link("ticket", escapeHtml(target.ticketId)) : escapeHtml(safeText(row.ticket_no || "-"))};
        }
    };

    document.addEventListener("DOMContentLoaded", () => {
        byId("workspaceAi").hidden = false;
        byId("dcoActivity").hidden = false;
        byId("dcoMode").addEventListener("change", event => setMode(event.target.value === "mock"));
        bindSurface("dcoCommandForm", "workspaceAi", "dcoCommandInput", "dcoCommandLog", activeContext);
        bindSurface("dcoDetailForm", "dcoDetailActions", "dcoDetailInput", "dcoDetailLog", () => detailContext);
        byId("workLogsTbody").addEventListener("click", event => {
            const button = event.target.closest("[data-log-index]");
            const row = button && renderedLogs[Number(button.dataset.logIndex)];
            if (row) showDetail(row, button.dataset.detail);
        });
        byId("openAiActivity").addEventListener("click", () => {
            switchTab("tab-report", document.querySelector('[aria-controls="tab-report"]'));
            byId("dcoActivityTitle").focus();
        });
        byId("refreshAiActivity").addEventListener("click", refreshActivity);
        byId("openMediaExecutor").addEventListener("click", () => openMedia());
        byId("detailMediaExecutor").addEventListener("click", () => openMedia(detailContext));
        for (const button of document.querySelectorAll("[data-close-dialog]")) {
            button.addEventListener("click", () => button.closest("dialog").close());
        }
        byId("dcoMediaForm").addEventListener("submit", event => {
            event.preventDefault();
            const serialNumber = byId("dcoMediaSerial").value.trim();
            const selected = serialNumber.toLowerCase() === mediaContext.serialNumber?.toLowerCase() ? mediaContext : {};
            const prompt = event.submitter?.value || undefined;
            send(byId("dcoMediaInput"), byId("dcoMediaLog"), {...selected, view: "media", ...shiftType(), serialNumber}, prompt);
        });
    });
})();
