"use strict";

async function api(path, options = {}) {
  const headers = { "X-Mockroom-Client": "web", "X-App-Token": state.config?.token || "", ...options.headers };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (response.status === 401 && (path === "/config" || state.config?.beta)) showBetaLogin();
  if (state.config?.beta && (path === "/transcribe" || /\/sessions\/[^/]+\/(answer|discuss)$/.test(path)
      || (state.config.semantic && path.startsWith("/cards?") && new URLSearchParams(path.split("?")[1]).get("q")))) {
    void refreshBetaQuota();
  }
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    const error = new Error(typeof result.detail === "string" ? result.detail : "Не удалось выполнить запрос. Попробуй ещё раз.");
    error.status = response.status;
    throw error;
  }
  return await response.json();
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
  const content = $("#app-content");
  if (typeof html === "string") content.innerHTML = html;
  else content.replaceChildren(html);
  $("#page-label").textContent = label;
  document.querySelectorAll(".nav-link[data-page]").forEach((link) => {
    const active = link.dataset.page === state.page;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  syncVoiceControls();
}

