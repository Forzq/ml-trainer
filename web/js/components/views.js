"use strict";

// Pure HTML renderers: no DOM mutation, application state or network requests.
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));

function interviewFrequencyHTML(rating) {
  const frequency = { 1: "редко", 2: "периодически", 3: "очень часто" }[rating];
  if (!frequency) return "";
  const label = `Оценка частоты на собеседованиях — ${frequency}, ${rating} из 3`;
  return `<span class="interview-frequency" role="img" aria-label="${label}" title="${label}"><span>${"★".repeat(rating)}</span><span class="frequency-empty">${"☆".repeat(3 - rating)}</span></span>`;
}

function messageHTML(kind, text, extra = "", speech = false) {
  return `<div class="message ${kind}"><span class="message-avatar">${kind === "user" ? "Я" : "✳"}</span><div class="message-body"><div class="message-name">${kind === "user" ? "ТВОЙ ОТВЕТ" : "ML-ТРЕНЕР"}${speech ? `<button class="icon-button" data-action="speak" data-text="${escapeHTML(text)}" aria-label="Озвучить сообщение">${icon("sound")}</button>` : ""}</div><div class="message-text">${escapeHTML(text)}</div>${extra}</div></div>`;
}


function discussionHTML(attempt) {
  return (attempt.discussion || []).map((turn) => messageHTML("user", turn.message) + messageHTML("assistant", turn.reply, "", true)).join("");
}

function rubricHTML(attempt) {
  if (!attempt.criterion_results?.length) {
    return `<div class="feedback-tags">${(attempt.covered || []).map((label) => `<span>✓ ${escapeHTML(label)}</span>`).join("")}${(attempt.missing || []).map((label) => `<span class="missing">${escapeHTML(label)}</span>`).join("")}</div>`;
  }
  const names = { correct: "Верно", partial: "Частично верно", incorrect: "Неверно", not_answered: "Не отвечено" };
  return `<details class="rubric-breakdown"><summary>Разбор по критериям · ${attempt.score}/100</summary><p>Баллы учитывают верные части ответа. Дополнительные вопросы не влияют на оценку.</p>${attempt.criterion_results.map((row) => `<div class="rubric-row"><div><span class="rubric-status ${row.status}">${names[row.status] || "Проверено"}</span><strong>${row.earned_points}/${row.max_points}</strong></div><p>${escapeHTML(row.label)}</p>${row.evidence ? `<blockquote>${escapeHTML(row.evidence)}</blockquote>` : ""}</div>`).join("")}</details>`;
}

function followupsHTML(question) {
  return question.followups?.length ? `<details class="optional-followups"><summary>Углубление · не влияет на балл</summary><p>Эти вопросы можно обсудить с тренером после основного ответа.</p><ol>${question.followups.map((text) => `<li>${escapeHTML(text)}</li>`).join("")}</ol></details>` : "";
}


function settingsHTML(config, { fish, speechReady }) {
  return `
    <div class="settings-connections">
    <div class="connection"><div><strong>AI-тренер</strong><small>${config.ai ? escapeHTML(config.model) : "Разбор по смыслу"}</small></div><span class="${config.ai ? "connected" : ""}">${config.ai ? "Подключён" : "Не подключён"}</span></div>
    <div class="connection"><div><strong>Голосовой ввод</strong><small>Deepgram · русский и английский</small></div><span class="${config.deepgram ? "connected" : ""}">${config.deepgram ? "Подключён" : "Не подключён"}</span></div>
    <div class="connection"><div><strong>OpenAI Whisper</strong><small>${config.deepgram ? "Резерв голосового ввода" : "Голосовой ввод"}</small></div><span class="${config.whisper ? "connected" : ""}">${config.whisper ? "Настроен" : "Не настроен"}</span></div>
    <div class="connection"><div><strong>Озвучка</strong><small>${fish ? "Fish Audio" : "Системный голос"}</small></div><span class="${speechReady ? "connected" : ""}">${speechReady ? "Доступна" : "Не настроена"}</span></div>
    </div>
    <div class="settings-details">
      <details><summary>Как подключить сервисы</summary><p>Заполни <code>.env</code> в папке проекта и перезапусти приложение.</p><dl class="setup-keys"><dt>Проверка ответов</dt><dd>OpenRouter: <code>OPENROUTER_API_KEY</code> и <code>OPENROUTER_MODEL</code><br>Другой совместимый API: <code>LLM_BASE_URL</code>, <code>LLM_API_KEY</code> и <code>LLM_MODEL</code></dd><dt>Голосовой ввод</dt><dd><code>DEEPGRAM_API_KEY</code> или <code>OPENAI_API_KEY</code></dd><dt>Голос Fish Audio</dt><dd><code>TTS_PROVIDER=fish</code><br><code>FISH_AUDIO_API_KEY</code></dd></dl><p>Все параметры описаны в <code>.env.example</code>. Для системной озвучки выбери <code>TTS_PROVIDER=system</code>.</p></details>
      <details><summary>Данные и конфиденциальность</summary><p>История и изображения аватара хранятся на сервере приложения. Аудиозаписи не сохраняются.</p><p>Сервис распознавания получает запись. Подключённая языковая модель получает ответ и критерии для оценки. ${config.transcription?.model === "local" ? "Расшифровка очищается правилами на сервере приложения." : config.transcription?.ready ? "Модель очистки получает расшифровку и контекст вопроса." : ""} ${fish ? "Fish Audio получает текст для озвучки." : ""} При семантическом поиске модель embeddings получает тексты вопросов и поисковые запросы. API-ключи доступны только серверу.</p></details>
      <details><summary>Техническая информация</summary><pre>${escapeHTML(config.database)} · ${config.cards} вопросов
Коллекция: ${escapeHTML(config.collection)}
Поиск: ${escapeHTML(config.embedding)}${fish ? `
Озвучка: ${escapeHTML(config.tts.model)}` : ""}</pre><p>${config.semantic ? "Поиск по смыслу через модель embeddings." : "Поиск по сходству слов. Для семантического поиска настрой OPENROUTER_EMBEDDING_MODEL."}</p></details>
    </div>`;
}
