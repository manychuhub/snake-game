/**
 * SHIFT BRIDGE - AWS DCO AI 인수인계 시스템 프론트엔드 컨트롤러
 * 10대 핵심 기능 풀스택 바인딩 및 인터랙션 모듈
 */

// 현재 분석된 임시 데이터 저장소
let currentClassifiedData = null;
let currentReportId = null;
let currentReportMarkdown = "";
let isReportEditMode = false;
let speechRecognitionInstance = null;
let isRecording = false;
const demoMode = ["/demo", "/demo/"].includes(window.location.pathname);

function requestApi(path, options) {
    if (!demoMode) return fetch(path, options);
    if ((options?.method || "GET") !== "GET") {
        return Promise.reject(new Error("가상 기록을 보는 공개 체험입니다."));
    }
    return fetch(`/demo${path}`);
}

// 페이지 초기화
document.addEventListener("DOMContentLoaded", () => {
    if (demoMode) {
        document.body.classList.add("demo-mode");
        document.getElementById("demo-notice").hidden = false;
        document.getElementById("demo-login").hidden = false;
        document.getElementById("activeOperatorName").textContent = "예시 당직자";
        document.getElementById("site-region").textContent = "가상 환경";
        document.getElementById("site-datacenter").textContent = "예시 데이터센터";
        for (const id of ["operatorNameInput", "reportAuthor", "approverNameInput"]) {
            document.getElementById(id).value = "예시 당직자";
        }
        for (const field of document.querySelectorAll("main input, main textarea, main select")) {
            if (field.type === "file" || field.tagName === "SELECT") field.disabled = true;
            else field.readOnly = true;
        }
        for (const control of document.querySelectorAll("main button:not(.btn-filter)")) control.disabled = true;
        for (const zone of document.querySelectorAll(".upload-zone, #micBtn")) zone.inert = true;
    } else {
        checkApiKeyStatus();
    }
    loadWorkLogs();
    loadTechnicalDocs();
    loadAnomalyStatistics();
    loadHandoverReports();
    const end = new Date(Math.ceil(Date.now() / 60000) * 60000);
    const start = new Date(end.getTime() - 12 * 60 * 60 * 1000);
    for (const [id, date] of [["reportStart", start], ["reportEnd", end]]) {
        const local = new Date(date.getTime() - date.getTimezoneOffset() * 60 * 1000);
        document.getElementById(id).value = local.toISOString().slice(0, 16);
    }
});

// =============================================================================
// 탭 전환 핸들러
// =============================================================================
function switchTab(tabId, btnElement) {
    document.querySelectorAll(".tab-pane").forEach(pane => pane.classList.remove("active"));
    document.querySelectorAll(".nav-tab").forEach(btn => {
        btn.classList.remove("active");
        btn.removeAttribute("aria-current");
    });

    const targetPane = document.getElementById(tabId);
    if (targetPane) targetPane.classList.add("active");
    if (btnElement) {
        btnElement.classList.add("active");
        btnElement.setAttribute("aria-current", "page");
        document.getElementById("workspaceHeading").textContent = btnElement.dataset.heading || btnElement.textContent.trim();
    }
    window.scrollTo(0, 0);

    // 탭별 새로고침 트리거
    if (tabId === "tab-stats") loadAnomalyStatistics();
    if (tabId === "tab-priority") loadPriorityTasks();
    if (tabId === "tab-report") loadHandoverReports();
    if (tabId === "tab-docs") loadTechnicalDocs();
}

// =============================================================================
// 기능 1 & 3: 자유 형식 업무 기록 분석, 자동 분류, 누락 정보 보완
// =============================================================================

function setSampleLog(type) {
    const input = document.getElementById("rawLogInput");
    if (type === 1) {
        input.value = "오늘 02:40 Hall-A 랙 #R14 호스트 svr-kr-a14-03에서 DIMM 채널B2 다중 ECC 에러 발생함. 티켓 #TT-49211 열고 블레이드 오프라인으로 뺀 다음 예비 DDR5 64GB 모듈로 교체 장착 완료함. POST 통과 및 메모리 진단 정상 복구 확인됨. 결함 부품은 RMA 랙에 둠.";
    } else if (type === 2) {
        input.value = "04:15 Hall-C 광케이블 분배함 FDP#02 코어 스위치 sw-core-c01 포트 48번 링크 플래핑 현상 접수 (티켓 #TT-49280). OTDR 찍어보니 감쇠 7.8dB 나옴. MPO-LC 5m 케이블 재고 없어서 교체 못함. 주간조 입고되는 대로 신규 포설 작업 해야 함.";
    } else if (type === 3) {
        input.value = "05:00 Hall-B 랙 #32 32번 서버 svr-kr-b32-01에서 동일 파워 PSU#1 쿨링팬 RPM 저하 및 과열 경보 발생. 티켓 #TT-49330. PDU 전원은 정상이나 팬 베어링 마모 추정. 예비 1200W Hot-swap PSU 교체 필요.";
    }
}

async function analyzeAndClassifyLog() {
    const rawText = document.getElementById("rawLogInput").value.trim();
    const operator = document.getElementById("operatorNameInput").value.trim();
    const btn = document.getElementById("btnClassify");
    const statusBadge = document.getElementById("classifyStatusBadge");

    if (!rawText) {
        alert("분석할 업무 내용을 입력해 주세요.");
        return;
    }

    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Gemini 분석 중...`;
    statusBadge.textContent = "AI 심층 분석 중";
    statusBadge.className = "badge-status check";

    try {
        const res = await requestApi("/api/logs/classify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ raw_text: rawText, operator: operator })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        // 연산자 오버라이드 (입력한 작성자 반영)
        if (operator && data.operator === "미확인") {
            data.operator = operator;
        }

        currentClassifiedData = data;
        renderClassifiedPreview(data);

        // 누락 정보 알림창 처리 (Quality QA)
        const missingBox = document.getElementById("missingInfoBox");
        const missingList = document.getElementById("missingQuestionsList");
        const alerts = data.missing_alerts || [];

        if (alerts.length > 0) {
            missingList.innerHTML = "<ul>" + alerts.map(a => `<li>• <strong>${escapeHtml(a.issue)}</strong> ➔ <em>${escapeHtml(a.question)}</em></li>`).join("") + "</ul>";
            missingBox.style.display = "block";
        } else {
            missingBox.style.display = "none";
        }

        document.getElementById("btnSaveLog").disabled = false;
        statusBadge.textContent = "분류 완료 (검토 대기)";
        statusBadge.className = "badge-status complete";

    } catch (err) {
        alert("분석 실패: " + err.message);
        statusBadge.textContent = "분석 오류";
        statusBadge.className = "badge-status pending";
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles"></i> AI 자동 분류 분석`;
    }
}

function renderClassifiedPreview(data) {
    const fields = [
        "execution_time", "operator", "device_id", "ticket_no",
        "incident_type", "cause", "action_taken", "result",
        "status", "follow_up", "remarks"
    ];

    fields.forEach(field => {
        const el = document.getElementById(`res-${field}`);
        if (!el) return;
        const val = data[field];

        if (!val || val === "미확인") {
            el.innerHTML = `<span class="badge-unconfirmed">미확인</span>`;
        } else {
            if (field === "status") {
                let badgeClass = val === "완료" ? "complete" : (val === "미완료" ? "pending" : "check");
                el.innerHTML = `<span class="badge-status ${badgeClass}">${escapeHtml(val)}</span>`;
            } else {
                el.textContent = val;
            }
        }
    });
}

function applyMissingInfoAnswer() {
    const ansInput = document.getElementById("missingAnswerInput");
    const ans = ansInput.value.trim();
    if (!ans || !currentClassifiedData) return;

    // 미확인 필드들에 답변을 지능적으로 병합
    if (currentClassifiedData.ticket_no === "미확인" && ans.includes("TT-")) {
        const match = ans.match(/TT-[\d\w]+/i);
        if (match) currentClassifiedData.ticket_no = match[0].toUpperCase();
    }
    if (currentClassifiedData.result === "미확인" && (ans.includes("정상") || ans.includes("확인") || ans.includes("복구"))) {
        currentClassifiedData.result = ans;
    } else {
        currentClassifiedData.remarks = (currentClassifiedData.remarks === "미확인" ? "" : currentClassifiedData.remarks + " | ") + `[엔지니어 보완] ${ans}`;
    }

    renderClassifiedPreview(currentClassifiedData);
    ansInput.value = "";
    document.getElementById("missingInfoBox").style.display = "none";
    alert("✅ 누락 정보가 업무 기록에 성공적으로 보완 반영되었습니다.");
}

async function saveClassifiedLog() {
    if (!currentClassifiedData) return;

    const btn = document.getElementById("btnSaveLog");
    btn.disabled = true;

    try {
        const res = await requestApi("/api/logs/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(currentClassifiedData)
        });
        const result = await res.json();
        if (result.success) {
            alert(`✅ 업무 기록 #${result.log.id}이 성공적으로 데이터베이스에 영구 등록되었습니다.`);
            document.getElementById("rawLogInput").value = "";
            document.getElementById("btnSaveLog").disabled = true;
            document.getElementById("missingInfoBox").style.display = "none";
            loadWorkLogs();
            loadAnomalyStatistics();
        }
    } catch (err) {
        alert("저장 실패: " + err.message);
    } finally {
        btn.disabled = false;
    }
}

async function loadWorkLogs(statusFilter = null) {
    const tbody = document.getElementById("workLogsTbody");
    try {
        let url = "/api/logs";
        if (statusFilter) url += `?status=${encodeURIComponent(statusFilter)}`;
        const res = await requestApi(url);
        const data = await res.json();
        const logs = data.logs || [];

        if (demoMode && !statusFilter && logs.length) {
            document.getElementById("rawLogInput").value = logs[0].raw_text;
            document.getElementById("classifyStatusBadge").textContent = "가상 분류 결과";
            renderClassifiedPreview(logs[0]);
        }

        if (logs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; padding: 25px; color: var(--text-muted);">등록된 업무 기록이 없습니다.</td></tr>`;
            return;
        }

        tbody.innerHTML = logs.map(l => {
            const statusClass = l.status === "완료" ? "complete" : (l.status === "미완료" ? "pending" : "check");
            const tierClass = `tier-${escapeHtml(l.priority_tier || 'P3')}`;
            return `
            <tr>
                <td><strong>#${l.id}</strong></td>
                <td>${escapeHtml(l.execution_time || '-')}</td>
                <td>${escapeHtml(l.operator || '-')}</td>
                <td><code style="color: #38bdf8;">${escapeHtml(l.device_id || '-')}</code></td>
                <td><strong>${escapeHtml(l.ticket_no || '-')}</strong></td>
                <td>${escapeHtml(l.incident_type || '-')}</td>
                <td>
                    <div style="font-weight: 500;">${escapeHtml(l.action_taken || '-')}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 2px;">결과: ${escapeHtml(l.result || '-')}</div>
                </td>
                <td><span class="badge-status ${statusClass}">${escapeHtml(l.status)}</span></td>
                <td><span class="tier-badge ${tierClass}">${escapeHtml(l.priority_tier || 'P3')} (${escapeHtml(String(l.priority_score))}점)</span></td>
                <td>
                    <button class="btn-sample" style="color: #f87171; border-color: #ef4444;" onclick="deleteLog(${l.id})">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </td>
            </tr>
            `;
        }).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="10" style="color: #f87171; text-align: center;">로딩 실패: ${e.message}</td></tr>`;
    }
}

function filterLogs(status, btnElement) {
    document.querySelectorAll(".btn-filter").forEach(b => b.classList.remove("active"));
    if (btnElement) btnElement.classList.add("active");
    loadWorkLogs(status);
}

async function deleteLog(id) {
    if (!confirm(`업무 기록 #${id}을 삭제하시겠습니까?`)) return;
    try {
        const res = await requestApi("/api/logs/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: id })
        });
        if (res.ok) {
            loadWorkLogs();
            loadAnomalyStatistics();
        }
    } catch (e) {
        alert("삭제 오류: " + e.message);
    }
}

// =============================================================================
// 기능 4: 음성 인식 및 음성 인수인계 (Voice Ops: 마이크 + 파일 업로드)
// =============================================================================

function toggleSpeechRecording() {
    if (location.protocol === "https:") {
        alert("웹 배포에서는 오디오 파일 업로드를 사용하세요.");
        return;
    }
    const mic = document.getElementById("micBtn");
    const statusText = document.getElementById("recordingStatus");

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        alert("현재 브라우저에서 Web Speech API를 지원하지 않습니다. Chrome/Edge 브라우저를 사용하거나 아래의 '오디오 파일 업로드' 기능을 사용하세요.");
        return;
    }

    if (!isRecording) {
        speechRecognitionInstance = new SpeechRecognition();
        speechRecognitionInstance.lang = "ko-KR";
        speechRecognitionInstance.continuous = true;
        speechRecognitionInstance.interimResults = true;

        speechRecognitionInstance.onstart = () => {
            isRecording = true;
            mic.classList.add("recording");
            statusText.textContent = "🎙️ 음성을 듣고 있습니다... 말씀해 주세요.";
            statusText.style.color = "#38bdf8";
        };

        speechRecognitionInstance.onresult = (event) => {
            let finalTranscript = "";
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                }
            }
            if (finalTranscript) {
                const rawBox = document.getElementById("voiceRawTranscript");
                rawBox.value = (rawBox.value ? rawBox.value + " " : "") + finalTranscript;
                triggerVoiceCleaning(rawBox.value);
            }
        };

        speechRecognitionInstance.onerror = (e) => {
            statusText.textContent = `녹음 오류: ${e.error}`;
            stopSpeechRecording();
        };

        speechRecognitionInstance.onend = () => {
            stopSpeechRecording();
        };

        speechRecognitionInstance.start();

    } else {
        stopSpeechRecording();
    }
}

function stopSpeechRecording() {
    if (speechRecognitionInstance) {
        speechRecognitionInstance.stop();
        speechRecognitionInstance = null;
    }
    isRecording = false;
    const mic = document.getElementById("micBtn");
    const statusText = document.getElementById("recordingStatus");
    mic.classList.remove("recording");
    statusText.textContent = "녹음이 중지되었습니다. 정제된 내용을 검토해 주세요.";
    statusText.style.color = "var(--text-muted)";
}

async function triggerVoiceCleaning(rawTranscript) {
    if (!rawTranscript.trim()) return;
    try {
        const res = await requestApi("/api/voice/process", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ transcript: rawTranscript })
        });
        const data = await res.json();
        document.getElementById("voiceCleanedTranscript").value = data.cleaned_text || rawTranscript;

        const termsBox = document.getElementById("detectedTermsBox");
        const terms = data.technical_terms || [];
        termsBox.innerHTML = terms.map(t => `<span class="term-tag"><i class="fa-solid fa-tag"></i> ${escapeHtml(t)}</span>`).join("");
    } catch (e) {
        console.warn("Voice cleaning error:", e);
    }
}

async function handleAudioFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const statusEl = document.getElementById("audioUploadStatus");
    statusEl.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> 오디오 파일 (${escapeHtml(file.name)}) Gemini Multimodal 처리 중...`;

    const reader = new FileReader();
    reader.onload = async () => {
        try {
            const base64Data = reader.result.split(",")[1];
            const mimeType = file.type || "audio/wav";

            const res = await requestApi("/api/voice/upload", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ audio_base64: base64Data, mime_type: mimeType })
            });
            const data = await res.json();

            document.getElementById("voiceRawTranscript").value = data.raw_transcript || `[파일 업로드: ${file.name}]`;
            document.getElementById("voiceCleanedTranscript").value = data.cleaned_text || "";

            const termsBox = document.getElementById("detectedTermsBox");
            const terms = data.technical_terms || [];
            termsBox.innerHTML = terms.map(t => `<span class="term-tag"><i class="fa-solid fa-tag"></i> ${escapeHtml(t)}</span>`).join("");

            statusEl.innerHTML = `<span style="color: #10b981;">✅ '${escapeHtml(file.name)}' 음성 처리 완료!</span>`;
        } catch (e) {
            statusEl.innerHTML = `<span style="color: #f87171;">음성 처리 실패: ${e.message}</span>`;
        }
    };
    reader.readAsDataURL(file);
}

function transferVoiceToLog() {
    const cleaned = document.getElementById("voiceCleanedTranscript").value.trim();
    const raw = document.getElementById("voiceRawTranscript").value.trim();
    const textToTransfer = cleaned || raw;

    if (!textToTransfer) {
        alert("전송할 음성 텍스트가 없습니다. 마이크 녹음을 하거나 오디오 파일을 업로드하세요.");
        return;
    }

    document.getElementById("rawLogInput").value = textToTransfer;
    switchTab("tab-classify", document.querySelector('[aria-controls="tab-classify"]'));
    analyzeAndClassifyLog();
}

// =============================================================================
// 기능 2: 8개 섹션 인수인계 종합 보고서 생성 및 승인
// =============================================================================

async function generateComprehensiveReport() {
    const title = document.getElementById("reportShiftTitle").value.trim();
    const outgoing = document.getElementById("reportOutgoingShift").value.trim();
    const incoming = document.getElementById("reportIncomingShift").value.trim();
    const author = document.getElementById("reportAuthor").value.trim();
    const start = new Date(document.getElementById("reportStart").value);
    const end = new Date(document.getElementById("reportEnd").value);
    if (!(start < end)) {
        alert("올바른 교대 시작과 종료 시각을 입력하세요.");
        return;
    }

    const view = document.getElementById("reportRenderedView");
    const editor = document.getElementById("reportMarkdownEditor");
    const badge = document.getElementById("reportStatusBadge");

    view.innerHTML = `<div style="text-align: center; padding: 50px;"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><p style="margin-top: 15px;">전체 업무 기록을 집계하여 8개 섹션 보고서를 생성하고 있습니다...</p></div>`;

    try {
        const res = await requestApi("/api/reports/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                shift_title: title,
                outgoing_shift: outgoing,
                incoming_shift: incoming,
                author: author,
                shift_start: start.toISOString(),
                shift_end: end.toISOString()
            })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        currentReportId = data.report_id;
        currentReportMarkdown = data.raw_markdown;

        editor.value = currentReportMarkdown;
        renderMarkdownView(currentReportMarkdown);

        badge.textContent = `검토 대기 (보고서 #${currentReportId})`;
        badge.className = "badge-status pending";

        loadHandoverReports();
    } catch (e) {
        view.innerHTML = `<div style="color: #f87171; padding: 20px;">생성 실패: ${e.message}</div>`;
    }
}

function toggleReportEditMode() {
    const view = document.getElementById("reportRenderedView");
    const editor = document.getElementById("reportMarkdownEditor");
    isReportEditMode = !isReportEditMode;

    if (isReportEditMode) {
        editor.style.display = "block";
        view.style.display = "none";
    } else {
        currentReportMarkdown = editor.value;
        renderMarkdownView(currentReportMarkdown);
        editor.style.display = "none";
        view.style.display = "block";
    }
}

function renderMarkdownView(md) {
    renderMarkdownInto(md, document.getElementById("reportRenderedView"));
}

async function approveCurrentReport() {
    if (!currentReportId) {
        alert("승인할 보고서가 선택되지 않았습니다. 먼저 보고서를 생성하거나 목록에서 선택하세요.");
        return;
    }
    const approver = document.getElementById("approverNameInput").value.trim() || "DCO 책임자";
    const editedMd = document.getElementById("reportMarkdownEditor").value;

    if (!confirm(`인수인계 보고서 #${currentReportId}의 내용을 공식 검토 완료하였으며, 최종 서명 승인하시겠습니까?`)) return;

    try {
        const res = await requestApi("/api/reports/approve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                id: currentReportId,
                approver_name: approver,
                edited_markdown: editedMd
            })
        });
        const result = await res.json();
        if (!res.ok) throw new Error(result.error || "승인에 실패했습니다.");
        if (result.success) {
            alert(`✅ ${result.message}`);
            const badge = document.getElementById("reportStatusBadge");
            badge.textContent = `최종 승인 완료 (${result.approved_by})`;
            badge.className = "badge-status complete";
            loadHandoverReports();
        }
    } catch (e) {
        alert("승인 실패: " + e.message);
    }
}

async function loadHandoverReports() {
    const container = document.getElementById("reportArchiveTbody");
    try {
        const res = await requestApi("/api/reports");
        const data = await res.json();
        const reports = data.reports || [];

        if (reports.length === 0) {
            container.innerHTML = `<div style="font-size: 0.8rem; color: var(--text-muted); padding: 10px;">저장된 인수인계 보고서가 없습니다.</div>`;
            return;
        }

        container.innerHTML = reports.map(r => `
            <div style="background: #090d14; border: 1px solid var(--border); padding: 10px; border-radius: 4px; margin-bottom: 8px; cursor: pointer;" onclick="loadReportDetail(${r.id})">
                <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 4px;">
                    <strong>#${r.id} ${escapeHtml(r.shift_title)}</strong>
                    <span class="badge-status ${r.status === '최종승인' ? 'complete' : 'pending'}">${escapeHtml(r.status)}</span>
                </div>
                <div style="font-size: 0.72rem; color: var(--text-muted);">
                    작성: ${escapeHtml(r.author || '-')} | 교대: ${escapeHtml(r.outgoing_shift)} ➔ ${escapeHtml(r.incoming_shift)}
                </div>
            </div>
        `).join("");
        if (demoMode && currentReportId === null) await loadReportDetail(reports[0].id, reports[0]);
    } catch (e) {
        container.innerHTML = `<div style="color: #f87171;">목록 로드 실패</div>`;
    }
}

async function loadReportDetail(id, selectedReport = null) {
    try {
        if (!selectedReport) {
            const res = await requestApi("/api/reports");
            const data = await res.json();
            selectedReport = (data.reports || []).find(report => report.id === id);
        }
        const rep = selectedReport;
        if (!rep) return;

        currentReportId = rep.id;
        currentReportMarkdown = rep.raw_markdown;
        document.getElementById("reportMarkdownEditor").value = currentReportMarkdown;
        renderMarkdownView(currentReportMarkdown);

        const badge = document.getElementById("reportStatusBadge");
        badge.textContent = `${rep.status} (보고서 #${rep.id})`;
        badge.className = `badge-status ${rep.status === '최종승인' ? 'complete' : 'pending'}`;
    } catch (e) {}
}

// =============================================================================
// 기능 5: RAG 지식 검색 질의응답
// =============================================================================

function askRagSample(question) {
    document.getElementById("ragQuestionInput").value = question;
    executeRagQuery();
}

async function executeRagQuery() {
    const input = document.getElementById("ragQuestionInput");
    const q = input.value.trim();
    if (!q) return;

    const answerBox = document.getElementById("ragAnswerBox");
    const answerText = document.getElementById("ragAnswerText");
    const sourcesList = document.getElementById("ragSourcesList");

    answerBox.style.display = "block";
    answerText.innerHTML = `<div style="color: var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> 과거 모든 승인 업무 기록과 SOP 문서를 FTS 인덱스로 검색하여 답변을 생성 중입니다...</div>`;
    sourcesList.innerHTML = "";

    try {
        const res = await requestApi("/api/rag/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: q })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        renderMarkdownInto(data.answer || "관련 답변을 생성할 수 없습니다.", answerText);

        // 출처 카드 렌더링
        const sources = data.sources || [];
        if (sources.length === 0) {
            sourcesList.innerHTML = `<div style="font-size: 0.78rem; color: var(--text-muted);">직접 연관된 출처 문서가 없습니다.</div>`;
        } else {
            sourcesList.innerHTML = sources.map(s => {
                if (s.source_type === "WORK_LOG") {
                    return `
                    <div class="source-card">
                        <div class="source-badge"><i class="fa-solid fa-ticket"></i> 티켓 #${escapeHtml(s.ticket_no || '미발급')}</div>
                        <div>장비: <strong>${escapeHtml(s.device_id || '-')}</strong></div>
                        <div style="color: var(--text-muted); margin-top: 2px;">조치: ${escapeHtml(s.action_taken || '-')}</div>
                    </div>`;
                } else {
                    return `
                    <div class="source-card">
                        <div class="source-badge" style="color: #10b981;"><i class="fa-solid fa-book"></i> SOP: ${escapeHtml(s.filename)}</div>
                        <div style="color: var(--text-muted);">${escapeHtml(s.summary || '-')}</div>
                    </div>`;
                }
            }).join("");
        }
    } catch (e) {
        answerText.innerHTML = `<span style="color: #f87171;">검색 오류: ${e.message}</span>`;
    }
}

// =============================================================================
// 기능 5: 기술 문서 (SOP / 매뉴얼) 업로드, 분석 및 문서 Q&A
// =============================================================================

function handleDocFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    document.getElementById("docFilenameInput").value = file.name;
    const reader = new FileReader();
    reader.onload = () => {
        document.getElementById("docContentInput").value = reader.result;
    };
    reader.readAsText(file);
}

async function uploadAndAnalyzeDocument() {
    const filename = document.getElementById("docFilenameInput").value.trim() || "DCO_SOP_문서.txt";
    const content = document.getElementById("docContentInput").value.trim();

    if (!content) {
        alert("문서 본문 내용을 입력해 주세요.");
        return;
    }

    try {
        const res = await requestApi("/api/docs/upload", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename: filename, content: content })
        });
        const data = await res.json();
        if (data.success) {
            alert(`✅ 문서 '${filename}'이 지식 베이스에 성공적으로 색인 등록되었습니다.`);
            document.getElementById("docFilenameInput").value = "";
            document.getElementById("docContentInput").value = "";
            loadTechnicalDocs();
        }
    } catch (e) {
        alert("업로드 실패: " + e.message);
    }
}

async function loadTechnicalDocs() {
    const container = document.getElementById("technicalDocsList");
    const selectForQa = document.getElementById("docSelectForQa");

    try {
        const res = await requestApi("/api/docs");
        const data = await res.json();
        const docs = data.docs || [];

        if (docs.length === 0) {
            container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 30px;">등록된 SOP 문서가 없습니다.</div>`;
            if (selectForQa) selectForQa.innerHTML = `<option value="">문서 없음</option>`;
            return;
        }

        if (selectForQa) {
            selectForQa.innerHTML = docs.map(d => `<option value="${d.id}">${escapeHtml(d.filename)} (${escapeHtml(d.category || 'SOP')})</option>`).join("");
        }

        container.innerHTML = docs.map(d => `
            <div style="background: #090d14; border: 1px solid var(--border); border-left: 3px solid #10b981; padding: 14px; border-radius: 4px; margin-bottom: 12px;">
                <div class="doc-card-heading">
                    <strong><i class="fa-solid fa-file-pdf" style="color: #f87171;"></i> ${escapeHtml(d.filename)}</strong>
                    <span class="badge-status complete">${escapeHtml(d.category || 'SOP')}</span>
                </div>
                <div style="font-size: 0.85rem; color: #cbd5e1; margin-bottom: 8px;">${escapeHtml(d.summary || '')}</div>
                <div style="font-size: 0.78rem; color: #94a3b8; white-space: pre-wrap; background: #0f172a; padding: 8px; border-radius: 4px;">${escapeHtml(d.key_points || '')}</div>
            </div>
        `).join("");
    } catch (e) {}
}

async function executeDocQa() {
    const select = document.getElementById("docSelectForQa");
    const docId = select ? select.value : null;
    const input = document.getElementById("docQaQuestionInput");
    const q = input ? input.value.trim() : "";
    const resBox = document.getElementById("docQaResultBox");

    if (!docId || !q) {
        alert("질문할 문서를 선택하고 질문 내용을 입력하세요.");
        return;
    }

    resBox.style.display = "block";
    resBox.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> 문서 본문을 검토하여 출처와 함께 답변을 생성 중입니다...`;

    try {
        const res = await requestApi("/api/docs/qa", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ doc_id: parseInt(docId), question: q })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        renderMarkdownInto(data.answer, resBox);
    } catch (e) {
        resBox.innerHTML = `<span style="color: #f87171;">오류: ${e.message}</span>`;
    }
}

// =============================================================================
// 기능 6: 패턴 탐지 및 통계 계산 & AI 공학 해석
// =============================================================================

async function loadAnomalyStatistics() {
    try {
        const res = await requestApi("/api/anomalies/stats");
        const stats = await res.json();

        document.getElementById("stat-total-logs").textContent = stats.total_logs || 0;
        document.getElementById("stat-pending-logs").textContent = (stats.status_counts && stats.status_counts['미완료']) || 0;

        const topDev = (stats.repeated_devices && stats.repeated_devices[0]) ? `${stats.repeated_devices[0].device_id} (${stats.repeated_devices[0].count}회)` : "-";
        document.getElementById("stat-top-device").textContent = topDev;

        const topType = (stats.incident_types && stats.incident_types[0]) ? `${stats.incident_types[0].incident_type} (${stats.incident_types[0].count}건)` : "-";
        document.getElementById("stat-top-type").textContent = topType;

        // 1. 동일 장비 반복 장애
        const devTbody = document.getElementById("repeatDevicesTbody");
        devTbody.innerHTML = (stats.repeated_devices || []).map(d => `
            <tr>
                <td><code>${escapeHtml(d.device_id)}</code></td>
                <td><strong style="color: #f87171;">${d.count} 회 반복 장애</strong></td>
            </tr>
        `).join("") || `<tr><td colspan="2">데이터 없음</td></tr>`;

        // 2. 동일 부품 반복 교체
        const partsTbody = document.getElementById("repeatPartsTbody");
        if (partsTbody) {
            partsTbody.innerHTML = (stats.repeated_parts || []).map(p => `
                <tr>
                    <td><strong>${escapeHtml(p.part_name)}</strong></td>
                    <td><span style="color: #38bdf8; font-weight: 600;">${p.count} 회 교체/소요</span></td>
                </tr>
            `).join("") || `<tr><td colspan="2">데이터 없음</td></tr>`;
        }

        // 3. 동일 오류 코드 / 알람 반복
        const errTbody = document.getElementById("repeatErrorsTbody");
        if (errTbody) {
            errTbody.innerHTML = (stats.repeated_errors || []).map(e => `
                <tr>
                    <td><code>${escapeHtml(e.error_code)}</code></td>
                    <td><strong style="color: #fbbf24;">${e.count} 건 발생</strong></td>
                </tr>
            `).join("") || `<tr><td colspan="2">데이터 없음</td></tr>`;
        }

        // 4. 반복적인 작업 실수 / 누락 패턴
        const omTbody = document.getElementById("frequentOmissionsTbody");
        if (omTbody) {
            omTbody.innerHTML = (stats.frequent_omissions || []).map(o => `
                <tr>
                    <td>${escapeHtml(o.issue)}</td>
                    <td><strong style="color: #f87171;">${o.count} 건 감지</strong></td>
                </tr>
            `).join("") || `<tr><td colspan="2">데이터 없음</td></tr>`;
        }

    } catch (e) {}
}

async function requestAnomalyExplanation() {
    const box = document.getElementById("aiAnomalyExplanation");
    box.innerHTML = `<div style="text-align: center; padding: 25px;"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><p style="margin-top: 10px;">통계 데이터를 바탕으로 Gemini 수석 아키텍트가 공학적 원인 진단을 수행 중입니다...</p></div>`;

    try {
        const res = await requestApi("/api/anomalies/explain", { method: "POST" });
        const data = await res.json();
        renderMarkdownInto(data.explanation || "분석 결과를 생성하지 못했습니다.", box);
    } catch (e) {
        box.innerHTML = `<div style="color: #f87171;">해석 실패: ${e.message}</div>`;
    }
}

// =============================================================================
// 기능 7: 미완료 업무 우선순위 자동 추천 (Priority Scoring)
// =============================================================================

async function loadPriorityTasks() {
    const tbody = document.getElementById("priorityTasksTbody");
    try {
        const res = await requestApi("/api/logs?status=미완료");
        const data = await res.json();
        const tasks = data.logs || [];

        if (tasks.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 30px; color: var(--text-muted);">현재 미완료 체류 중인 긴급 업무가 없습니다.</td></tr>`;
            return;
        }

        tbody.innerHTML = tasks.map(t => `
            <tr>
                <td><span class="tier-badge tier-${escapeHtml(t.priority_tier || 'P3')}">${escapeHtml(t.priority_tier || 'P3')}</span></td>
                <td><strong style="color: #fbbf24; font-family: var(--font-mono);">${escapeHtml(String(t.priority_score ?? 50))}점</strong></td>
                <td>
                    <div><strong>${escapeHtml(t.ticket_no || '-')}</strong></div>
                    <code style="color: #38bdf8;">${escapeHtml(t.device_id || '-')}</code>
                </td>
                <td>
                    <div style="font-weight: 600;">${escapeHtml(t.incident_type)}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(t.cause)}</div>
                </td>
                <td><div style="color: #fca5a5;">${escapeHtml(t.follow_up || '-')}</div></td>
                <td style="font-size: 0.78rem; color: #cbd5e1;">장애 심각도, 부품 확보 여부, 리던던시 영향도 종합 평가</td>
                <td>
                    <button class="btn-success" style="padding: 4px 10px; font-size: 0.75rem;" onclick="markTaskDone(${t.id})">
                        조치확정
                    </button>
                </td>
            </tr>
        `).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7">로드 실패</td></tr>`;
    }
}

async function markTaskDone(id) {
    if (!confirm(`업무 #${id}의 조치를 완료 상태로 확정 변경하시겠습니까?`)) return;
    try {
        await requestApi("/api/logs/update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: id, status: "완료", result: "현장 점검 및 조치 완료 확인" })
        });
        loadPriorityTasks();
        loadWorkLogs();
    } catch (e) {}
}

// =============================================================================
// 기능 8: 다국어 인수인계 지원 (용어집 보존 스플릿 뷰)
// =============================================================================

async function executeTranslation() {
    const text = document.getElementById("translateSourceText").value.trim();
    const lang = document.getElementById("targetLangSelect").value;
    const resBox = document.getElementById("translateResultBox");

    if (!text) {
        alert("번역할 원문 텍스트를 입력해 주세요.");
        return;
    }

    resBox.innerHTML = `<div style="text-align: center; padding: 40px;"><i class="fa-solid fa-spinner fa-spin"></i> 전문 용어(iDRAC, PDU, 랙, 티켓)를 보호하며 정밀 번역 중입니다...</div>`;

    try {
        const res = await requestApi("/api/translate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: text, target_lang: lang })
        });
        const data = await res.json();
        resBox.textContent = data.translated_text || "번역 결과를 가져올 수 없습니다.";
    } catch (e) {
        resBox.innerHTML = `<span style="color: #f87171;">번역 실패: ${e.message}</span>`;
    }
}

// =============================================================================
// 기능 9: Function Calling 자연어 Ops 에이전트
// =============================================================================

function sendAgentCmd(cmd) {
    document.getElementById("agentInput").value = cmd;
    sendAgentMessage();
}

async function sendAgentMessage() {
    const input = document.getElementById("agentInput");
    const cmd = input.value.trim();
    if (!cmd) return;

    const chatContainer = document.getElementById("agentChatContainer");

    // 사용자 말풍선
    const userBubble = document.createElement("div");
    userBubble.className = "chat-bubble user";
    userBubble.textContent = cmd;
    chatContainer.appendChild(userBubble);
    input.value = "";
    chatContainer.scrollTop = chatContainer.scrollHeight;

    // AI 대기 말풍선
    const aiBubble = document.createElement("div");
    aiBubble.className = "chat-bubble ai";
    aiBubble.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> 도구 계획 수립 및 시스템 실행 중...`;
    chatContainer.appendChild(aiBubble);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    try {
        const res = await requestApi("/api/agent/command", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command: cmd })
        });
        const data = await res.json();
        const plan = data.plan || {};
        const result = data.execution_result;

        let contentHtml = `<div style="font-weight: 600; color: var(--accent); margin-bottom: 4px;">⚡ 도구 실행: ${escapeHtml(plan.function_name || 'direct_answer')}</div>`;
        contentHtml += `<div>${escapeHtml(plan.assistant_message || '')}</div>`;

        if (Array.isArray(result)) {
            contentHtml += `<div style="margin-top: 8px; display: flex; flex-direction: column; gap: 6px;">`;
            result.slice(0, 5).forEach(item => {
                contentHtml += `
                <div style="background: #090d14; border: 1px solid #243247; padding: 8px 12px; border-radius: 4px; font-size: 0.8rem;">
                    <strong>[#${escapeHtml(item.id || item.ticket_no || '')}] ${escapeHtml(item.device_id || item.filename || '')}</strong>: ${escapeHtml(item.action_taken || item.summary || item.cause || '')} 
                    <span class="badge-status ${item.status === '완료' ? 'complete' : 'pending'}">${escapeHtml(item.status || '')}</span>
                </div>`;
            });
            contentHtml += `</div>`;
        } else if (typeof result === "string") {
            contentHtml += `<div style="margin-top: 8px; padding: 10px; background: #090d14; border-radius: 4px; font-size: 0.82rem; white-space: pre-wrap;">${escapeHtml(result)}</div>`;
        } else if (result && typeof result === "object") {
            contentHtml += `<div style="margin-top: 8px; padding: 10px; background: #090d14; border-radius: 4px; font-size: 0.8rem;"><pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre></div>`;
        }

        aiBubble.innerHTML = contentHtml;
    } catch (e) {
        aiBubble.innerHTML = `<span style="color: #f87171;">오류: ${e.message}</span>`;
    } finally {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
}

// =============================================================================
// 기능 10: 누적 기록 기반 업무 효율화 제안
// =============================================================================

async function loadEfficiencyImprovements() {
    const container = document.getElementById("improvementsContainer");
    try {
        const res = await requestApi("/api/improvements", { method: "POST" });
        const data = await res.json();
        renderMarkdownInto(data.improvements || "개선안을 불러오지 못했습니다.", container);
    } catch (e) {
        container.innerHTML = `<div style="color: #f87171;">개선안 로드 오류: ${e.message}</div>`;
    }
}

// =============================================================================
// API 키 설정 모달 핸들러 및 연결 테스트
// =============================================================================

function openApiKeyModal() {
    document.getElementById("apiKeyModal").style.display = "flex";
}

function closeApiKeyModal() {
    document.getElementById("apiKeyModal").style.display = "none";
}

async function checkApiKeyStatus() {
    try {
        const res = await requestApi("/api/settings/status");
        const data = await res.json();
        const statusSpan = document.getElementById("apiKeyStatusText");
        if (data.signed_in_as) {
            document.getElementById("activeOperatorName").textContent = data.signed_in_as;
            for (const id of ["reportAuthor", "approverNameInput"]) {
                const field = document.getElementById(id);
                field.value = data.signed_in_as;
                field.readOnly = true;
            }
        }
        statusSpan.textContent = data.engine_ready
            ? (data.api_key_configured ? "BridgeCLI 설정됨" : "Gemini 키 필요")
            : "BridgeCLI 연결 확인";
    } catch (e) {}
}

async function testApiKeyConnection() {
    const btn = document.getElementById("btnTestApiKey");
    const resultBox = document.getElementById("apiKeyTestResult");

    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> 연결 테스트 중...`;
    resultBox.style.display = "none";

    try {
        const res = await requestApi("/api/settings/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}"
        });
        const data = await res.json();

        resultBox.style.display = "block";
        if (data.success) {
            resultBox.className = "test-result-box success";
            resultBox.innerHTML = `<strong><i class="fa-solid fa-circle-check"></i> ${escapeHtml(data.message)}</strong><br><span style="font-size: 0.75rem;">응답 샘플: "${escapeHtml(data.reply_sample || '')}"</span>`;
        } else {
            resultBox.className = "test-result-box fail";
            resultBox.innerHTML = `<strong><i class="fa-solid fa-circle-xmark"></i> 연결 실패:</strong> ${escapeHtml(data.error || '응답 없음')}`;
        }
    } catch (e) {
        resultBox.style.display = "block";
        resultBox.className = "test-result-box fail";
        resultBox.innerHTML = `<strong><i class="fa-solid fa-circle-xmark"></i> 통신 오류:</strong> ${e.message}`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-network-wired"></i> 연결 테스트`;
    }
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function renderMarkdownInto(md, element) {
    let html = escapeHtml(md)
        .replace(/^# (.*$)/gim, '<h1>$1</h1>')
        .replace(/^## (.*$)/gim, '<h2>$1</h2>')
        .replace(/^### (.*$)/gim, '<h3>$1</h3>')
        .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
        .replace(/^\- (.*$)/gim, '<li>$1</li>')
        .replace(/\n\n/gim, '<br>');
    element.innerHTML = html;
}
