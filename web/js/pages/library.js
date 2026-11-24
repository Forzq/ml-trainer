"use strict";

const LIBRARY_SOURCE_TAGS = ["mock-interview", "github_ques"];
const LIBRARY_CACHE_KEY = "ml-library-cards-v1";
let libraryCatalog;

async function loadLibraryCatalog(version) {
  if (libraryCatalog?.version === version) return libraryCatalog.cards;

  let saved;
  try { saved = JSON.parse(storage.get(LIBRARY_CACHE_KEY)); } catch {}
  if (saved?.version === version && Array.isArray(saved.cards)) {
    libraryCatalog = saved;
    return saved.cards;
  }

  const pending = api("/cards").then(({ cards }) => {
    if (state.config?.catalog_version === version) {
      storage.set(LIBRARY_CACHE_KEY, JSON.stringify({ version, cards }));
    }
    return cards;
  });
  libraryCatalog = { version, cards: pending };
  try {
    return await pending;
  } catch (error) {
    if (libraryCatalog?.cards === pending) libraryCatalog = undefined;
    throw error;
  }
}

async function renderLibrary() {
  setPage(`<div class="page-title"><div><h1>Банк вопросов</h1><p>Исследуй темы или найди вопрос для следующей практики.</p></div><button class="button primary small" data-action="start">Тренироваться ${icon("arrow")}</button></div><form id="search-form"><label class="sr-only" for="card-search">Поиск вопросов</label><div class="search-box">${icon("search")}<input id="card-search" value="${escapeHTML(state.query)}" maxlength="500" placeholder="Например: переобучение, mock-interview, github_ques" autocomplete="off"></div></form><div class="filter-row">${[{ id: "all", name: "Все темы" }, ...state.config.topics].map((topic) => `<button class="chip ${state.libraryTopic === topic.id ? "active" : ""}" data-action="filter" data-topic="${topic.id}">${escapeHTML(topic.name)}</button>`).join("")}</div><p class="search-note" id="library-count" role="status"></p><div class="library-grid" id="library-results"><span class="spinner"></span></div>`, "Банк вопросов");
  $("#search-form").addEventListener("submit", (event) => { event.preventDefault(); searchCards(); });
  $("#search-form").insertAdjacentHTML("afterend", `<div class="level-filter"><label for="library-level">Сложность</label><select id="library-level"><option value="all" ${state.libraryLevel === "all" ? "selected" : ""}>Все уровни</option>${["Junior", "Middle", "Senior"].map((level) => `<option value="${level}" ${state.libraryLevel === level ? "selected" : ""}>${level}</option>`).join("")}</select></div>`);
  await searchCards();
}

async function searchCards() {
  const version = ++state.searchVersion;
  state.query = $("#card-search")?.value ?? state.query;
  const query = state.query.trim().toLowerCase();
  const { libraryTopic: topic, libraryLevel: level } = state;
  const browse = !query || LIBRARY_SOURCE_TAGS.includes(query);
  let cards;
  if (browse && state.config.catalog_version) {
    const catalog = await loadLibraryCatalog(state.config.catalog_version);
    cards = catalog.filter((card) => (topic === "all" || card.topic_id === topic)
      && (level === "all" || card.level === level) && (!query || card.tags.includes(query)));
  } else {
    const result = await api(`/cards?q=${encodeURIComponent(state.query)}&topic=${encodeURIComponent(topic)}&level=${encodeURIComponent(level)}`);
    cards = result.cards;
  }
  if (version !== state.searchVersion || state.page !== "library") return;
  if (browse) {
    cards.sort((left, right) => Number(right.from_interview) - Number(left.from_interview)
      || (right.interview_frequency ?? 0) - (left.interview_frequency ?? 0) || left.id - right.id);
  }
  $("#library-count").textContent = `Найдено вопросов: ${cards.length}`;
  $("#library-results").innerHTML = cards.length
    ? cards.map(libraryCardHTML).join("")
    : `<div class="empty-state"><h3>Пока нет вопросов</h3><p>Измени запрос, тему или сложность.</p></div>`;
}

function libraryCardHTML(card) {
  const topicTag = card.tags.find((tag) => !LIBRARY_SOURCE_TAGS.includes(tag));
  const sourceTags = LIBRARY_SOURCE_TAGS.filter((tag) => card.tags.includes(tag));
  const tags = [card.level, ...(topicTag ? [topicTag] : []), ...sourceTags];
  return `<article class="question-card">
    <div class="question-card-meta"><span class="eyebrow">${escapeHTML(card.topic)}</span>${interviewFrequencyHTML(card.interview_frequency)}</div>
    <h3>${escapeHTML(card.title)}</h3><p>${escapeHTML(card.question)}</p>
    <div class="question-card-footer">${tags.map((tag) => `<span class="tag">${escapeHTML(tag)}</span>`).join("")}
      <button class="text-button" data-action="topic" data-topic="${escapeHTML(card.topic_id)}">Практиковать тему ${icon("arrow")}</button>
    </div>
  </article>`;
}
