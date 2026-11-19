"use strict";

const $ = (selector) => document.querySelector(selector);
const isDesktop = () => typeof window.pywebview?.api?.close === "function";
const speechRecognitionReady = () => Boolean(state.config?.deepgram || state.config?.whisper);
const storage = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch {} },
  remove(key) { try { localStorage.removeItem(key); } catch {} },
};
function savedVolume() {
  const stored = storage.get("ml-voice-volume");
  const value = stored === null ? 75 : Number(stored);
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) / 100 : 0.75;
}

const voiceTones = new Set(["natural", "calm", "very_calm_slow", "friendly", "excited", "soft", "whisper"]);
const savedTone = storage.get("ml-voice-tone");
// A separate preference makes automatic narration explicit and enabled on first use.
const state = { config: null, session: null, busy: false, awaitingNext: false, libraryTopic: "all", libraryLevel: "all", query: "", sound: storage.get("ml-auto-speech") !== "off", volume: savedVolume(), tone: voiceTones.has(savedTone) ? savedTone : "natural", page: "home", historyPage: 1, historyVersion: 0, recorder: null, stream: null, recordingTimer: null, toastTimer: null, searchVersion: 0 };
const speech = { version: 0, controller: null, audio: null, reader: null, receiving: false, utterance: null, objectUrl: null, status: "idle", completion: null, resolve: null };
const trainerAvatar = new TrainerAvatar({ api, storage, toast });
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
      throw new Error("Для Live Training настрой озвучку в «Подключениях».");
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

function updateLiveUI() {
  syncTrainerAvatar();
  const panel = $("#live-panel");
  if (!panel) return;
  const key = `${live.enabled}:${live.paused}`;
  if (panel.dataset.mode !== key) {
    panel.dataset.mode = key;
    panel.innerHTML = live.enabled
      ? `<div class="live-heading"><span class="live-badge">● LIVE TRAINING</span><div class="live-actions"><button class="button small" data-action="${live.paused ? "live-resume" : "live-pause"}">${live.paused ? "Продолжить" : "Пауза"}</button><button class="text-button" data-action="live-manual">Обычный режим</button><button class="text-button" data-action="live-finish">Завершить</button></div></div><p class="live-status" role="status" aria-live="polite"></p><div class="live-meter" aria-hidden="true"><i></i></div><small>Команды: «повтори вопрос», «следующий вопрос», «пауза», «заверши тренировку». После разбора — 6 секунд на уточнение.</small>`
      : `<div class="live-heading"><div><strong>Голосовой диалог</strong><p>Слушай вопросы и отвечай без кнопок.</p></div><button class="button small" data-action="live-start">Включить</button></div>`;
  }
  if (live.enabled) {
    const status = panel.querySelector(".live-status");
    if (status.textContent !== live.message) status.textContent = live.message;
    panel.querySelector(".live-meter i").style.width = `${Math.round(live.level * 100)}%`;
    panel.dataset.phase = live.phase;
  }
  const resume = panel.querySelector('[data-action="live-resume"]');
  if (resume) resume.disabled = state.busy;
  const start = panel.querySelector('[data-action="live-start"]');
  if (start) start.disabled = state.busy;
  const locked = live.running || state.busy;
  for (const selector of ["#record-button", "#submit-answer", "#next-question", '[data-action="skip"]']) {
    if ($(selector)) $(selector).disabled = locked;
  }
  if ($("#answer-input")) $("#answer-input").readOnly = live.running;
}

function showTranscriptOriginal(result, field) {
  $("#transcription-review")?.remove();
  if (result.cleanup === "applied" && result.raw_text !== result.text) {
    field.insertAdjacentHTML("afterend", `<details class="transcription-review" id="transcription-review"><summary>Исходная расшифровка последней записи</summary><p>${escapeHTML(result.raw_text)}</p></details>`);
  }
}

function syncTrainerAvatar() {
  if (state.recorder?.state === "recording" || (live.running && ["listening", "followup"].includes(live.phase))) {
    trainerAvatar.update("listening", "Слушаю тебя");
  } else if ((state.busy && speech.status !== "playing") || speech.status === "loading") {
    trainerAvatar.update("thinking", "Думаю над ответом…");
  } else {
    const attempt = state.session?.attempts.find((item) => item.question.id === state.session?.question?.id);
    const reaction = attempt ? (attempt.mode === "ai" && attempt.score >= 70 ? "positive" : "supportive") : "neutral";
    trainerAvatar.update(reaction, speech.status === "playing" ? "Говорю…" : attempt ? "Можно обсудить ответ" : "Готов к тренировке");
  }
}

function syncVoiceControls() {
  const percent = Math.round(state.volume * 100);
  $("#voice-volume").value = percent;
  $("#voice-volume").style.setProperty("--volume", `${percent}%`);
  $("#voice-volume-output").textContent = `${percent}%`;
  $("#voice-volume-summary").textContent = `${percent}%`;
  $("#auto-speech").checked = state.sound;
  $("#voice-tone").value = state.tone;
  const fish = state.config?.tts?.provider === "fish";
  $("#voice-tone").disabled = !fish;
  $(".voice-tone-preview").disabled = !fish || !state.config.tts.ready;
  $("#voice-tone-hint").textContent = fish ? "Подача следующей фразы. Сила эффекта зависит от голоса и текста." : "Выбор интонации доступен для голоса Fish Audio.";
  const toggle = $('[data-action="toggle-sound"]');
  if (toggle) {
    toggle.classList.toggle("off", !state.sound);
    toggle.setAttribute("aria-pressed", String(state.sound));
    toggle.setAttribute("aria-label", state.sound ? "Выключить автоозвучку" : "Включить автоозвучку");
    toggle.title = state.sound ? "Выключить автоозвучку" : "Включить автоозвучку";
  }
}

function setVolume(percent) {
  const value = Number(percent);
  if (!Number.isFinite(value)) return;
  state.volume = Math.max(0, Math.min(100, value)) / 100;
  if (state.volume === 0 && live.running) live.pause("Громкость 0%. Увеличь громкость и нажми «Продолжить».");
  storage.set("ml-voice-volume", String(Math.round(state.volume * 100)));
  if (speech.audio) speech.audio.volume = state.volume;
  if (speech.utterance) speech.utterance.volume = state.volume;
  syncVoiceControls();
}

function setAutoSpeech(enabled) {
  state.sound = Boolean(enabled);
  if (!enabled && live.running) live.pause("Автоозвучка выключена. Live Training на паузе.");
  storage.set("ml-auto-speech", state.sound ? "on" : "off");
  if (!state.sound) cancelSpeech();
  syncVoiceControls();
}

$("#voice-volume").addEventListener("input", (event) => setVolume(event.target.value));
$("#auto-speech").addEventListener("change", (event) => setAutoSpeech(event.target.checked));
$("#voice-tone").addEventListener("change", (event) => {
  if (!voiceTones.has(event.target.value)) return;
  state.tone = event.target.value;
  storage.set("ml-voice-tone", state.tone);
  cancelSpeech();
  syncVoiceControls();
});
document.addEventListener("click", (event) => { if (!event.target.closest("#voice-controls")) $("#voice-controls").open = false; });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && $("#voice-controls").open) { $("#voice-controls").open = false; $("#voice-controls summary").focus(); } });
syncVoiceControls();

function syncTheme() {
  const dark = window.MLTheme.current === "dark";
  const button = $("#theme-toggle");
  const label = dark ? "Включить светлую тему" : "Включить тёмную тему";
  button.innerHTML = icon(dark ? "sun" : "moon");
  button.setAttribute("aria-label", label);
  button.setAttribute("aria-pressed", String(dark));
  button.title = label;
  if (typeof window.pywebview?.api?.set_theme === "function") {
    window.pywebview.api.set_theme(dark ? "dark" : "light").catch(() => {});
  }
}

$("#theme-toggle").addEventListener("click", () => window.MLTheme.set(window.MLTheme.current === "dark" ? "light" : "dark"));
window.addEventListener("ml-theme-change", syncTheme);
window.addEventListener("pywebviewready", syncTheme);
window.addEventListener("storage", (event) => { if (event.key === "ml-theme") { window.MLTheme.set(event.newValue); } });
syncTheme();

async function api(path, options = {}) {
  const headers = { "X-App-Token": state.config?.token || "", ...options.headers };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(`/api${path}`, { ...options, headers });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Не удалось выполнить запрос. Попробуй ещё раз.");
  return result;
}

function toast(message) {
  const element = $("#toast");
  clearTimeout(state.toastTimer);
  element.textContent = message;
  element.hidden = false;
  state.toastTimer = setTimeout(() => { element.hidden = true; }, 7000);
}

function topicName(id) {
  return state.config.topics.find((topic) => topic.id === id)?.name || "Все темы";
}

function formatDate(value) {
  return new Date(value.replace(" ", "T") + "Z").toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function setPage(html, label) {
  $("#app-content").innerHTML = html;
  $("#page-label").textContent = label;
  document.querySelectorAll(".nav-link[data-page]").forEach((link) => link.classList.toggle("active", link.dataset.page === state.page));
  syncVoiceControls();
}

async function renderHome() {
  const { answered, completed } = await api("/stats");
  if (state.page !== "home") return;
  const date = new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
  const resume = state.session && !state.session.completed;
  setPage(`
    <div class="intro"><div><h1>Время разобраться в ML</h1></div><span class="date-note">${escapeHTML(date)}</span></div>
    ${resume ? `<div class="resume-banner"><span>Есть незавершённая тренировка · ${escapeHTML(topicName(state.session.topic))}</span><button class="text-button" data-action="resume">Продолжить ${icon("arrow")}</button></div>` : ""}
    <section class="hero"><div class="hero-copy"><span class="hero-pill">${icon("spark")} ПОДГОТОВКА К ML-ИНТЕРВЬЮ</span><h2>Понимать глубже.<br><span>Отвечать увереннее.</span></h2><p>Объясняй идеи своими словами, замечай пробелы<br class="desktop-break"> и закрепляй знания — по одному вопросу за раз.</p><div class="hero-actions"><button class="button primary" data-action="start">Начать тренировку ${icon("arrow")}</button></div></div><div class="hero-art" aria-hidden="true"><div class="orbit"></div><div class="orbit second"></div><div class="voice-card"><div class="voice-label"><span class="status-dot"></span> Голосовая практика</div><div class="wave">${[9,17,25,15,33,41,27,46,35,21,31,19,11,17,8].map((height) => `<i style="--h:${height}px"></i>`).join("")}</div><div class="voice-caption">Объясняй. Обсуждай. Повторяй.</div></div><span class="float-tag">${icon("check")} Текстом или голосом</span></div></section>
    <div class="metrics-strip"><div class="metric"><span class="metric-icon">${icon("cards")}</span><div><strong>${state.config.cards}</strong><small>вопросов в банке</small></div></div><div class="metric"><span class="metric-icon">${icon("check")}</span><div><strong>${answered}</strong><small>ответов в истории</small></div></div><div class="metric"><span class="metric-icon">${icon("clock")}</span><div><strong>${completed}</strong><small>тренировок завершено</small></div></div></div>
    <div class="section-heading"><h2>Выбери направление</h2><button class="text-button" data-action="library">Весь банк вопросов ${icon("arrow")}</button></div>
    <div class="topic-grid">${state.config.topics.map((topic) => `<button class="topic-card" data-action="topic" data-topic="${topic.id}" ${topic.count ? "" : 'disabled aria-disabled="true"'}><span class="topic-symbol">${topic.symbol}</span><h3>${escapeHTML(topic.name)}</h3><p>${escapeHTML(topic.description)}</p><div class="topic-meta"><span>${topic.count ? `${topic.count} вопросов` : "Скоро · вопросы ещё не добавлены"}</span>${icon("arrow")}</div></button>`).join("")}</div>
    ${!state.config.ai ? `<div class="below-topics"><span>Демо-проверка ищет ключевые слова. Подключи AI для разбора по смыслу.</span><button class="text-button" data-action="settings">Подключения ${icon("arrow")}</button></div>` : ""}
  `, "Обзор");
}

function showStart(topic = "all") {
  if (live.running) live.pause("Выбор новой тренировки открыт. Текущий вопрос сохранён.");
  $("#session-topic").innerHTML = `<option value="all">Все темы · ${state.config.cards} вопросов</option>` + state.config.topics.map((item) => `<option value="${item.id}" ${item.count ? "" : "disabled"}>${escapeHTML(item.name)} · ${item.count ? item.count + " вопросов" : "скоро"}</option>`).join("");
  $("#session-topic").value = topic;
  const candidateLevel = storage.get("ml-candidate-level");
  $("#candidate-level").value = ["Junior", "Middle", "Senior"].includes(candidateLevel) ? candidateLevel : "Middle";
  $("#start-dialog").showModal();
}

async function startSession(event) {
  event.preventDefault();
  live.stop();
  cancelSpeech();
  discardRecording();
  const button = $("#start-form button[type=submit]");
  button.disabled = true;
  try {
    const liveMode = $("#session-mode").value === "live";
    live.timing.silenceMs = Number($("#live-silence").value);
    live.threshold = Number($("#live-sensitivity").value);
    if (liveMode) {
      await live.prepare();
      if (!$("#start-dialog").open) { live.stop(); return; }
    }
    if (state.session && !state.session.completed) {
      await api(`/sessions/${state.session.id}/finish`, { method: "POST" });
    }
    const candidateLevel = $("#candidate-level").value;
    applySession(await api("/sessions", { method: "POST", body: { topic: $("#session-topic").value, level: $("#session-level").value, candidate_level: candidateLevel, count: Number($("#session-count").value) } }));
    storage.set("ml-candidate-level", candidateLevel);
    storage.set("ml-session", state.session.id);
    state.awaitingNext = false;
    $("#start-dialog").close();
    if (location.hash === "#training") {
      state.page = "training"; renderTraining();
      if (liveMode) await live.start({ prepared: true }); else speak(state.session.question.question);
    } else { state.speakNext = !liveMode; state.liveNext = liveMode; location.hash = "training"; }
  } catch (error) { live.stop(); toast(error.name === "NotAllowedError" ? "Разреши доступ к микрофону, чтобы начать Live Training." : error.message); }
  finally { button.disabled = false; }
}

function applySession(session) {
  state.session = session;
  state.awaitingNext = Boolean(session.reviewing);
}

function draftKey() { return `ml-${state.session?.reviewing ? "discussion" : "draft"}-${state.session?.id}-${state.session?.question?.id}`; }

function renderTraining() {
  const session = state.session;
  if (!session) { showStart(); location.hash = "home"; return; }
  if (session.completed) { renderResults(); return; }
  const question = session.question;
  const reviewing = session.reviewing;
  const attempt = session.attempts.find((item) => item.question.id === question.id);
  let messages = messageHTML("assistant", question.question, "", true);
  if (attempt) {
    messages += messageHTML("user", attempt.mode === "skipped" ? "Пропускаю этот вопрос." : attempt.answer);
    messages += messageHTML("assistant", attempt.feedback, rubricHTML(attempt), true);
    if (attempt.discussion?.length) messages += `<div class="conversation-divider">Обсуждение вопроса</div>` + discussionHTML(attempt);
  }
  const topic = question?.topic || topicName(session.topic);
  const current = session.current_index + 1;
  const lastQuestion = current >= session.total;
  const nextPanel = reviewing ? `<div class="next-panel"><p>Есть вопросы к разбору? Обсуди их с тренером.</p><button class="button primary" data-action="next" id="next-question">${lastQuestion ? "Итоги тренировки" : "Следующий вопрос"} ${icon("arrow")}</button></div>` : "";
  const composer = `<form class="composer ${reviewing ? "discussion-composer" : ""}" id="answer-form"><label class="sr-only" for="answer-input">${reviewing ? "Сообщение тренеру" : "Твой ответ"}</label><textarea id="answer-input" maxlength="12000" placeholder="${reviewing ? "Задай вопрос или уточни свой ответ…" : "Напиши ответ или запиши его голосом…"}">${escapeHTML(storage.get(draftKey()) || "")}</textarea><div class="composer-actions"><div class="composer-left"><button class="mic-button" type="button" data-action="record" id="record-button">${icon("mic")} Ответить голосом</button><button type="button" class="icon-button ${state.sound ? "" : "off"}" data-action="toggle-sound" aria-label="Переключить озвучку" aria-pressed="${state.sound}">${icon("sound")}</button></div><button class="button primary" type="submit" id="submit-answer">${reviewing ? "Отправить" : "Проверить ответ"} ${icon("arrow")}</button></div><div class="composer-actions">${reviewing ? '<span class="composer-footnote">Обсуждаем текущий вопрос</span>' : '<button class="text-button" type="button" data-action="skip">Пока не знаю — показать объяснение</button>'}<span class="composer-footnote">Ctrl + Enter</span></div>${!state.config.ai ? '<p class="composer-footnote">Демо-проверка по ключевым словам · оценка понимания недоступна</p>' : ""}</form>`;
  setPage(`
    <div class="page-title"><div><h1>Тренировка</h1><p>${escapeHTML(topic)} · ${escapeHTML(question.level)}</p></div><button class="button small" data-action="finish">Завершить</button></div>
    <div class="training-layout"><section class="chat-panel"><div id="live-panel" class="live-panel"></div><div class="chat-header"><span>Вопрос ${current} из ${session.total}</span><span class="chat-status"><span class="status-dot"></span><span id="activity-label">${reviewing ? "Обсуждаем вопрос" : "Твой ход"}</span></span></div><div class="chat-messages" id="chat-messages" role="log" aria-live="polite">${messages}</div>
    ${followupsHTML(question)}${nextPanel}${composer}</section>
    <aside class="training-side"><div id="trainer-avatar"></div><div class="side-card"><h3>Твоя практика</h3><div class="progress-number">${session.answered} <span>/ ${session.total}</span></div><div class="progress-track"><div style="width:${100 * session.answered / session.total}%"></div></div><small>вопросов разобрано</small><div class="session-topic">${escapeHTML(topicName(session.topic))}</div></div></aside></div>
  `, "Тренировка");
  const chat = $("#chat-messages");
  chat.scrollTo({ top: chat.scrollHeight, behavior: "instant" });
  $("#answer-form").addEventListener("submit", submitAnswer);
  updateLiveUI();
}

async function submitAnswer(event, skip = false, { silent = false } = {}) {
  event?.preventDefault();
  if (live.running && !silent) return;
  if (state.busy || state.recorder?.state === "recording") return;
  const answer = $("#answer-input")?.value || "";
  const reviewing = state.session.reviewing;
  if (!skip && !answer.trim()) { toast("Сначала напиши или запиши ответ."); $("#answer-input").focus(); return; }
  state.busy = true;
  const key = draftKey();
  $("#submit-answer").disabled = true;
  $("#record-button").disabled = true;
  $("#answer-input").disabled = true;
  if ($("#next-question")) $("#next-question").disabled = true;
  $("#activity-label").textContent = reviewing ? "Отвечаю…" : "Разбираю ответ…";
  cancelSpeech();
  try {
    const result = await api(`/sessions/${state.session.id}/${reviewing ? "discuss" : "answer"}`, { method: "POST", body: reviewing ? { question_id: state.session.question.id, message: answer } : { question_id: state.session.question.id, answer, skip } });
    applySession(result.session);
    storage.remove(key);
    if (state.page === "training") {
      renderTraining();
      if (!silent) speak(reviewing ? result.discussion.reply : result.evaluation.feedback);
    }
    return result;
  } catch (error) {
    toast(error.message);
    if ($("#submit-answer")) $("#submit-answer").disabled = false;
    if ($("#record-button")) $("#record-button").disabled = false;
    if ($("#answer-input")) $("#answer-input").disabled = false;
    if ($("#next-question")) $("#next-question").disabled = false;
    if ($("#activity-label")) $("#activity-label").textContent = "Можно попробовать ещё раз";
    if (silent) throw error;
  } finally { state.busy = false; updateLiveUI(); }
}

async function nextQuestion({ silent = false } = {}) {
  if (state.busy) return;
  state.busy = true;
  discardRecording();
  cancelSpeech();
  $("#next-question").disabled = true;
  $("#answer-input").disabled = true;
  try {
    applySession(await api(`/sessions/${state.session.id}/next`, { method: "POST", body: { question_id: state.session.question.id } }));
    renderTraining();
    if (state.session.question && !silent) speak(state.session.question.question);
    return state.session;
  } catch (error) {
    toast(error.message);
    if ($("#next-question")) $("#next-question").disabled = false;
    if ($("#answer-input")) $("#answer-input").disabled = false;
    if (silent) throw error;
  } finally { state.busy = false; updateLiveUI(); }
}

function renderResults() {
  const session = state.session;
  const assessed = session.attempts.filter((attempt) => attempt.mode === "ai");
  const skipped = session.attempts.filter((attempt) => attempt.mode === "skipped").length;
  const average = assessed.length ? Math.round(assessed.reduce((sum, attempt) => sum + attempt.score, 0) / assessed.length) : null;
  setPage(`<div class="results"><div class="result-hero"><div class="result-symbol">✳</div><h1>Практика завершена</h1><p>Теперь ты чуть лучше знаешь, на что обратить внимание.</p><div class="result-numbers"><div><strong>${session.answered}</strong><small>вопросов разобрано</small></div><div><strong>${average === null ? "—" : average + "%"}</strong><small>${average === null ? "AI-оценки пока нет" : "средняя AI-оценка"}</small></div><div><strong>${skipped}</strong><small>пропущено</small></div></div><p>${assessed.length ? "Оценка модели — ориентир для повторения. Главная ценность — в разборе." : "Демо-проверка не оценивает понимание. Посмотри объяснения и повтори сложные вопросы."}</p></div><div class="section-heading"><h2>Что разобрали</h2></div>${session.attempts.length ? session.attempts.map((attempt) => `<details class="result-row"><summary>${escapeHTML(attempt.question.title)}<span class="tag">${attempt.mode === "ai" ? attempt.score + "%" : attempt.mode === "skipped" ? "Пропущен" : "Демо"}</span></summary><p><strong>Твой ответ:</strong> ${escapeHTML(attempt.answer || "Вопрос пропущен")}</p><p>${escapeHTML(attempt.feedback)}</p>${rubricHTML(attempt)}${attempt.discussion?.length ? `<div class="history-discussion">${discussionHTML(attempt)}</div>` : ""}</details>`).join("") : `<p class="helper">В этот раз ответов не было. Можно начать снова, когда будет удобно.</p>`}<div class="result-actions"><button class="button primary" data-action="start">Ещё одна тренировка ${icon("arrow")}</button><button class="button" data-action="home">На главную</button></div></div>`, "Итоги");
}

async function renderLibrary() {
  setPage(`<div class="page-title"><div><h1>Банк вопросов</h1><p>Исследуй темы или найди вопрос для следующей практики.</p></div><button class="button primary small" data-action="start">Тренироваться ${icon("arrow")}</button></div><form id="search-form"><label class="sr-only" for="card-search">Поиск вопросов</label><div class="search-box">${icon("search")}<input id="card-search" value="${escapeHTML(state.query)}" maxlength="500" placeholder="Например: переобучение, precision, регуляризация…" autocomplete="off"></div></form><div class="filter-row">${[{ id: "all", name: "Все темы" }, ...state.config.topics].map((topic) => `<button class="chip ${state.libraryTopic === topic.id ? "active" : ""}" data-action="filter" data-topic="${topic.id}">${escapeHTML(topic.name)}</button>`).join("")}</div><p class="search-note" id="library-count" role="status"></p><div class="library-grid" id="library-results"><span class="spinner"></span></div>`, "Банк вопросов");
  $("#search-form").addEventListener("submit", (event) => { event.preventDefault(); searchCards(); });
  $("#search-form").insertAdjacentHTML("afterend", `<div class="level-filter"><label for="library-level">Сложность</label><select id="library-level"><option value="all" ${state.libraryLevel === "all" ? "selected" : ""}>Все уровни</option>${["Junior", "Middle", "Senior"].map((level) => `<option value="${level}" ${state.libraryLevel === level ? "selected" : ""}>${level}</option>`).join("")}</select></div>`);
  await searchCards();
}

async function searchCards() {
  const version = ++state.searchVersion;
  state.query = $("#card-search")?.value ?? state.query;
  const result = await api(`/cards?q=${encodeURIComponent(state.query)}&topic=${encodeURIComponent(state.libraryTopic)}&level=${encodeURIComponent(state.libraryLevel)}`);
  if (version !== state.searchVersion || state.page !== "library") return;
  $("#library-count").textContent = `Найдено вопросов: ${result.cards.length}`;
  $("#library-results").innerHTML = result.cards.length ? result.cards.map((card) => `<article class="question-card"><span class="eyebrow">${escapeHTML(card.topic)}</span><h3>${escapeHTML(card.title)}</h3><p>${escapeHTML(card.question)}</p><div class="question-card-footer"><span class="tag">${escapeHTML(card.level)}</span><span class="tag">${escapeHTML(card.tags[0])}</span><button class="text-button" data-action="topic" data-topic="${card.topic_id}">Практиковать тему ${icon("arrow")}</button></div></article>`).join("") : `<div class="empty-state"><h3>Пока нет вопросов</h3><p>Измени запрос, тему или сложность.</p></div>`;
}

async function renderHistory(page = state.historyPage) {
  const version = ++state.historyVersion;
  const result = await api(`/history?page=${page}`);
  if (version !== state.historyVersion || state.page !== "history") return;
  const changedPage = result.page !== state.historyPage;
  state.historyPage = result.page;
  setPage(`<div class="page-title"><div><h1>История тренировок</h1><p>Твои ответы и разборы сохраняются между запусками.</p></div></div>${result.sessions.length ? `<div class="history-list">${result.sessions.map((session) => `<article class="history-item"><span class="metric-icon">${icon(session.completed_at ? "check" : "clock")}</span><div><h3>${escapeHTML(topicName(session.topic))}</h3><p>${escapeHTML(formatDate(session.created_at))} · Ответов: ${session.answered} · ${session.completed_at ? "Завершена" : "В процессе"}</p></div><button class="button small" data-action="open-session" data-id="${session.id}">${session.completed_at ? "Посмотреть" : "Продолжить"} ${icon("arrow")}</button></article>`).join("")}</div>` : `<div class="empty-state">${icon("clock")}<h3>Первая тренировка ещё впереди</h3><p>Начни с пары вопросов. Здесь появятся твои ответы, разборы и темы для повторения.</p><button class="button primary" data-action="start">Начать практику ${icon("arrow")}</button></div>`}`, "История");
  if (result.total_pages > 1) {
    const first = (result.page - 1) * result.page_size + 1;
    const last = first + result.sessions.length - 1;
    $("#app-content").insertAdjacentHTML("beforeend", `<nav class="history-pagination" aria-label="Страницы истории"><button class="button small" data-action="history-page" data-page="${result.page - 1}" ${result.page === 1 ? "disabled" : ""} aria-label="Предыдущая страница истории">Назад</button><div class="history-page-info" role="status">Страница ${result.page} из ${result.total_pages}<span>Показаны ${first}–${last} из ${result.total}</span></div><button class="button small" data-action="history-page" data-page="${result.page + 1}" ${result.page === result.total_pages ? "disabled" : ""} aria-label="Следующая страница истории">Далее</button></nav>`);
  }
  if (changedPage) window.scrollTo({ top: 0, behavior: "instant" });
}

function showSettings() {
  if (live.running) live.pause("Настройки открыты. Нажми «Продолжить», чтобы вернуться к Live Training.");
  const config = state.config;
  const fish = config.tts?.provider === "fish";
  const speechReady = fish ? config.tts.ready : "speechSynthesis" in window;
  $("#settings-content").innerHTML = settingsHTML(config, { fish, speechReady });
  if (!$("#settings-dialog").open) $("#settings-dialog").showModal();
  speechStatus(speech.status);
}

function speechStatus(status) {
  speech.status = status;
  syncTrainerAvatar();
  const indicator = $("#speech-indicator");
  indicator.hidden = status === "idle";
  indicator.innerHTML = `${status === "loading" ? '<span class="spinner"></span>' : icon("sound")}<span>${status === "loading" ? "Готовлю голос…" : "Озвучиваю"}</span>${icon("close")}`;
  const preview = $(".voice-preview");
  if (preview && !preview.disabled) {
    preview.innerHTML = `${icon(status === "idle" ? "sound" : "stop")} ${status === "idle" ? "Послушать голос" : "Остановить озвучку"}`;
    preview.dataset.action = status === "idle" ? "preview-voice" : "stop-preview";
  }
  const tonePreview = $(".voice-tone-preview");
  tonePreview.innerHTML = `${icon(status === "idle" ? "sound" : "stop")} ${status === "idle" ? "Послушать интонацию" : "Остановить озвучку"}`;
  tonePreview.dataset.action = status === "idle" ? "preview-tone" : "stop-preview";
}

function cancelSpeech(completed = false) {
  trainerAvatar.stopAudio();
  speech.resolve?.(completed === true);
  speech.resolve = null;
  speech.version += 1;
  speech.controller?.abort();
  speech.controller = null;
  speech.reader?.cancel().catch(() => {});
  speech.reader = null;
  speech.receiving = false;
  if (speech.audio) { speech.audio.onplaying = null; speech.audio.onended = null; speech.audio.onerror = null; speech.audio.pause(); speech.audio.removeAttribute("src"); speech.audio.load(); }
  speech.audio = null;
  speech.utterance = null;
  if (speech.objectUrl) URL.revokeObjectURL(speech.objectUrl);
  speech.objectUrl = null;
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  speechStatus("idle");
}

function waitForAudioEvent(target, name, signal, action = () => {}) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      target.removeEventListener(name, done);
      target.removeEventListener("error", failed);
      signal.removeEventListener("abort", aborted);
    };
    const done = () => { cleanup(); resolve(); };
    const failed = () => { cleanup(); reject(new Error("Не удалось воспроизвести поток озвучки. Попробуй повторить.")); };
    const aborted = () => { cleanup(); reject(new DOMException("Speech cancelled", "AbortError")); };
    if (signal.aborted) { aborted(); return; }
    target.addEventListener(name, done, { once: true });
    target.addEventListener("error", failed, { once: true });
    signal.addEventListener("abort", aborted, { once: true });
    try { action(); } catch (error) { cleanup(); reject(error); }
  });
}

function speechAudio(source, version) {
  speech.objectUrl = URL.createObjectURL(source);
  const audio = new Audio(speech.objectUrl);
  audio.volume = state.volume;
  speech.audio = audio;
  trainerAvatar.attachAudio(audio);
  audio.onplaying = () => { if (speech.version === version) speechStatus("playing"); };
  audio.onended = () => { if (speech.version === version) cancelSpeech(true); };
  audio.onerror = () => { if (speech.version === version) { cancelSpeech(); toast("Не удалось воспроизвести запись. Можно повторить озвучку рядом с сообщением."); } };
  return audio;
}

async function playSpeechStream(response, version, signal) {
  const source = new MediaSource();
  const opened = waitForAudioEvent(source, "sourceopen", signal);
  const audio = speechAudio(source, version);
  await opened;
  const buffer = source.addSourceBuffer("audio/mpeg");
  const reader = response.body.getReader();
  speech.reader = reader;
  speech.receiving = true;
  let started = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (signal.aborted) throw new DOMException("Speech cancelled", "AbortError");
      if (done) break;
      if (!value.length) continue;
      await waitForAudioEvent(buffer, "updateend", signal, () => buffer.appendBuffer(value));
      if (!started) {
        started = true;
        // Keep receiving data while play() waits for enough MP3 frames to start.
        audio.play().catch((error) => {
          if (speech.version !== version) return;
          cancelSpeech();
          toast(error.name === "NotAllowedError" ? "Нажми кнопку динамика рядом с сообщением, чтобы включить воспроизведение." : "Не удалось запустить озвучку. Попробуй повторить.");
        });
      }
    }
    if (!started) throw new Error("Сервис озвучки вернул пустую запись.");
    if (source.readyState === "open") source.endOfStream();
  } finally {
    reader.releaseLock();
    if (speech.version === version) { speech.reader = null; speech.receiving = false; }
  }
}

async function speak(text, { force = false } = {}) {
  if ((!state.sound && !force) || state.recorder?.state === "recording") return;
  if (state.volume === 0) { if (force) toast("Громкость голоса — 0%. Увеличь её в настройках голоса справа вверху."); return; }
  cancelSpeech();
  speech.completion = new Promise((resolve) => { speech.resolve = resolve; });
  if (state.config?.tts?.provider === "fish") {
    if (!state.config.tts.ready) { cancelSpeech(); toast("Для голоса Fish Audio добавь FISH_AUDIO_API_KEY в .env и перезапусти приложение."); return; }
    const version = speech.version;
    const controller = new AbortController();
    speech.controller = controller;
    speechStatus("loading");
    try {
      const response = await fetch("/api/speech", {
        method: "POST", signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-App-Token": state.config.token },
        body: JSON.stringify({ text, tone: state.tone, stream: true }),
      });
      if (!response.ok) {
        const result = await response.json();
        throw new Error(typeof result.detail === "string" ? result.detail : "Не удалось озвучить сообщение.");
      }
      if (speech.version !== version) return;
      if (response.body && response.headers.get("Content-Type")?.split(";")[0] === "audio/mpeg"
          && window.MediaSource?.isTypeSupported("audio/mpeg")) {
        await playSpeechStream(response, version, controller.signal);
        return;
      }
      const blob = await response.blob();
      if (speech.version !== version) return;
      if (!blob.size || !blob.type.startsWith("audio/")) throw new Error("Сервис озвучки вернул некорректную запись.");
      const audio = speechAudio(blob, version);
      await audio.play();
      if (speech.version === version) speechStatus("playing");
    } catch (error) {
      if (speech.version !== version || error.name === "AbortError") return;
      cancelSpeech();
      toast(error.name === "NotAllowedError" ? "Нажми кнопку динамика рядом с сообщением, чтобы включить воспроизведение." : error.message);
    }
    return;
  }
  if (!("speechSynthesis" in window)) { cancelSpeech(); toast("Системная озвучка недоступна."); return; }
  const version = speech.version;
  const utterance = new SpeechSynthesisUtterance(text);
  speech.utterance = utterance;
  utterance.volume = state.volume;
  utterance.lang = "ru-RU";
  utterance.rate = 1;
  const voice = speechSynthesis.getVoices().find((item) => item.lang.toLowerCase().startsWith("ru"));
  if (voice) utterance.voice = voice;
  utterance.onstart = () => { if (speech.version === version) speechStatus("playing"); };
  utterance.onend = () => { if (speech.version === version) cancelSpeech(true); };
  utterance.onerror = (event) => { if (speech.version === version) { cancelSpeech(); if (!["canceled", "interrupted"].includes(event.error)) toast("Озвучка недоступна. Тот же текст есть в чате."); } };
  speechSynthesis.speak(utterance);
}

function releaseMicrophone() {
  clearTimeout(state.recordingTimer);
  state.stream?.getTracks().forEach((track) => track.stop());
  state.stream = null;
}

function discardRecording() {
  if (state.recorder && state.recorder.state !== "inactive") {
    state.recorder.onstop = null;
    state.recorder.stop();
  }
  releaseMicrophone();
  state.recorder = null;
}

async function record() {
  if (live.running) return;
  if (state.busy) return;
  if (state.recorder?.state === "recording") { state.recorder.stop(); return; }
  if (!speechRecognitionReady()) { toast("Для голосового ввода добавь DEEPGRAM_API_KEY или OPENAI_API_KEY в .env; инструкция — в «Подключениях»."); return; }
  if (!navigator.mediaDevices?.getUserMedia || !("MediaRecorder" in window)) { toast(isDesktop() ? "Запись недоступна. Обнови Microsoft Edge WebView2 Runtime." : "Этот браузер не поддерживает запись. Открой приложение в Edge или Chrome."); return; }
  cancelSpeech();
  const sessionId = state.session.id;
  const questionId = state.session.question.id;
  const button = $("#record-button");
  button.disabled = true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    if (state.page !== "training" || state.session?.id !== sessionId || state.session?.question?.id !== questionId) { stream.getTracks().forEach((track) => track.stop()); return; }
    state.stream = stream;
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    state.recorder = recorder;
    const chunks = [];
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    recorder.onerror = () => { discardRecording(); toast("Не удалось записать звук. Проверь микрофон."); renderTraining(); };
    recorder.onstop = async () => {
      releaseMicrophone();
      state.recorder = null;
      state.busy = true;
      syncTrainerAvatar();
      button.disabled = true;
      const cleanupReady = state.config.transcription?.ready ?? state.config.ai;
      button.innerHTML = `${icon("mic")} ${cleanupReady ? "Распознаю и очищаю…" : "Распознаю…"}`;
      button.classList.remove("recording");
      if ($("#activity-label")) $("#activity-label").textContent = cleanupReady ? "Распознаю и очищаю…" : "Распознаю…";
      if ($("#submit-answer")) $("#submit-answer").disabled = true;
      const form = new FormData();
      form.append("audio", new Blob(chunks, { type: recorder.mimeType }), "answer.webm");
      form.append("session_id", sessionId);
      form.append("question_id", String(questionId));
      try {
        const result = await api("/transcribe", { method: "POST", body: form });
        if (state.page !== "training" || state.session?.id !== sessionId || state.session?.question?.id !== questionId) return;
        const providerNote = result.provider === "whisper" ? "Использован Whisper. " : "";
        const field = $("#answer-input");
        field.value = [field.value.trim(), result.text].filter(Boolean).join(" ").slice(0, 12000);
        storage.set(draftKey(), field.value);
        showTranscriptOriginal(result, field);
        if (!result.text.trim()) toast("Речь не обнаружена. Попробуй ещё раз или напиши ответ.");
        else if (result.cleanup === "unavailable") toast(providerNote + "Речь распознана, но очистка недоступна. В поле исходный текст — проверь его перед отправкой.");
        else toast(providerNote + (state.session.reviewing ? "Сообщение распознано. Проверь текст и нажми «Отправить»." : "Ответ распознан. Проверь текст и нажми «Проверить ответ»."));
      } catch (error) { toast(error.message); }
      finally {
        state.busy = false;
        syncTrainerAvatar();
        if ($("#record-button")) { $("#record-button").disabled = false; $("#record-button").innerHTML = `${icon("mic")} Ответить голосом`; }
        if ($("#submit-answer")) $("#submit-answer").disabled = false;
        if ($("#activity-label")) $("#activity-label").textContent = "Твой ход";
      }
    };
    recorder.start(1000);
    syncTrainerAvatar();
    button.classList.add("recording");
    button.innerHTML = `${icon("stop")} Закончить запись`;
    $("#submit-answer").disabled = true;
    $("#activity-label").textContent = "Слушаю…";
    state.recordingTimer = setTimeout(() => { if (recorder.state === "recording") recorder.stop(); }, 120000);
  } catch (error) {
    releaseMicrophone();
    toast(error.name === "NotAllowedError" ? (isDesktop() ? "Разреши доступ к микрофону в приложении и параметрах конфиденциальности Windows или ответь текстом." : "Разреши доступ к микрофону в настройках браузера или ответь текстом.") : "Микрофон недоступен. Проверь подключение устройства.");
  } finally { button.disabled = false; }
}

async function finishSession() {
  live.stop();
  if (state.busy) { toast("Дождись завершения проверки."); return; }
  discardRecording();
  cancelSpeech();
  applySession(await api(`/sessions/${state.session.id}/finish`, { method: "POST" }));
  renderResults();
}

async function route() {
  if (!state.config) return;
  if (state.busy) { toast("Дождись завершения запроса."); history.replaceState(null, "", `#${state.page}`); return; }
  if (live.enabled) live.stop();
  cancelSpeech();
  discardRecording();
  const page = location.hash.slice(1) || "home";
  state.page = ["home", "library", "history", "training"].includes(page) ? page : "home";
  try {
    if (state.page === "home") await renderHome();
    else if (state.page === "library") await renderLibrary();
    else if (state.page === "history") await renderHistory();
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
  if (action === "avatar-settings") {
    if (live.running) live.pause("Настройка аватара. Нажми «Продолжить», когда будешь готов.");
    trainerAvatar.show();
    return;
  }
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
  if (state.busy && !["settings", "close-settings", "speak", "toggle-sound", "preview-voice", "preview-tone", "stop-preview"].includes(action)) { toast("Дождись завершения запроса."); return; }
  try {
    if (live.running && ["speak", "preview-voice", "preview-tone"].includes(action)) live.pause("Live Training на паузе для повторного прослушивания.");
    if (action === "start") showStart();
    else if (action === "topic") showStart(target.dataset.topic);
    else if (["home", "library", "history"].includes(action)) location.hash = action;
    else if (action === "settings") showSettings();
    else if (action === "preview-voice" || action === "preview-tone") await speak("Привет! Я твой тренер по машинному обучению. Сегодня разберём переобучение. Объясни своими словами, почему модель может ошибаться на новых данных.", { force: true });
    else if (action === "stop-preview") cancelSpeech();
    else if (action === "close-settings") $("#settings-dialog").close();
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
    else if (action === "shutdown") { discardRecording(); cancelSpeech(); if (isDesktop()) { await window.pywebview.api.close(); return; } await api("/shutdown", { method: "POST" }); $("#settings-dialog").close(); setPage(`<div class="empty-state">${icon("check")}<h3>Приложение остановлено</h3><p>Можно закрыть окно. Чтобы продолжить, снова нажми на ярлык ML Trainer.</p></div>`, "До встречи"); }
  } catch (error) { toast(error.message); }
});

let searchTimer;
document.addEventListener("input", (event) => {
  if (event.target.id === "answer-input") storage.set(draftKey(), event.target.value);
  if (event.target.id === "card-search") { state.query = event.target.value; clearTimeout(searchTimer); searchTimer = setTimeout(() => searchCards().catch((error) => toast(error.message)), 350); }
});
document.addEventListener("change", (event) => {
  if (event.target.id === "session-mode") $("#live-options").hidden = event.target.value !== "live";
  if (event.target.id === "library-level") { state.libraryLevel = event.target.value; searchCards().catch((error) => toast(error.message)); }
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && event.target.id === "answer-input") submitAnswer(event);
});
window.addEventListener("hashchange", route);
window.addEventListener("pagehide", () => { live.stop(); discardRecording(); cancelSpeech(); trainerAvatar.context?.close().catch(() => {}); });
$("#settings-button").addEventListener("click", showSettings);
$("#speech-indicator").addEventListener("click", cancelSpeech);
$("#close-settings").addEventListener("click", () => $("#settings-dialog").close());
$("#close-start").addEventListener("click", () => $("#start-dialog").close());
$("#start-form").addEventListener("submit", startSession);
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } }));

async function boot() {
  try {
    state.config = await api("/config");
    await trainerAvatar.load().catch(() => toast("Не удалось загрузить картинки аватара. Тренировка доступна."));
    $("#mode-badge").textContent = state.config.ai ? "AI-проверка" : "Демо-режим";
    $("#mode-badge").hidden = false;
    $("#mode-badge").title = state.config.ai ? "Разбор ответа по критериям вопроса" : "Проверка по ключевым словам без оценки понимания";
    $("#nav-count").textContent = state.config.cards;
    const sessionId = storage.get("ml-session");
    if (sessionId) { try { applySession(await api(`/sessions/${sessionId}`)); } catch { storage.remove("ml-session"); } }
    await route();
  } catch {
    setPage(`<div class="error-state">Не удалось подключиться к локальному серверу. Закрой окно и снова открой ярлык ML Trainer.</div>`, "Подключение");
  }
}
boot();
