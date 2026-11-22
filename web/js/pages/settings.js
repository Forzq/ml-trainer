"use strict";

const settingsPage = $("#settings-template").content.firstElementChild;
let settingsSection = "";

function openSettings(section = "") {
  if (state.page === "settings") {
    if (section) settingsPage.querySelector(`#settings-${section}`)?.focus();
    return;
  }
  settingsSection = section;
  location.hash = "settings";
}

function renderSettings() {
  const config = state.config;
  const fish = config.tts?.provider === "fish";
  const speechReady = fish ? config.tts.ready : "speechSynthesis" in window;
  settingsPage.querySelector("#connection-settings").innerHTML = settingsHTML(config, { fish, speechReady });
  settingsPage.querySelector("#settings-resume").hidden = !state.session || state.session.completed;
  setPage(settingsPage, "Настройки");
  speechStatus(speech.status);
  if (settingsSection) {
    settingsPage.querySelector(`#settings-${settingsSection}`)?.focus();
    settingsSection = "";
  } else {
    window.scrollTo({ top: 0, behavior: "instant" });
  }
}

function bindLiveSettings() {
  for (const [id, currentValue, apply] of [
    ["live-silence", live.timing.silenceMs, (value) => { live.timing.silenceMs = value; }],
    ["live-sensitivity", live.threshold, (value) => { live.threshold = value; }],
  ]) {
    const field = settingsPage.querySelector(`#${id}`);
    const key = `ml-${id}`;
    const saved = storage.get(key);
    field.value = Array.from(field.options).some((option) => option.value === saved) ? saved : String(currentValue);
    apply(Number(field.value));
    field.addEventListener("change", () => {
      apply(Number(field.value));
      storage.set(key, field.value);
    });
  }
}

