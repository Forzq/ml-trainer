"use strict";

// Local energy endpointing: no audio is sent until a complete turn is recorded.
class SpeechGate {
  constructor({ threshold = 0.012, silenceMs = 3000, waitMs = 25000, maxMs = 120000 } = {}) {
    Object.assign(this, { threshold, silenceMs, waitMs, maxMs });
    this.started = null;
    this.last = null;
    this.loudSince = null;
    this.heard = false;
  }
  sample(rms, now) {
    if (this.started === null) this.started = now;
    if (rms >= this.threshold) {
      if (this.loudSince === null) this.loudSince = now;
      if (now - this.loudSince >= 150) this.heard = true;
      this.last = now;
    } else {
      this.loudSince = null;
    }
    if (this.heard && now - this.last >= this.silenceMs) return "speech";
    if (now - this.started >= this.maxMs) return this.heard ? "speech" : "empty";
    if (!this.heard && this.loudSince === null && now - this.started >= this.waitMs) return "empty";
    return null;
  }
}

function liveCommand(text) {
  const normalized = text.toLowerCase().replace(/ё/g, "е").replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\bplease\b/g, "").replace(/пожалуйста/g, "").replace(/\s+/g, " ").trim();
  const groups = {
    pause: ["пауза", "стоп", "поставь на паузу", "останови тренировку"],
    finish: ["заверши тренировку", "закончить тренировку", "завершить тренировку"],
    next: ["следующий вопрос", "дальше", "далее", "перейдем дальше"],
    skip: ["не знаю", "пропустить вопрос", "пропускаю вопрос"],
    question: ["повтори вопрос", "повторить вопрос"],
    repeat: ["повтори", "повтори ответ", "повтори разбор"],
  };
  return Object.keys(groups).find((key) => groups[key].includes(normalized)) || null;
}

class LiveTraining {
  constructor(hooks) {
    this.hooks = hooks;
    this.enabled = false;
    this.paused = false;
    this.version = 0;
    this.phase = "idle";
    this.message = "";
    this.level = 0;
    this.context = null;
    this.cancelCapture = null;
    this.task = null;
    this.lastSpeech = "";
    this.timing = { silenceMs: 3000, followupMs: 6000, answerWaitMs: 25000, maxMs: 120000, tailMs: 350 };
    this.threshold = 0.012;
  }
  get running() { return this.enabled && !this.paused; }
  current(token) { return this.running && this.version === token && this.hooks.session()?.id === this.sessionId; }
  status(phase, message) {
    this.phase = phase;
    this.message = message;
    this.hooks.update();
  }
  async prepare() {
    this.hooks.checkReady();
    const AudioContextType = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextType) throw new Error("Live Training требует поддержку Web Audio. Обнови WebView2 Runtime.");
    if (!this.context || this.context.state === "closed") this.context = new AudioContextType();
    const context = this.context;
    await context.resume();
    const stream = await navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: true, noiseSuppression: true, autoGainControl: true,
    } });
    stream.getTracks().forEach((track) => track.stop());
    if (context !== this.context || context.state !== "running") throw new Error("Не удалось запустить обработку микрофона. Попробуй включить Live Training ещё раз.");
  }
  release() {
    this.cancelCapture?.();
    this.cancelCapture = null;
    const context = this.context;
    this.context = null;
    if (context && context.state !== "closed") context.close().catch(() => {});
    this.level = 0;
  }
  pause(message = "Пауза. Микрофон выключен. Нажми «Продолжить», когда будешь готов.") {
    this.version += 1;
    this.enabled = true;
    this.paused = true;
    this.release();
    this.hooks.cancelSpeech();
    this.status("paused", message);
  }
  stop() {
    this.version += 1;
    this.enabled = false;
    this.paused = false;
    this.release();
    this.hooks.cancelSpeech();
    this.status("idle", "");
  }
  async start({ prepared = false } = {}) {
    if (this.running || this.hooks.busy()) return;
    if (!this.hooks.session()?.question) throw new Error("Сначала начни тренировку.");
    this.hooks.checkReady();
    const token = ++this.version;
    this.sessionId = this.hooks.session().id;
    this.enabled = true;
    this.paused = false;
    this.status("preparing", "Подготавливаю микрофон…");
    try {
      if (!prepared || this.context?.state !== "running") await this.prepare();
      if (!this.current(token)) return;
      this.task = this.run(token).catch((error) => {
        if (this.current(token)) this.pause(error.message + " Микрофон выключен; текст ответа сохранён, если он уже распознан.");
      });
    } catch (error) {
      if (this.current(token)) this.pause(error.name === "NotAllowedError"
        ? "Разреши доступ к микрофону и нажми «Продолжить»."
        : error.message);
    }
  }
  async say(text, token) {
    this.lastSpeech = text;
    this.status("speaking", "Тренер говорит. Микрофон выключен.");
    const completed = await this.hooks.say(text);
    if (!this.current(token)) return false;
    if (!completed) throw new Error("Озвучка не завершилась. Проверь голос и громкость.");
    await new Promise((resolve) => setTimeout(resolve, this.timing.tailMs));
    return this.current(token);
  }
  async listen(token, followup) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: true, noiseSuppression: true, autoGainControl: true,
    } });
    if (!this.current(token)) { stream.getTracks().forEach((track) => track.stop()); return { reason: "cancelled" }; }
    let source, analyser, recorder;
    try {
      source = this.context.createMediaStreamSource(stream);
      analyser = this.context.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    } catch (error) {
      source?.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      throw error;
    }
    const gate = new SpeechGate({ threshold: this.threshold, silenceMs: this.timing.silenceMs,
      waitMs: followup ? this.timing.followupMs : this.timing.answerWaitMs, maxMs: this.timing.maxMs });
    const values = new Float32Array(analyser.fftSize);
    this.status(followup ? "followup" : "listening", followup
      ? "Есть уточнение? Говори сейчас. Если промолчишь, перейду к следующему вопросу."
      : "Слушаю ответ. Пауза в речи завершит запись автоматически.");
    return new Promise((resolve, reject) => {
      const chunks = [];
      let timer, stopping = false, reason;
      const cleanup = () => {
        clearInterval(timer);
        source.disconnect();
        stream.getTracks().forEach((track) => track.stop());
        this.level = 0;
        if (this.cancelCapture === cancel) this.cancelCapture = null;
      };
      const finish = (why) => {
        if (stopping) return;
        stopping = true;
        reason = why;
        if (recorder.state !== "inactive") { recorder.stop(); cleanup(); }
        else { cleanup(); resolve({ reason }); }
      };
      const cancel = () => finish("cancelled");
      this.cancelCapture = cancel;
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        cleanup();
        resolve({ reason: reason || "device-ended", blob: new Blob(chunks, { type: recorder.mimeType }) });
      };
      recorder.onerror = () => { cleanup(); reject(new Error("Не удалось записать ответ. Проверь микрофон.")); };
      try {
        recorder.start(250);
        timer = setInterval(() => {
          if (!this.current(token)) { finish("cancelled"); return; }
          analyser.getFloatTimeDomainData(values);
          const rms = Math.sqrt(values.reduce((sum, value) => sum + value * value, 0) / values.length);
          this.level = Math.min(1, rms / Math.max(this.threshold * 4, 0.05));
          const end = gate.sample(rms, performance.now());
          this.hooks.update();
          if (end) finish(end);
        }, 50);
      } catch (error) { cleanup(); reject(error); }
    });
  }
  async run(token) {
    let narrate = true;
    while (this.current(token)) {
      const session = this.hooks.session();
      if (session.completed) { this.stop(); return; }
      const attempt = session.attempts.find((item) => item.question.id === session.question.id);
      if (narrate) {
        const text = session.reviewing
          ? attempt.discussion?.at(-1)?.reply || attempt.feedback
          : session.question.question;
        if (!await this.say(text, token)) return;
      }
      const capture = await this.listen(token, session.reviewing);
      if (!this.current(token) || capture.reason === "cancelled") return;
      if (capture.reason === "device-ended") throw new Error("Микрофон отключился во время записи. Проверь устройство.");
      if (capture.reason === "empty") {
        if (!session.reviewing) { this.pause("Не услышал начало ответа. Проверь микрофон и нажми «Продолжить»; вопрос не пропущен."); return; }
        this.status("advancing", "Перехожу к следующему вопросу…");
        await this.hooks.next();
        narrate = true;
        continue;
      }
      this.status("transcribing", "Распознаю и очищаю твою реплику…");
      const result = await this.hooks.transcribe(capture.blob);
      // Preserve a late transcript on pause, but never submit it after cancellation.
      const command = liveCommand(result.text);
      let answer = result.text;
      if (!command) answer = this.hooks.acceptTranscript(result, session);
      if (!this.current(token)) return;
      if (!result.text.trim()) { this.pause("Не удалось разобрать речь. Ответ не отправлен; попробуй ещё раз или ответь текстом."); return; }
      if (command === "pause") { this.pause(); return; }
      if (command === "finish") { this.stop(); await this.hooks.finish(); return; }
      if (result.cleanup === "unavailable") { this.pause("Очистка расшифровки недоступна. Проверь исходный текст в поле перед отправкой."); return; }
      if (command === "question" || command === "repeat") {
        if (!await this.say(command === "question" ? session.question.question : this.lastSpeech, token)) return;
        narrate = false;
        continue;
      }
      if ((command === "next" || command === "skip") && session.reviewing) {
        this.status("advancing", "Перехожу к следующему вопросу…");
        await this.hooks.next();
      } else {
        this.status("evaluating", session.reviewing ? "Тренер отвечает на уточнение…" : "Тренер разбирает ответ…");
        await this.hooks.submit(answer, command === "next" || command === "skip");
      }
      narrate = true;
    }
  }
}

window.LiveTraining = LiveTraining;
window.SpeechGate = SpeechGate;
window.liveCommand = liveCommand;
