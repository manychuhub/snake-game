"use strict";

globalThis.createWorkspaceAiMock = function () {
    const rows = [
        {id: 901, execution_time: "02:15", operator: "dco-demo", device_id: "RACK-A12 SRV-021 SN-HDD021 PART:HDD",
            ticket_no: "TT-DEMO-021", incident_type: "HDD 장애", action_taken: "예비 HDD 교체 대기",
            result: "SMART 경보 확인", status: "미완료", follow_up: "교체 후 상태를 확인하세요."},
        {id: 902, execution_time: "04:35", operator: "dco-demo", device_id: "RACK-A12 SRV-023 PART:RAM",
            ticket_no: "TT-DEMO-023", incident_type: "RAM 장애", action_taken: "RAM 교체",
            result: "재부팅 후 정상", status: "추가점검", follow_up: "다음 교대에서 오류 카운터를 확인하세요."},
        {id: 903, execution_time: "14:20", operator: "dco-demo", device_id: "RACK-B03 SRV-031 PART:PSU",
            ticket_no: "TT-DEMO-031", incident_type: "전원 모듈", action_taken: "전원 모듈 교체",
            result: "전원 이중화 확인", status: "완료", follow_up: "경보 해제 확인"},
        {id: 904, execution_time: "12:30", operator: "dco-demo", device_id: "RACK-B03 SRV-032 SN-DEMO-041 PART:SSD",
            ticket_no: "TT-DEMO-041", incident_type: "저장 매체 삭제", action_taken: "삭제 증적 검토",
            result: "삭제 검증 완료", status: "완료", follow_up: "폐기 증적 첨부 대기"}
    ].map(row => ({priority_tier: "P2", priority_score: 75, ...row}));
    const pending = new Map();
    const auditLogs = [];
    const notifications = [];
    let sequence = 0;

    function answer(reply) {
        return {type: "answer", reply};
    }

    function event(command, targetId, result = "executed") {
        const auditLog = {timestamp: new Date().toISOString(), actor: "dco-demo", command, targetId, result};
        auditLogs.unshift(auditLog);
        return auditLog;
    }

    function action(name, reply, values = {}, auditLog) {
        return {type: "action_executed", reply, action: {name, ...values}, auditLog};
    }

    function propose(row, status, target, command) {
        if (row.status === status) return answer("가상 기록에 이미 해당 상태가 적용되어 있습니다.");
        const confirmationId = `mock-${++sequence}`;
        pending.set(confirmationId, {row, from: row.status, status, command, target});
        return {
            type: "pending_confirmation", confirmationId, target, changes: {status: {from: row.status, to: status}},
            summary: `가상 기록 #${row.id}의 상태를 변경합니다.`, reply: "가상 변경을 승인하시겠습니까?"
        };
    }

    function stage(command, target, changes, summary, extra = {}) {
        const confirmationId = "mock-" + ++sequence;
        pending.set(confirmationId, {command, target, ...extra});
        return {type: "pending_confirmation", confirmationId, target, changes, summary, reply: "가상 작업을 승인하시겠습니까?"};
    }

    function logs(status, filter) {
        return rows.filter(row => (!status || row.status === status) &&
            (filter !== "night_incidents" || /^(0[0-7]|2[0-3]):/.test(row.execution_time)) &&
            (filter !== "open_replacements" || (["미완료", "추가점검", "대기"].includes(row.status) && row.action_taken.includes("교체"))));
    }

    function recordTarget(row) {
        const target = {ticketId: row.ticket_no};
        for (const [key, prefix] of Object.entries({rackId: "RACK-", serverId: "SRV-", serialNumber: "SN-"})) {
            const identifier = row.device_id.split(" ").find(value => value.startsWith(prefix));
            if (identifier) target[key] = identifier;
        }
        return target;
    }

    function command({message, context}) {
        const phrase = message.trim().replace(/[ .!]+$/, "");
        if (/^야간 장애 티켓(?: |$)/.test(phrase)) {
            return action("filter_work_logs", "가상 야간 장애 티켓을 표시합니다.", {filter: "night_incidents"});
        }
        if (/^미완료 하드웨어 교체 담당자(?:에게)? 알림 (?:보내|보내 줘|보내줘|전송)$/.test(phrase)) {
            const replacements = logs(null, "open_replacements");
            if (!replacements.length) return answer("알릴 가상 교체 기록이 없습니다.");
            for (const row of replacements) {
                notifications.unshift({timestamp: new Date().toISOString(), sender: "dco-demo", ticketId: row.ticket_no});
                event("notify_replacement_owners", row.ticket_no);
            }
            return action("notify_replacement_owners", `가상 담당자 알림 ${replacements.length}건을 등록했습니다.`, {},
                auditLogs[0]);
        }
        if (/^미완료 하드웨어 교체(?: 목록)?(?: (?:열어|보여\s*줘|조회))?$/.test(phrase)) {
            return action("filter_work_logs", "가상 미완료 하드웨어 교체 목록을 표시합니다.", {filter: "open_replacements"});
        }
        if (/IPMI 콘솔/i.test(phrase)) {
            const serverId = context.serverId || phrase.match(/\bSRV-[\w-]+\b/i)?.[0];
            const server = rows.find(row => recordTarget(row).serverId === serverId);
            return server
                ? stage("open_bmc_console", recordTarget(server), {console: "가상 서버 연결"}, "가상 IPMI 콘솔 접근을 요청합니다.")
                : answer("가상 서버 상세에서 IPMI 콘솔 명령을 실행하세요.");
        }

        if (phrase.startsWith("/기록 ")) {
            const target = Object.fromEntries(["rackId", "serverId", "serialNumber", "ticketId"]
                .filter(key => context[key]).map(key => [key, context[key]]));
            return stage("create_work_log", target, {rawText: phrase.slice(4), status: "미완료"}, "가상 업무 기록을 등록합니다.");
        }
        if (context.view === "media") {
            const row = rows.find(item => item.incident_type === "저장 매체 삭제" &&
                recordTarget(item).serialNumber?.toLowerCase() === context.serialNumber?.toLowerCase());
            if (!row) return answer("해당 시리얼 번호의 가상 삭제 기록이 없습니다. SN-DEMO-041을 사용할 수 있습니다.");
            if (/^폐기 대기/.test(phrase)) return propose(row, "폐기 대기", recordTarget(row), "queue_media_disposal");
            if (/증적.*초안/.test(phrase)) {
                return answer(`가상 폐기 증적 초안\n시리얼 번호  ${recordTarget(row).serialNumber}\n삭제 기록  #${row.id}\n삭제 검증  ${row.result}\n현재 상태  ${row.status}\n입회자 및 증적 첨부  확인 필요`);
            }
            if (/삭제 로그.*검증/.test(phrase)) return answer(`가상 삭제 기록 #${row.id}에서 삭제 검증 완료를 확인했습니다.`);
        }

        const ticket = context.ticketId || phrase.match(/\bTT-DEMO-\d+\b/i)?.[0];
        const row = rows.find(item => item.ticket_no === ticket?.toUpperCase());
        const note = message.match(/^(?:\/인계\s+|인계\s*노트\s*추가\s*[:：]\s*)(.+)$/s);
        if (note && row) {
            return stage("append_handover_note", recordTarget(row), {handoverNote: note[1]},
                "가상 인계 노트를 추가합니다.", {row, from: row.status, note: note[1]});
        }
        const status = phrase.match(/(미완료|완료|추가점검|대기)(?:로)?\s*(?:변경|처리|설정)/)?.[1];
        if (row && status) return propose(row, status, recordTarget(row), "update_work_log_status");
        if (/절차|규정|SOP|진단/.test(phrase)) {
            const part = context.view?.split("/")[1]?.toUpperCase();
            return answer(`가상 SOP 예시${part ? ` (${part})` : ""}\n교대 기록과 경보를 비교한 뒤 승인된 현장 절차서에서 장비별 점검 항목을 확인하세요.`);
        }
        const scoped = rows.filter(item => {
            const target = recordTarget(item);
            return item === row || (context.rackId && target.rackId === context.rackId) ||
                (context.serverId && target.serverId === context.serverId);
        });
        if (scoped.length) {
            return answer(scoped.map(item => `${item.ticket_no} · ${item.status}\n${item.result}\n${item.follow_up}`).join("\n\n"));
        }
        return answer("가상 업무 기록에서 랙·서버·티켓을 선택하거나 상단 추천 명령을 실행하세요.");
    }

    function confirm({confirmationId, approved}) {
        const item = pending.get(confirmationId);
        if (!item) throw new Error("모의 승인 요청을 찾을 수 없습니다.");
        if (item.response) return item.response;
        const unchanged = !item.row || item.row.status === item.from;
        const result = !approved ? "cancelled" : unchanged ? "executed" : "target_changed";
        let targetId = item.row && String(item.row.id);
        if (result === "executed") {
            if (item.note) item.row.follow_up += "\n[dco-demo] " + item.note;
            if (item.status) item.row.status = item.status;
            if (item.command === "create_work_log") {
                targetId = String(900 + rows.length + 1);
                rows.unshift({id: Number(targetId), execution_time: "미확인", operator: "dco-demo",
                    device_id: [item.target.rackId, item.target.serverId, item.target.serialNumber].filter(Boolean).join(" "),
                    ticket_no: item.target.ticketId, status: "미완료", follow_up: "", priority_score: 50, priority_tier: "P3"});
            }
        }
        const reply = {executed: "가상 요청을 처리했습니다.", cancelled: "가상 변경을 취소했습니다.",
            target_changed: "가상 대상 상태가 바뀌었습니다. 다시 확인해 주세요."}[result];
        item.response = {status: result === "executed" ? "executed" : "cancelled", reply,
            auditLog: event(item.command,
                item.command === "queue_media_disposal" ? item.target.serialNumber : targetId || item.target.serverId, result)};
        return item.response;
    }

    return {command, confirm, logs, activity: () => ({auditLogs, notifications})};
};
