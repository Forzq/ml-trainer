"use strict";

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

