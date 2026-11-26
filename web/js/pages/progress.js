"use strict";

let progressRequest;

const progressColor = (coverage) => `--progress-hue:${5 + coverage * 1.47};--progress-fill:${coverage}%`;
const progressLink = (topic, skill) => `#progress${topic ? "/" + topic.id : ""}${skill ? "/" + skill.id : ""}`;

async function renderProgress([topicId, skillId], refresh) {
  const hash = location.hash;
  const config = state.config;
  if (refresh || !progressRequest) progressRequest = api("/progress");
  const pending = progressRequest;
  const current = () => state.page === "progress" && location.hash === hash && state.config === config;
  let data;
  try {
    data = await pending;
  } catch (error) {
    if (progressRequest === pending) progressRequest = null;
    if (current()) throw error;
    return;
  }
  if (!current()) return;

  const topic = data.topics.find((item) => item.id === topicId);
  const skill = topic?.skills.find((item) => item.id === skillId);
  setPage(`
    <div class="progress-page">
      <header class="progress-heading">
        <div><h1 id="progress-title" tabindex="-1">Прогресс</h1><p>Карта тем по твоим тренировкам</p></div>
        <div class="progress-total"><strong>${data.totals.mastered}<span>/${data.totals.total}</span></strong><small>вопросов освоено</small></div>
      </header>
      <div class="progress-layout">
        <section class="progress-map-panel" aria-labelledby="progress-map-title">
          <div class="progress-map-heading">
            <div>${topic ? `<a class="progress-back" href="#progress">${icon("arrow")} Все темы</a>` : ""}
              <h2 id="progress-map-title" tabindex="-1">${escapeHTML(topic?.name ?? "Карта тем")}</h2></div>
            <span class="progress-map-count">${topic ? `Подтемы · ${topic.skills.length}` : `Направления · ${data.topics.length}`}</span>
          </div>
          ${progressGraph(data, topic, skill)}
          <div class="progress-legend" aria-label="Шкала прогресса"><span>Нужно освоить</span><i aria-hidden="true"></i><span>Освоено</span></div>
        </section>
        ${progressDetail(data, topic, skill)}
      </div>
    </div>`, "Прогресс");
  if (skill) $("#progress-practice").addEventListener("click", () => showStart(topic.id, skill));
  if (!refresh) {
    const destination = $(skill ? "#progress-detail-title" : "#progress-map-title");
    destination.focus({ preventScroll: true });
    if (skill) destination.scrollIntoView({ block: "nearest" });
  }
}

function progressGraph(data, topic, selected) {
  const nodes = topic?.skills ?? data.topics;
  if (!nodes.length) return '<p class="progress-map-empty">В этой теме пока нет вопросов.</p>';
  const rows = Math.ceil(nodes.length / 2);
  const offset = Math.floor(nodes.length / 2);
  const positions = nodes.map((node, index) => {
    const right = index >= rows;
    const row = right ? index - rows : index;
    const count = right ? offset : rows;
    return { node, x: right ? 81 : 19, y: 100 * (row + .5) / count, right };
  });
  const edges = positions.map(({ node, x, y, right }) =>
    `<path class="${node === selected ? "progress-edge-current" : ""}" d="M 500 500 C ${right ? 640 : 360} 500, ${right ? 630 : 370} ${y * 10}, ${x * 10} ${y * 10}"/>`).join("");
  return `<div class="progress-graph" style="--progress-rows:${rows}">
    <svg class="progress-edges" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">${edges}</svg>
    <div class="progress-root">
      <span aria-hidden="true">${topic ? escapeHTML(topic.symbol) : icon("map")}</span>
      <strong>${escapeHTML(topic?.name ?? "ML")}</strong>
      <small>${topic ? `${topic.coverage}% охвата` : `${data.totals.total} вопросов`}</small>
    </div>
    ${positions.map(({ node, x, y }) => `<a class="progress-node" href="${progressLink(topic ?? node, topic ? node : null)}" ${node === selected ? 'aria-current="location"' : ""}
      style="--progress-x:${x}%;--progress-y:${y}%;${progressColor(node.coverage)}">
      <strong>${escapeHTML(node.name)}</strong>
      <div class="progress-node-meta"><span>${node.mastered} / ${node.total} освоено</span><span>${node.coverage}%</span></div>
      <span class="progress-track-fill" aria-hidden="true"></span>
    </a>`).join("")}
  </div>`;
}

function progressDetail(data, topic, skill) {
  if (!skill) {
    const counts = topic ?? data.totals;
    return `<aside class="progress-detail" aria-labelledby="progress-detail-title">
      <h2 id="progress-detail-title" tabindex="-1">${topic ? "О направлении" : "Твоя практика"}</h2>
      ${topic ? `<p>${escapeHTML(topic.description)}.</p>` : ""}
      <dl class="progress-metrics">
        <div><dt>Попробовал</dt><dd>${counts.attempted}</dd></div>
        <div><dt>Освоил</dt><dd>${counts.mastered}</dd></div>
        <div><dt>Осталось освоить</dt><dd>${counts.total - counts.mastered}</dd></div>
      </dl>
      <p class="progress-rule">Вопрос засчитывается при лучшей AI-оценке от ${data.mastery_score} из 100. Цвет направления учитывает долю освоенных вопросов в каждой подтеме.</p>
    </aside>`;
  }

  return `<aside class="progress-detail" aria-labelledby="progress-detail-title" style="${progressColor(skill.coverage)}">
    <div class="progress-detail-heading"><h2 id="progress-detail-title" tabindex="-1">${escapeHTML(skill.name)}</h2><span>${skill.coverage}%</span></div>
    <span class="progress-track-fill" aria-hidden="true"></span>
    <p class="progress-detail-count">${skill.mastered} из ${skill.total} освоено</p>
    <p>${escapeHTML(skill.summary)}</p>
    ${skill.branches.map(({ name, text }) => `<section class="progress-reading"><h3>${escapeHTML(name)}</h3><p>${escapeHTML(text)}</p></section>`).join("")}
    <details class="progress-questions">
      <summary>Вопросы · ${skill.total}</summary>
      <ul>${skill.questions.map((question) => progressQuestion(question, data.mastery_score)).join("")}</ul>
    </details>
    <button id="progress-practice" class="button primary" type="button">Тренировать подтему ${icon("arrow")}</button>
  </aside>`;
}

function progressQuestion(question, threshold) {
  const mastered = question.best_score !== null && question.best_score >= threshold;
  const status = question.best_score !== null ? `${question.best_score} / 100` : question.attempted ? "Есть попытка" : "Без ответа";
  return `<li><div><strong>${escapeHTML(question.title)}</strong><small>${escapeHTML(question.level)}</small></div>
    <span class="progress-question-status${mastered ? " mastered" : ""}">${status}</span></li>`;
}
