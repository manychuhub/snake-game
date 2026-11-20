const form = document.getElementById("credentials");
const title = document.getElementById("title");
const submit = document.getElementById("submit");
const toggle = document.getElementById("toggle");
const message = document.getElementById("message");
const authChanges = new BroadcastChannel("shift-bridge-auth");
let signup = false;
const accountChange = new URLSearchParams(location.search).get("account");
if (accountChange === "password") message.textContent = "비밀번호를 변경했습니다. 새 비밀번호로 로그인하세요.";
if (accountChange === "deleted") message.textContent = "계정 탈퇴가 완료되었습니다.";

function setMode(enabled) {
    signup = enabled;
    title.textContent = submit.textContent = signup ? "회원가입" : "로그인";
    form.action = signup ? "/api/account/signup" : "/api/account/login";
    form.elements.password.autocomplete = signup ? "new-password" : "current-password";
    form.elements.password.minLength = signup ? 12 : 0;
    toggle.textContent = signup ? "로그인 화면으로" : "회원가입";
}

toggle.addEventListener("click", () => {
    message.textContent = "";
    setMode(!signup);
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = toggle.disabled = true;
    try {
        const response = await fetch(form.action, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(Object.fromEntries(new FormData(form)))
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        if (!signup) {
            authChanges.postMessage("changed");
            location.replace("/workspace");
            return;
        }
        setMode(false);
        form.elements.password.value = "";
        form.elements.password.focus();
        message.textContent = "회원가입이 완료되었습니다. 로그인하세요.";
    } catch (error) {
        message.textContent = error.message;
    } finally {
        submit.disabled = toggle.disabled = false;
    }
});
