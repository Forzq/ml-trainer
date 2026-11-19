"use strict";

function showSettings() {
  if (live.running) live.pause("Настройки открыты. Нажми «Продолжить», чтобы вернуться к Live Training.");
  const config = state.config;
  const fish = config.tts?.provider === "fish";
  const speechReady = fish ? config.tts.ready : "speechSynthesis" in window;
  $("#settings-content").innerHTML = settingsHTML(config, { fish, speechReady });
  if (!$("#settings-dialog").open) $("#settings-dialog").showModal();
  speechStatus(speech.status);
}

