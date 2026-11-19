"use strict";

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

