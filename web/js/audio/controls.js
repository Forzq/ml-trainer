"use strict";

function syncVoiceControls() {
  const percent = Math.round(state.volume * 100);
  const volume = settingsPage.querySelector("#voice-volume");
  volume.value = percent;
  volume.style.setProperty("--volume", `${percent}%`);
  settingsPage.querySelector("#voice-volume-output").textContent = `${percent}%`;
  settingsPage.querySelector("#auto-speech").checked = state.sound;
  settingsPage.querySelector("#voice-tone").value = state.tone;
  const fish = state.config?.tts?.provider === "fish";
  settingsPage.querySelector("#voice-choice").hidden = !fish;
  settingsPage.querySelector("#trainer-voice").value = state.voice;
  settingsPage.querySelector("#voice-tone-field").hidden = !fish;
  settingsPage.querySelector(".voice-preview").disabled = !(fish ? state.config.tts.ready : "speechSynthesis" in window);
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

settingsPage.querySelector("#voice-volume").addEventListener("input", (event) => setVolume(event.target.value));
settingsPage.querySelector("#auto-speech").addEventListener("change", (event) => setAutoSpeech(event.target.checked));
settingsPage.querySelector("#trainer-voice").addEventListener("change", (event) => {
  if (state.busy || state.recorder?.state === "recording") {
    event.target.value = state.voice;
    toast("Закончи запись или дождись ответа, чтобы сменить голос.");
    return;
  }
  const voice = event.target.value;
  if (voice !== "female" && voice !== "male") return;
  if (live.running) live.pause("Голос изменён. Нажми «Продолжить», чтобы вернуться к тренировке.");
  else cancelSpeech();
  state.voice = voice;
  storage.set("ml-trainer-voice", voice);
  syncTrainerAvatar();
});
settingsPage.querySelector("#voice-tone").addEventListener("change", (event) => {
  if (!voiceTones.has(event.target.value)) return;
  state.tone = event.target.value;
  storage.set("ml-voice-tone", state.tone);
  cancelSpeech();
  syncVoiceControls();
});
syncVoiceControls();

