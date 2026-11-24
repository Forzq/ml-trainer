"use strict";

function showBetaLogin() {
  if ($("#beta-login")) return;
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
      <h1>Mockroom</h1>
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

function syncBetaControls(config) {
  document.body.classList.remove("beta-signed-out");
  settingsPage.querySelector('[data-action="logout"]').hidden = !config.beta;
  settingsPage.querySelector('[data-action="shutdown"]').hidden = config.beta;
}
