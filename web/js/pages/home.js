"use strict";

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

