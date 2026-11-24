"use strict";

const byId = (id) => document.getElementById(id);
const signIn = byId("sign-in");
const dashboard = byId("dashboard");
const loginForm = byId("login");
const number = new Intl.NumberFormat("ru");
const usd = new Intl.NumberFormat("ru", { style: "currency", currency: "USD" });
const date = new Intl.DateTimeFormat("ru", { dateStyle: "medium", timeStyle: "short" });
let accounts = [];
let busy = false;

async function adminApi(path, method = "GET", data) {
  const response = await fetch("/api/admin/" + path, {
    method,
    headers: { "Content-Type": "application/json", "X-Mockroom-Client": "web" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof result.detail === "string" ? result.detail : "Не удалось выполнить запрос.");
    error.status = response.status;
    throw error;
  }
  return result;
}

function message(id, text, error = false) {
  const node = byId(id);
  node.textContent = text;
  node.hidden = !text;
  node.classList.toggle("error", error);
}

function showLogin() {
  accounts = [];
  byId("accounts").replaceChildren();
  dashboard.hidden = true;
  signIn.hidden = false;
  loginForm.reset();
  loginForm.elements.login.focus();
}

function renderAccounts() {
  const query = byId("search").value.trim().toLowerCase();
  const rows = document.createDocumentFragment();
  const matching = accounts.filter(({ label, display_name, id }) =>
    [label, display_name, id].some((value) => value?.toLowerCase().includes(query)));
  for (const account of matching) {
    const row = byId("account-row").content.cloneNode(true);
    const find = (name) => row.querySelector(name);
    const name = account.display_name || account.label || "Без имени";
    find(".account-name").textContent = name;
    const label = find(".account-label");
    label.hidden = !account.display_name || !account.label || account.label === name;
    label.textContent = account.label;
    const state = account.active ? (account.limit === 0 ? "На паузе" : "Активен") : "Отключён";
    find(".account-state").textContent = state + " · " + (account.custom ? "своя квота" : "по умолчанию");
    find(".account-id").textContent = account.id;
    find(".account-used").textContent = number.format(account.used);
    find(".account-remaining").textContent = number.format(account.remaining);
    const form = find("form");
    form.dataset.account = account.id;
    form.elements.maximum.value = account.limit;
    form.elements.maximum.setAttribute("aria-label", "Квота участника " + name);
    form.elements.reset.hidden = !account.custom;
    rows.append(row);
  }
  byId("accounts").replaceChildren(rows);
  byId("empty").hidden = matching.length > 0;
}

function render(data) {
  signIn.hidden = true;
  dashboard.hidden = false;
  accounts = data.accounts;
  renderAccounts();
  byId("global-remaining").textContent = number.format(data.global.remaining);
  byId("global-usage").textContent = "Осталось · использовано " + number.format(data.global.used) + " из " +
    number.format(data.global.limit);
  byId("default-amount").textContent = number.format(data.default_limit);
  byId("global-limit").elements.maximum.value = data.global.limit;
  byId("default-limit").elements.maximum.value = data.default_limit;
  byId("updated").textContent = "Обновлено " + date.format(new Date()) + " · сброс " +
    date.format(new Date(data.reset_at * 1000));
  byId("release").textContent = data.build.version;
  byId("build-id").textContent = data.build.id ?? "—";
  byId("commit").textContent = data.build.commit
    ? data.build.commit.slice(0, 12) + (data.build.dirty ? " + изменения" : "") : "—";
  byId("built-at").textContent = data.build.built_at ? date.format(new Date(data.build.built_at)) : "—";
}

async function refreshBudget() {
  byId("key-status").textContent = "Загрузка бюджета…";
  try {
    const budget = await adminApi("openrouter");
    if (!budget.available) {
      byId("key-remaining").textContent = "—";
      byId("key-status").textContent = budget.reason === "not_configured"
        ? "Ключ OpenRouter не настроен." : "Данные временно недоступны.";
      return;
    }
    byId("key-remaining").textContent = budget.limit_remaining == null ? "—" : usd.format(budget.limit_remaining);
    const period = { daily: "Суточный лимит", weekly: "Недельный лимит", monthly: "Месячный лимит" };
    const cap = budget.limit == null ? "Ключ без лимита" :
      (period[budget.limit_reset] || "Лимит без сброса") + " " + usd.format(budget.limit);
    const today = budget.usage_daily == null ? "" : " · сегодня " + usd.format(budget.usage_daily);
    byId("key-status").textContent = cap + today;
  } catch {
    byId("key-remaining").textContent = "—";
    byId("key-status").textContent = "Данные временно недоступны.";
  }
}

async function action(button, operation) {
  if (busy) return;
  busy = true;
  button.disabled = true;
  message("status", "");
  try {
    await operation();
  } catch (error) {
    if (error.status === 401) showLogin();
    message(dashboard.hidden ? "login-error" : "status", error.message, true);
  } finally {
    busy = false;
    button.disabled = false;
  }
}

async function refresh() {
  render(await adminApi("usage"));
  void refreshBudget();
}

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  message("login-error", "");
  const credentials = Object.fromEntries(new FormData(loginForm));
  void action(loginForm.querySelector("button"), async () => {
    try {
      await adminApi("login", "POST", credentials);
    } finally {
      loginForm.elements.password.value = "";
    }
    await refresh();
  });
});

byId("refresh").addEventListener("click", (event) => void action(event.currentTarget, refresh));
byId("logout").addEventListener("click", (event) => void action(event.currentTarget, async () => {
  await adminApi("logout", "POST");
  message("login-error", "");
  showLogin();
}));
byId("search").addEventListener("input", renderAccounts);

function saveLimit(form, maximum, button) {
  return action(button, async () => {
    const data = await adminApi("limits", "PUT", {
      target: form.dataset.target,
      account_id: form.dataset.account || null,
      maximum,
    });
    render(data);
    message("status", maximum === null ? "Квота сброшена." : "Квота сохранена.");
  });
}

dashboard.addEventListener("submit", (event) => {
  const form = event.target;
  if (!form.dataset.target) return;
  event.preventDefault();
  void saveLimit(form, form.elements.maximum.value, form.querySelector("button[type=submit]"));
});
dashboard.addEventListener("click", (event) => {
  const button = event.target.closest("button[name=reset]");
  if (button) void saveLimit(button.form, null, button);
});

refresh().catch((error) => {
  showLogin();
  if (error.status !== 401) message("login-error", error.message, true);
});
