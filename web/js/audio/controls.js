"use strict";

function syncVoiceControls() {
  const percent = Math.round(state.volume * 100);
  $("#voice-volume").value = percent;
  $("#voice-volume").style.setProperty("--volume", `${percent}%`);
  $("#voice-volume-output").textContent = `${percent}%`;
  $("#voice-volume-summary").textContent = `${percent}%`;
  $("#auto-speech").checked = state.sound;
  $("#voice-tone").value = state.tone;
  const fish = state.config?.tts?.provider === "fish";
  $("#voice-tone").disabled = !fish;
  $(".voice-tone-preview").disabled = !fish || !state.config.tts.ready;
  $("#voice-tone-hint").textContent = fish ? "Подача следующей фразы. Сила эффекта зависит от голоса и текста." : "Выбор интонации доступен для голоса Fish Audio.";
  const toggle = $('[data-action="toggle-sound"]');
  if (toggle) {
    toggle.classList.toggle("off", !state.sound);
    toggle.setAttribute("aria-pressed", String(state.sound));
    toggle.setAttribute("aria-label", state.sound ? "Выключить автоозвучку" : "Включить автоозвучку");
    toggle.title = state.sound ? "Выключить автоозвучку" : "Включить автоозвучку";
  }
}

function setVolume(percent) {
  const value = Number(percent);
  if (!Number.isFinite(value)) return;
  state.volume = Math.max(0, Math.min(100, value)) / 100;
  if (state.volume === 0 && live.running) live.pause("Громкость 0%. Увеличь громкость и нажми «Продолжить».");
  storage.set("ml-voice-volume", String(Math.round(state.volume * 100)));
  if (speech.audio) speech.audio.volume = state.volume;
  if (speech.utterance) speech.utterance.volume = state.volume;
  syncVoiceControls();
}

function setAutoSpeech(enabled) {
  state.sound = Boolean(enabled);
  if (!enabled && live.running) live.pause("Автоозвучка выключена. Live Training на паузе.");
  storage.set("ml-auto-speech", state.sound ? "on" : "off");
  if (!state.sound) cancelSpeech();
  syncVoiceControls();
}

$("#voice-volume").addEventListener("input", (event) => setVolume(event.target.value));
$("#auto-speech").addEventListener("change", (event) => setAutoSpeech(event.target.checked));
$("#voice-tone").addEventListener("change", (event) => {
  if (!voiceTones.has(event.target.value)) return;
  state.tone = event.target.value;
  storage.set("ml-voice-tone", state.tone);
  cancelSpeech();
  syncVoiceControls();
});
document.addEventListener("click", (event) => { if (!event.target.closest("#voice-controls")) $("#voice-controls").open = false; });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && $("#voice-controls").open) { $("#voice-controls").open = false; $("#voice-controls summary").focus(); } });
syncVoiceControls();

