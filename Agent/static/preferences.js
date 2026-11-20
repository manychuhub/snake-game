(() => {
    const panel = document.getElementById("preferences");
    const main = panel.closest("main");
    panel.innerHTML = `
        <div class="controls preferences-header">
            <h2 id="preferences-title">기본 장소</h2>
            <span data-account></span>
            <button class="secondary" data-logout type="button">로그아웃</button>
        </div>
        <form autocomplete="off">
            <fieldset class="preferences-fields" disabled>
                <label>기본 위치<input name="default_location" type="text" maxlength="120"></label>
                <label>장소 종류<input name="place_type" type="text" maxlength="80"></label>
                <button type="submit">저장</button>
            </fieldset>
        </form>
        <div class="controls">
            <p role="status"></p>
            <button class="secondary" data-retry type="button" hidden>다시 불러오기</button>
        </div>`;
    const form = panel.querySelector("form");
    const fields = panel.querySelector("fieldset");
    const account = panel.querySelector("[data-account]");
    const logout = panel.querySelector("[data-logout]");
    const retry = panel.querySelector("[data-retry]");
    const status = panel.querySelector("[role=status]");
    const authChanges = new BroadcastChannel("shift-bridge-auth");
    const jsonPost = {method: "POST", headers: {"Content-Type": "application/json"}};
    let accountId = null;
    let revision = 0;

    function clear() {
        ++revision;
        accountId = null;
        fields.disabled = true;
        form.reset();
        account.textContent = status.textContent = "";
        retry.hidden = true;
    }

    function show(data) {
        accountId = data.account_id;
        account.textContent = data.username;
        form.elements.default_location.value = data.default_location;
        form.elements.place_type.value = data.place_type;
        fields.disabled = false;
    }

    function leave(path) {
        clear();
        main.hidden = true;
        location.replace(path);
    }

    async function load(loadedMessage = "") {
        clear();
        if (document.hidden || logout.disabled || main.hidden) return;
        const current = revision;
        status.textContent = "불러오는 중…";
        try {
            const response = await fetch("/api/account/preferences", {cache: "no-store"});
            if (current !== revision) return;
            if (response.status === 401) return leave("/login");
            if (!response.ok) throw new Error();
            const data = await response.json();
            if (current !== revision) return;
            if (panel.hasAttribute("data-admin-dashboard") && !data.admin) return leave("/account/preferences");
            show(data);
            status.textContent = loadedMessage;
        } catch {
            if (current !== revision) return;
            status.textContent = "설정을 불러오지 못했습니다.";
            retry.hidden = false;
        }
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (accountId === null || fields.disabled) return;
        const current = ++revision;
        const values = {account_id: accountId, ...Object.fromEntries(new FormData(form))};
        fields.disabled = true;
        status.textContent = "저장 중…";
        try {
            const response = await fetch("/api/account/preferences", {...jsonPost, body: JSON.stringify(values)});
            if (current !== revision) return;
            if (response.status === 401) return leave("/login");
            if (response.status === 409) {
                return load("계정이 바뀌었습니다. 변경 사항을 다시 입력하세요.");
            }
            const data = await response.json();
            if (current !== revision) return;
            if (!response.ok) {
                status.textContent = data.error || "설정을 저장하지 못했습니다.";
                return;
            }
            show(data);
            status.textContent = "설정을 저장했습니다.";
        } catch {
            if (current === revision) status.textContent = "설정을 저장하지 못했습니다.";
        } finally {
            if (current === revision) fields.disabled = false;
        }
    });

    logout.addEventListener("click", async () => {
        logout.disabled = true;
        clear();
        try {
            const response = await fetch("/api/account/logout", {...jsonPost, body: "{}"});
            if (!response.ok && response.status !== 401) throw new Error();
            authChanges.postMessage("changed");
            leave("/login");
        } catch {
            if (!document.hidden && !main.hidden) {
                status.textContent = "로그아웃을 완료하지 못했습니다.";
                retry.hidden = false;
            }
        } finally {
            logout.disabled = false;
        }
    });

    retry.addEventListener("click", () => load());
    authChanges.addEventListener("message", () => leave("/workspace"));
    window.addEventListener("pagehide", clear);
    window.addEventListener("pageshow", (event) => { if (event.persisted) load(); });
    document.addEventListener("visibilitychange", () => { if (document.hidden) clear(); else load(); });
    load();
})();
