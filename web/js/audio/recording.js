"use strict";

function releaseMicrophone() {
  clearTimeout(state.recordingTimer);
  state.stream?.getTracks().forEach((track) => track.stop());
  state.stream = null;
}

function discardRecording() {
  if (state.recorder && state.recorder.state !== "inactive") {
    state.recorder.onstop = null;
    state.recorder.stop();
  }
  releaseMicrophone();
  state.recorder = null;
}

async function record() {
  if (live.running) return;
  if (state.busy) return;
  if (state.recorder?.state === "recording") { state.recorder.stop(); return; }
  if (!speechRecognitionReady()) { toast("Для голосового ввода добавь DEEPGRAM_API_KEY или OPENAI_API_KEY в .env; инструкция — в «Подключениях»."); return; }
  if (!navigator.mediaDevices?.getUserMedia || !("MediaRecorder" in window)) { toast(isDesktop() ? "Запись недоступна. Обнови Microsoft Edge WebView2 Runtime." : "Этот браузер не поддерживает запись. Открой приложение в Edge или Chrome."); return; }
  cancelSpeech();
  const sessionId = state.session.id;
  const questionId = state.session.question.id;
  const button = $("#record-button");
  button.disabled = true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    if (state.page !== "training" || state.session?.id !== sessionId || state.session?.question?.id !== questionId) { stream.getTracks().forEach((track) => track.stop()); return; }
    state.stream = stream;
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    state.recorder = recorder;
    const chunks = [];
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    recorder.onerror = () => { discardRecording(); toast("Не удалось записать звук. Проверь микрофон."); renderTraining(); };
    recorder.onstop = async () => {
      releaseMicrophone();
      state.recorder = null;
      state.busy = true;
      syncTrainerAvatar();
      button.disabled = true;
      const cleanupReady = state.config.transcription?.ready ?? state.config.ai;
      button.innerHTML = `${icon("mic")} ${cleanupReady ? "Распознаю и очищаю…" : "Распознаю…"}`;
      button.classList.remove("recording");
      if ($("#activity-label")) $("#activity-label").textContent = cleanupReady ? "Распознаю и очищаю…" : "Распознаю…";
      if ($("#submit-answer")) $("#submit-answer").disabled = true;
      const form = new FormData();
      form.append("audio", new Blob(chunks, { type: recorder.mimeType }), "answer.webm");
      form.append("session_id", sessionId);
      form.append("question_id", String(questionId));
      try {
        const result = await api("/transcribe", { method: "POST", body: form });
        if (state.page !== "training" || state.session?.id !== sessionId || state.session?.question?.id !== questionId) return;
        const providerNote = result.provider === "whisper" ? "Использован Whisper. " : "";
        const field = $("#answer-input");
        field.value = [field.value.trim(), result.text].filter(Boolean).join(" ").slice(0, 12000);
        storage.set(draftKey(), field.value);
        showTranscriptOriginal(result, field);
        if (!result.text.trim()) toast("Речь не обнаружена. Попробуй ещё раз или напиши ответ.");
        else if (result.cleanup === "unavailable") toast(providerNote + "Речь распознана, но очистка недоступна. В поле исходный текст — проверь его перед отправкой.");
        else toast(providerNote + (state.session.reviewing ? "Сообщение распознано. Проверь текст и нажми «Отправить»." : "Ответ распознан. Проверь текст и нажми «Проверить ответ»."));
      } catch (error) { toast(error.message); }
      finally {
        state.busy = false;
        syncTrainerAvatar();
        if ($("#record-button")) { $("#record-button").disabled = false; $("#record-button").innerHTML = `${icon("mic")} Ответить голосом`; }
        if ($("#submit-answer")) $("#submit-answer").disabled = false;
        if ($("#activity-label")) $("#activity-label").textContent = "Твой ход";
      }
    };
    recorder.start(1000);
    syncTrainerAvatar();
    button.classList.add("recording");
    button.innerHTML = `${icon("stop")} Закончить запись`;
    $("#submit-answer").disabled = true;
    $("#activity-label").textContent = "Слушаю…";
    state.recordingTimer = setTimeout(() => { if (recorder.state === "recording") recorder.stop(); }, 120000);
  } catch (error) {
    releaseMicrophone();
    toast(error.name === "NotAllowedError" ? (isDesktop() ? "Разреши доступ к микрофону в приложении и параметрах конфиденциальности Windows или ответь текстом." : "Разреши доступ к микрофону в настройках браузера или ответь текстом.") : "Микрофон недоступен. Проверь подключение устройства.");
  } finally { button.disabled = false; }
}


function showTranscriptOriginal(result, field) {
  $("#transcription-review")?.remove();
  if (result.cleanup === "applied" && result.raw_text !== result.text) {
    field.insertAdjacentHTML("afterend", `<details class="transcription-review" id="transcription-review"><summary>Исходная расшифровка последней записи</summary><p>${escapeHTML(result.raw_text)}</p></details>`);
  }
}

