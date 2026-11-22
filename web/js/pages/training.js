"use strict";

function showStart(topic = "all") {
  if (live.running) live.pause("Выбор новой тренировки открыт. Текущий вопрос сохранён.");
  $("#session-topic").innerHTML = `<option value="all">Все темы · ${state.config.cards} вопросов</option>` + state.config.topics.map((item) => `<option value="${item.id}" ${item.count ? "" : "disabled"}>${escapeHTML(item.name)} · ${item.count ? item.count + " вопросов" : "скоро"}</option>`).join("");
  $("#session-topic").value = topic;
  const candidateLevel = storage.get("ml-candidate-level");
  $("#candidate-level").value = ["Junior", "Middle", "Senior"].includes(candidateLevel) ? candidateLevel : "Middle";
  $("#prioritize-interviews").checked = storage.get("ml-interview-priority") !== "off";
  updateSessionCounts();
  $("#start-dialog").showModal();
}

function updateSessionCounts() {
  const topicId = $("#session-topic").value;
  const level = $("#session-level").value;
  const available = state.config.topics.reduce((count, topic) => {
    if (topicId !== "all" && topicId !== topic.id) return count;
    return count + (level === "all" ? topic.count : topic.levels[level]);
  }, 0);
  const select = $("#session-count");
  const selected = Number(select.value);
  select.querySelector("option[data-available]")?.remove();
  for (const option of select.options) {
    option.disabled = Number(option.value) > available;
    option.hidden = option.disabled;
  }
  const maxCount = Math.min(20, available);
  if (maxCount > 0 && !Array.from(select.options).some((option) => Number(option.value) === maxCount)) {
    const option = new Option(`${maxCount} · все доступные`, maxCount);
    option.dataset.available = "";
    const nextOption = Array.from(select.options).find((item) => Number(item.value) > maxCount);
    select.add(option, nextOption);
  }
  const enabled = Array.from(select.options).filter((option) => !option.disabled);
  const preferred = enabled.findLast((option) => Number(option.value) <= (selected || 4));
  select.value = preferred?.value || enabled[0]?.value || "";
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
    if (liveMode) {
      await live.prepare();
      if (!$("#start-dialog").open) { live.stop(); return; }
    }
    if (state.session && !state.session.completed) {
      await api(`/sessions/${state.session.id}/finish`, { method: "POST" });
    }
    const candidateLevel = $("#candidate-level").value;
    const prioritizeInterviews = $("#prioritize-interviews").checked;
    applySession(await api("/sessions", { method: "POST", body: {
      topic: $("#session-topic").value, level: $("#session-level").value, candidate_level: candidateLevel,
      count: Number($("#session-count").value) || 1, prioritize_interviews: prioritizeInterviews,
    } }));
    storage.set("ml-candidate-level", candidateLevel);
    storage.set("ml-interview-priority", prioritizeInterviews ? "on" : "off");
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
    <div class="page-title"><div><h1>Тренировка</h1><p>${escapeHTML(topic)} · ${escapeHTML(question.level)} ${interviewFrequencyHTML(question.interview_frequency)}</p></div><button class="button small" data-action="finish">Завершить</button></div>
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
    const question_id = state.session.question.id;
    const voice = trainerVoice();
    const body = reviewing ? { question_id, message: answer, voice } : { question_id, answer, skip, voice };
    const result = await api(`/sessions/${state.session.id}/${reviewing ? "discuss" : "answer"}`, { method: "POST", body });
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


async function finishSession() {
  live.stop();
  if (state.busy) { toast("Дождись завершения проверки."); return; }
  discardRecording();
  cancelSpeech();
  applySession(await api(`/sessions/${state.session.id}/finish`, { method: "POST" }));
  renderResults();
}

