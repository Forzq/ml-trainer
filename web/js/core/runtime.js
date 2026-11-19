"use strict";

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

