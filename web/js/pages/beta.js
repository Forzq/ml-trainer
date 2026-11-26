"use strict";

function showBetaLogin() {
  if ($("#beta-login")) return;
  $("#beta-quota").hidden = true;
  if (state.config?.beta) {
    live.stop();
    discardRecording();
    cancelSpeech();
    storage.remove("ml-session");
    state.config = null;
    state.session = null;
  }
  $("#start-dialog").close();
  document.body.classList.add("beta-signed-out");
  setPage(`
    <section class="beta-sign-in">
      <div class="beta-brand"><img src="/static/mockroom-logo-purple.png" alt="" width="48" height="48"><h1>Mockroom</h1></div>
      <p>Введи код приглашения, чтобы открыть закрытую бету.</p>
      <form id="beta-login">
        <label class="field-label" for="invite-code">Код приглашения</label>
        <input id="invite-code" type="password" required maxlength="128" autocomplete="off"
               autocapitalize="none" spellcheck="false">
        <button class="button primary full" type="submit">Войти</button>
        <p id="beta-login-error" role="alert" hidden></p>
      </form>
    </section>`, "Вход");
  $("#invite-code").focus();
  $("#beta-login").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector("button");
    const errorMessage = $("#beta-login-error");
    button.disabled = true;
    errorMessage.hidden = true;
    try {
      await api("/beta/redeem", { method: "POST", body: { code: $("#invite-code").value.trim() } });
      history.replaceState(null, "", "/");
      location.reload();
    } catch (error) {
      errorMessage.textContent = error.message;
      errorMessage.hidden = false;
      button.disabled = false;
    }
  });
}

function showBetaName() {
  document.body.classList.add("beta-signed-out");
  setPage(`
    <section class="beta-sign-in">
      <div class="beta-brand"><img src="/static/mockroom-logo-purple.png" alt="" width="48" height="48"><h1>Как тебя зовут?</h1></div>
      <p>Имя будет видно администратору беты.</p>
      <form id="beta-profile">
        <label class="field-label" for="display-name">Имя</label>
        <input id="display-name" name="name" required maxlength="80" autocomplete="name">
        <button class="button primary full" type="submit">Продолжить</button>
        <p id="beta-profile-error" role="alert" hidden></p>
      </form>
      <button class="text-button beta-back" type="button" data-action="logout">Выйти</button>
    </section>`, "Профиль");
  $("#display-name").focus();
  $("#beta-profile").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector("button");
    const errorMessage = $("#beta-profile-error");
    const name = $("#display-name").value.trim();
    if (!name) {
      errorMessage.textContent = "Введи имя.";
      errorMessage.hidden = false;
      return;
    }
    button.disabled = true;
    errorMessage.hidden = true;
    try {
      await api("/beta/profile", { method: "PUT", body: { name } });
      await boot();
    } catch (error) {
      if (error.status === 401) { showBetaLogin(); return; }
      errorMessage.textContent = error.message;
      errorMessage.hidden = false;
      button.disabled = false;
    }
  });
}

function syncBetaControls(config) {
  document.body.classList.remove("beta-signed-out");
  settingsPage.querySelector('[data-action="logout"]').hidden = !config.beta;
  settingsPage.querySelector('[data-action="shutdown"]').hidden = config.beta;
  if (config.beta) void refreshBetaQuota();
}

let quotaSequence = 0;

async function refreshBetaQuota() {
  if (!state.config?.beta) return;
  const config = state.config;
  const sequence = ++quotaSequence;
  try {
    const { remaining, limit, reset_at: resetAt } = await api("/beta/quota");
    if (sequence !== quotaSequence || state.config !== config) return;
    const quota = $("#beta-quota");
    const bar = $("#beta-quota-bar");
    bar.max = Math.max(1, limit);
    bar.value = remaining;
    const text = `Запросы на сегодня · ${remaining.toLocaleString("ru-RU")} / ${limit.toLocaleString("ru-RU")}`;
    $("#beta-quota-text").textContent = text;
    bar.setAttribute("aria-valuetext", `Осталось ${remaining} из ${limit}`);
    quota.title = "Обновление квоты " + new Date(resetAt * 1000).toLocaleString("ru-RU");
    quota.hidden = false;
  } catch { /* Keep the last known quota during a temporary connection failure. */ }
}

window.addEventListener("focus", refreshBetaQuota);
setInterval(() => { if (!document.hidden) void refreshBetaQuota(); }, 30000);
