"use strict";

function updateLiveUI() {
  syncTrainerAvatar();
  const panel = $("#live-panel");
  if (!panel) return;
  const key = `${live.enabled}:${live.paused}`;
  if (panel.dataset.mode !== key) {
    panel.dataset.mode = key;
    panel.innerHTML = live.enabled
      ? `<div class="live-heading"><span class="live-badge">● LIVE TRAINING</span><div class="live-actions"><button class="button small" data-action="${live.paused ? "live-resume" : "live-pause"}">${live.paused ? "Продолжить" : "Пауза"}</button><button class="text-button" data-action="live-manual">Обычный режим</button><button class="text-button" data-action="live-finish">Завершить</button></div></div><p class="live-status" role="status" aria-live="polite"></p><div class="live-meter" aria-hidden="true"><i></i></div><small>Команды: «повтори вопрос», «следующий вопрос», «пауза», «заверши тренировку». После разбора — 6 секунд на уточнение.</small>`
      : `<div class="live-heading"><div><strong>Голосовой диалог</strong><p>Слушай вопросы и отвечай без кнопок.</p></div><button class="button small" data-action="live-start">Включить</button></div>`;
  }
  if (live.enabled) {
    const status = panel.querySelector(".live-status");
    if (status.textContent !== live.message) status.textContent = live.message;
    panel.querySelector(".live-meter i").style.width = `${Math.round(live.level * 100)}%`;
    panel.dataset.phase = live.phase;
  }
  const resume = panel.querySelector('[data-action="live-resume"]');
  if (resume) resume.disabled = state.busy;
  const start = panel.querySelector('[data-action="live-start"]');
  if (start) start.disabled = state.busy;
  const locked = live.running || state.busy;
  for (const selector of ["#record-button", "#submit-answer", "#next-question", '[data-action="skip"]']) {
    if ($(selector)) $(selector).disabled = locked;
  }
  if ($("#answer-input")) $("#answer-input").readOnly = live.running;
}

