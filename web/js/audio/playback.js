"use strict";

function speechStatus(status) {
  speech.status = status;
  syncTrainerAvatar();
  const indicator = $("#speech-indicator");
  indicator.hidden = status === "idle";
  indicator.innerHTML = `${status === "loading" ? '<span class="spinner"></span>' : icon("sound")}<span>${status === "loading" ? "Готовлю голос…" : "Озвучиваю"}</span>${icon("close")}`;
  const preview = $(".voice-preview");
  if (preview && !preview.disabled) {
    preview.innerHTML = `${icon(status === "idle" ? "sound" : "stop")} ${status === "idle" ? "Послушать голос" : "Остановить озвучку"}`;
    preview.dataset.action = status === "idle" ? "preview-voice" : "stop-preview";
  }
}

function cancelSpeech(completed = false) {
  trainerAvatar.stopAudio();
  speech.resolve?.(completed === true);
  speech.resolve = null;
  speech.version += 1;
  speech.controller?.abort();
  speech.controller = null;
  speech.reader?.cancel().catch(() => {});
  speech.reader = null;
  speech.receiving = false;
  if (speech.audio) { speech.audio.onplaying = null; speech.audio.onended = null; speech.audio.onerror = null; speech.audio.pause(); speech.audio.removeAttribute("src"); speech.audio.load(); }
  speech.audio = null;
  speech.utterance = null;
  if (speech.objectUrl) URL.revokeObjectURL(speech.objectUrl);
  speech.objectUrl = null;
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  speechStatus("idle");
}

function waitForAudioEvent(target, name, signal, action = () => {}) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      target.removeEventListener(name, done);
      target.removeEventListener("error", failed);
      signal.removeEventListener("abort", aborted);
    };
    const done = () => { cleanup(); resolve(); };
    const failed = () => { cleanup(); reject(new Error("Не удалось воспроизвести поток озвучки. Попробуй повторить.")); };
    const aborted = () => { cleanup(); reject(new DOMException("Speech cancelled", "AbortError")); };
    if (signal.aborted) { aborted(); return; }
    target.addEventListener(name, done, { once: true });
    target.addEventListener("error", failed, { once: true });
    signal.addEventListener("abort", aborted, { once: true });
    try { action(); } catch (error) { cleanup(); reject(error); }
  });
}

function speechAudio(source, version) {
  speech.objectUrl = URL.createObjectURL(source);
  const audio = new Audio(speech.objectUrl);
  audio.volume = state.volume;
  speech.audio = audio;
  trainerAvatar.attachAudio(audio);
  audio.onplaying = () => { if (speech.version === version) speechStatus("playing"); };
  audio.onended = () => { if (speech.version === version) cancelSpeech(true); };
  audio.onerror = () => { if (speech.version === version) { cancelSpeech(); toast("Не удалось воспроизвести запись. Можно повторить озвучку рядом с сообщением."); } };
  return audio;
}

async function playSpeechStream(response, version, signal) {
  const source = new MediaSource();
  const opened = waitForAudioEvent(source, "sourceopen", signal);
  const audio = speechAudio(source, version);
  await opened;
  const buffer = source.addSourceBuffer("audio/mpeg");
  const reader = response.body.getReader();
  speech.reader = reader;
  speech.receiving = true;
  let started = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (signal.aborted) throw new DOMException("Speech cancelled", "AbortError");
      if (done) break;
      if (!value.length) continue;
      await waitForAudioEvent(buffer, "updateend", signal, () => buffer.appendBuffer(value));
      if (!started) {
        started = true;
        // Keep receiving data while play() waits for enough MP3 frames to start.
        audio.play().catch((error) => {
          if (speech.version !== version) return;
          cancelSpeech();
          toast(error.name === "NotAllowedError" ? "Нажми кнопку динамика рядом с сообщением, чтобы включить воспроизведение." : "Не удалось запустить озвучку. Попробуй повторить.");
        });
      }
    }
    if (!started) throw new Error("Сервис озвучки вернул пустую запись.");
    if (source.readyState === "open") source.endOfStream();
  } finally {
    reader.releaseLock();
    if (speech.version === version) { speech.reader = null; speech.receiving = false; }
  }
}

async function speak(text, { force = false } = {}) {
  if ((!state.sound && !force) || state.recorder?.state === "recording") return;
  if (state.volume === 0) { if (force) toast("Громкость голоса — 0%. Увеличь её в разделе «Настройки» слева."); return; }
  cancelSpeech();
  speech.completion = new Promise((resolve) => { speech.resolve = resolve; });
  if (state.config?.tts?.provider === "fish") {
    if (!state.config.tts.ready) { cancelSpeech(); toast("Для голоса Fish Audio добавь FISH_AUDIO_API_KEY в .env и перезапусти приложение."); return; }
    const version = speech.version;
    const controller = new AbortController();
    speech.controller = controller;
    speechStatus("loading");
    try {
      const response = await fetch("/api/speech", {
        method: "POST", signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-Mockroom-Client": "web", "X-App-Token": state.config.token },
        body: JSON.stringify({ text, tone: state.tone, voice: trainerVoice(), stream: true }),
      });
      if (!response.ok) {
        const result = await response.json();
        throw new Error(typeof result.detail === "string" ? result.detail : "Не удалось озвучить сообщение.");
      }
      if (speech.version !== version) return;
      if (response.body && response.headers.get("Content-Type")?.split(";")[0] === "audio/mpeg"
          && window.MediaSource?.isTypeSupported("audio/mpeg")) {
        await playSpeechStream(response, version, controller.signal);
        return;
      }
      const blob = await response.blob();
      if (speech.version !== version) return;
      if (!blob.size || !blob.type.startsWith("audio/")) throw new Error("Сервис озвучки вернул некорректную запись.");
      const audio = speechAudio(blob, version);
      await audio.play();
      if (speech.version === version) speechStatus("playing");
    } catch (error) {
      if (speech.version !== version || error.name === "AbortError") return;
      cancelSpeech();
      toast(error.name === "NotAllowedError" ? "Нажми кнопку динамика рядом с сообщением, чтобы включить воспроизведение." : error.message);
    }
    return;
  }
  if (!("speechSynthesis" in window)) { cancelSpeech(); toast("Системная озвучка недоступна."); return; }
  const version = speech.version;
  const utterance = new SpeechSynthesisUtterance(text);
  speech.utterance = utterance;
  utterance.volume = state.volume;
  utterance.lang = "ru-RU";
  utterance.rate = 1;
  const voice = speechSynthesis.getVoices().find((item) => item.lang.toLowerCase().startsWith("ru"));
  if (voice) utterance.voice = voice;
  utterance.onstart = () => { if (speech.version === version) speechStatus("playing"); };
  utterance.onend = () => { if (speech.version === version) cancelSpeech(true); };
  utterance.onerror = (event) => { if (speech.version === version) { cancelSpeech(); if (!["canceled", "interrupted"].includes(event.error)) toast("Озвучка недоступна. Тот же текст есть в чате."); } };
  speechSynthesis.speak(utterance);
}

