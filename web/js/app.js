"use strict";

const trainerAvatar = new TrainerAvatar({
  api, storage, toast,
  panel: settingsPage.querySelector("#avatar-settings"),
  voice: trainerVoice,
});
const live = new LiveTraining({
  session: () => state.session,
  busy: () => state.busy,
  update: () => updateLiveUI(),
  cancelSpeech: () => cancelSpeech(),
  checkReady: () => {
    if (!speechRecognitionReady()) throw new Error("Для Live Training подключи Deepgram или Whisper в .env.");
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error("Запись недоступна. Обнови WebView2 Runtime.");
    if (state.volume === 0) throw new Error("Для Live Training увеличь громкость голоса выше 0%.");
    if (state.config.tts?.provider === "fish" ? !state.config.tts.ready : !("speechSynthesis" in window)) {
      throw new Error("Проверь подключение озвучки в разделе «Настройки».");
    }
  },
  say: async (text) => {
    const version = speech.version;
    const request = speak(text, { force: true });
    if (version === speech.version) return false;
    const completion = speech.completion;
    await request;
    return completion ? await completion : false;
  },
  transcribe: async (blob) => {
    const form = new FormData();
    form.append("audio", blob, "answer.webm");
    form.append("session_id", state.session.id);
    form.append("question_id", String(state.session.question.id));
    state.busy = true;
    updateLiveUI();
    try { return await api("/transcribe", { method: "POST", body: form }); }
    finally { state.busy = false; updateLiveUI(); }
  },
  acceptTranscript: (result, session) => {
    if (state.session?.id !== session.id || state.session.question?.id !== session.question.id || state.session.reviewing !== session.reviewing) return result.text;
    const key = draftKey();
    const field = $("#answer-input");
    const text = [(field?.value || storage.get(key) || "").trim(), result.text].filter(Boolean).join(" ").slice(0, 12000);
    storage.set(key, text);
    if (field) { field.value = text; showTranscriptOriginal(result, field); }
    return text;
  },
  submit: async (text, skip) => {
    if ($("#answer-input") && !skip) $("#answer-input").value = text;
    return await submitAnswer(null, skip, { silent: true });
  },
  next: () => nextQuestion({ silent: true }),
  finish: () => finishSession(),
});
bindLiveSettings();

function syncTheme() {
  const theme = window.MLTheme.current;
  settingsPage.querySelector("#theme-choice").value = theme;
  if (typeof window.pywebview?.api?.set_theme === "function") {
    window.pywebview.api.set_theme(theme).catch(() => {});
  }
}

settingsPage.querySelector("#theme-choice").addEventListener("change", (event) => window.MLTheme.set(event.target.value));
window.addEventListener("ml-theme-change", syncTheme);
window.addEventListener("pywebviewready", syncTheme);
window.addEventListener("storage", (event) => { if (event.key === "ml-theme") { window.MLTheme.set(event.newValue); } });
syncTheme();

async function route() {
  if (!state.config) return;
  if (state.busy) { toast("Дождись завершения запроса."); history.replaceState(null, "", `#${state.page}`); return; }
  const page = location.hash.slice(1) || "home";
  const nextPage = ["home", "library", "history", "training", "settings"].includes(page) ? page : "home";
  if (live.enabled) {
    if (nextPage === "settings") {
      if (live.running) live.pause("Настройки открыты. Вернись к тренировке и нажми «Продолжить».");
    } else if (!(state.page === "settings" && nextPage === "training" && live.paused)) {
      live.stop();
    }
  }
  cancelSpeech();
  discardRecording();
  state.page = nextPage;
  try {
    if (state.page === "home") await renderHome();
    else if (state.page === "library") await renderLibrary();
    else if (state.page === "history") await renderHistory();
    else if (state.page === "settings") renderSettings();
    else {
      renderTraining();
      if (state.liveNext && state.session?.question) { state.liveNext = false; await live.start({ prepared: true }); }
      else if (state.speakNext && state.session?.question) { state.speakNext = false; speak(state.session.question.question); }
    }
  } catch (error) { setPage(`<div class="error-state">${escapeHTML(error.message)}<br><button class="text-button" data-action="reload">Попробовать снова ${icon("arrow")}</button></div>`, "Ошибка"); }
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  if (action.startsWith("live-")) {
    try {
      if (action === "live-pause") live.pause();
      else if (action === "live-manual") live.stop();
      else if (action === "live-finish") { const task = live.task; live.stop(); await task; await finishSession(); }
      else if (action === "live-start" || action === "live-resume") {
        if (state.recorder?.state === "recording") { toast("Сначала закончи текущую запись."); return; }
        await live.start();
      }
    } catch (error) { toast(error.message); }
    return;
  }
  if (state.busy && !["speak", "toggle-sound", "stop-preview"].includes(action)) { toast("Дождись завершения запроса."); return; }
  try {
    if (live.running && action === "speak") live.pause("Live Training на паузе для повторного прослушивания.");
    if (action === "start") showStart();
    else if (action === "topic") showStart(target.dataset.topic);
    else if (["home", "library", "history"].includes(action)) location.hash = action;
    else if (action === "settings") openSettings("connections");
    else if (action === "avatar-settings") openSettings("avatar");
    else if (action === "preview-voice") {
      const intro = trainerVoice() === "male" ? "Я подготовил вопрос" : "Я подготовила вопрос";
      await speak(`Привет! ${intro} о переобучении. Почему модель может хорошо работать на обучающих данных и ошибаться на новых?`, { force: true });
    }
    else if (action === "stop-preview") cancelSpeech();
    else if (action === "resume") location.hash = "training";
    else if (action === "next") await nextQuestion();
    else if (action === "finish") await finishSession();
    else if (action === "skip") { discardRecording(); await submitAnswer(null, true); }
    else if (action === "record") await record();
    else if (action === "speak") { if (state.recorder?.state === "recording") return; speak(target.dataset.text, { force: true }); }
    else if (action === "toggle-sound") { setAutoSpeech(!state.sound); toast(state.sound ? "Автоозвучка включена." : "Автоозвучка выключена. Сообщения можно послушать кнопкой динамика."); }
    else if (action === "filter") { state.libraryTopic = target.dataset.topic; await renderLibrary(); }
    else if (action === "history-page") { target.disabled = true; try { await renderHistory(Number(target.dataset.page)); } finally { target.disabled = false; } }
    else if (action === "open-session") { applySession(await api(`/sessions/${target.dataset.id}`)); storage.set("ml-session", state.session.id); location.hash = "training"; }
    else if (action === "reload") await route();
    else if (action === "logout") {
      await api("/beta/logout", { method: "POST" });
      showBetaLogin();
    }
    else if (action === "shutdown") { live.stop(); discardRecording(); cancelSpeech(); if (isDesktop()) { await window.pywebview.api.close(); return; } await api("/shutdown", { method: "POST" }); setPage(`<div class="empty-state">${icon("check")}<h3>Приложение остановлено</h3><p>Можно закрыть окно. Чтобы продолжить, снова нажми на ярлык ML Trainer.</p></div>`, "До встречи"); }
  } catch (error) { toast(error.message); }
});

let searchTimer;
document.addEventListener("input", (event) => {
  if (event.target.id === "answer-input") storage.set(draftKey(), event.target.value);
  if (event.target.id === "card-search") { state.query = event.target.value; clearTimeout(searchTimer); searchTimer = setTimeout(() => searchCards().catch((error) => toast(error.message)), 350); }
});
document.addEventListener("change", (event) => {
  if (event.target.id === "session-mode") $("#live-options").hidden = event.target.value !== "live";
  if (event.target.id === "session-topic" || event.target.id === "session-level") updateSessionCounts();
  if (event.target.id === "library-level") { state.libraryLevel = event.target.value; searchCards().catch((error) => toast(error.message)); }
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && event.target.id === "answer-input") submitAnswer(event);
});
window.addEventListener("hashchange", route);
window.addEventListener("pagehide", () => { live.stop(); discardRecording(); cancelSpeech(); trainerAvatar.context?.close().catch(() => {}); });
$("#speech-indicator").addEventListener("click", cancelSpeech);
$("#close-start").addEventListener("click", () => $("#start-dialog").close());
$("#start-form").addEventListener("submit", startSession);
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } }));

async function boot() {
  try {
    state.config = await api("/config");
    syncBetaControls(state.config);
    syncVoiceControls();
    await trainerAvatar.load().catch(() => toast("Не удалось загрузить картинки аватара. Тренировка доступна."));
    $("#mode-badge").textContent = state.config.ai ? "AI-проверка" : "Демо-режим";
    $("#mode-badge").hidden = false;
    $("#mode-badge").title = state.config.ai ? "Разбор ответа по критериям вопроса" : "Проверка по ключевым словам без оценки понимания";
    $("#nav-count").textContent = state.config.cards;
    const sessionId = storage.get("ml-session");
    if (sessionId) { try { applySession(await api(`/sessions/${sessionId}`)); } catch { storage.remove("ml-session"); } }
    await route();
  } catch (error) {
    if (error.status !== 401) {
      setPage(`<div class="error-state">Не удалось подключиться к приложению. Обнови страницу и попробуй ещё раз.</div>`, "Подключение");
    }
  }
}
boot();
