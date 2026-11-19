"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
global.window = global;
vm.runInThisContext(fs.readFileSync(require("node:path").join(__dirname, "../../web/js/audio/live.js"), "utf8"));

const silent = new SpeechGate();
assert.equal(silent.sample(0, 0), null);
assert.equal(silent.sample(0, 25000), "empty");
const gate = new SpeechGate();
for (let t = 0; t <= 250; t += 50) assert.equal(gate.sample(0.08, t), null);
assert.equal(gate.sample(0, 3200), null);
assert.equal(gate.sample(0, 3250), "speech");
const click = new SpeechGate();
click.sample(0, 0); click.sample(0.1, 50); click.sample(0, 100);
assert.equal(click.sample(0, 25000), "empty");
const thinking = new SpeechGate({ silenceMs: 5000 });
thinking.sample(.1, 0); thinking.sample(.1, 200);
assert.equal(thinking.sample(0, 4000), null);
assert.equal(thinking.sample(.1, 4100), null);
assert.equal(thinking.sample(0, 8000), null);
assert.equal(liveCommand("Следующий вопрос, пожалуйста!"), "next");
assert.equal(liveCommand("Я не знаю точную формулу, но объясню смысл"), null);
assert.equal(liveCommand("Мы делаем паузу между обновлениями весов"), null);
assert.equal(liveCommand("Заверши тренировку."), "finish");
const lateVoice = new SpeechGate();
lateVoice.sample(0, 0); lateVoice.sample(.1, 24950);
assert.equal(lateVoice.sample(.1, 25000), null, "Do not cut off a word starting at the wait deadline");

function fixture() {
  let session = { id: "test", question: { id: 1, question: "Question" }, attempts: [], reviewing: false, completed: false };
  const log = { listened: 0, submitted: [], drafts: [], next: 0 };
  const hooks = { session: () => session, busy: () => false, update() {}, cancelSpeech() {}, checkReady() {},
    say: async () => true,
    transcribe: async () => ({ text: "My answer", cleanup: "applied" }),
    acceptTranscript: (result) => { log.drafts.push(result.text); return result.text; },
    submit: async (text, skip) => {
      log.submitted.push({ text, skip });
      session = { ...session, reviewing: true, attempts: [{ question: session.question, feedback: "Feedback", discussion: [] }] };
    },
    next: async () => { log.next++; session = { ...session, completed: true, question: null }; }, finish: async () => {},
  };
  const controller = new LiveTraining(hooks);
  controller.prepare = async () => {};
  controller.timing.tailMs = 0;
  controller.listen = async () => { log.listened++; return { reason: log.listened > 1 ? "empty" : "speech", blob: {} }; };
  return { controller, hooks, log };
}
async function until(test) {
  for (let i = 0; i < 100; i++) { if (test()) return; await new Promise((resolve) => setTimeout(resolve, 2)); }
  throw new Error("Unit state timed out");
}
(async () => {
  const ordinary = fixture();
  await ordinary.controller.start(); await ordinary.controller.task;
  assert.equal(ordinary.log.submitted.length, 1);
  assert.equal(ordinary.log.next, 1);
  assert.equal(ordinary.controller.enabled, false);
  const noSpeech = fixture();
  noSpeech.controller.listen = async () => ({ reason: "empty" });
  await noSpeech.controller.start(); await noSpeech.controller.task;
  assert.equal(noSpeech.log.submitted.length, 0);
  assert.equal(noSpeech.log.next, 0);
  assert.equal(noSpeech.controller.paused, true);
  const cancelled = fixture();
  let finishAudio;
  cancelled.hooks.say = () => new Promise((resolve) => { finishAudio = resolve; });
  await cancelled.controller.start();
  assert.equal(cancelled.log.listened, 0, "Microphone must wait for playback completion");
  cancelled.controller.pause(); finishAudio(true); await cancelled.controller.task;
  assert.equal(cancelled.log.listened, 0);
  const late = fixture();
  let finishRecognition;
  late.hooks.transcribe = () => new Promise((resolve) => { finishRecognition = resolve; });
  await late.controller.start(); await until(() => finishRecognition);
  late.controller.pause(); finishRecognition({ text: "Late transcript", cleanup: "applied" });
  await late.controller.task;
  assert.deepEqual(late.log.drafts, ["Late transcript"]);
  assert.equal(late.log.submitted.length, 0);
  const failed = fixture();
  failed.hooks.submit = async () => { throw new Error("Evaluation failed"); };
  await failed.controller.start(); await failed.controller.task;
  assert.equal(failed.controller.paused, true);
  assert.deepEqual(failed.log.drafts, ["My answer"]);
  const cleanup = fixture();
  cleanup.hooks.transcribe = async () => ({ text: "Raw speech", cleanup: "unavailable" });
  await cleanup.controller.start(); await cleanup.controller.task;
  assert.equal(cleanup.controller.paused, true);
  assert.deepEqual(cleanup.log.drafts, ["Raw speech"]);
  assert.equal(cleanup.log.submitted.length, 0);
  const finish = fixture();
  let finished = 0;
  finish.hooks.transcribe = async () => ({ text: "Заверши тренировку.", cleanup: "applied" });
  finish.hooks.finish = async () => { finished++; };
  await finish.controller.start(); await finish.controller.task;
  assert.equal(finished, 1);
  assert.equal(finish.log.submitted.length, 0);
  assert.equal(finish.controller.enabled, false);
  const disconnected = fixture();
  disconnected.controller.listen = async () => ({ reason: "device-ended" });
  await disconnected.controller.start(); await disconnected.controller.task;
  assert.equal(disconnected.controller.paused, true);
  assert.equal(disconnected.log.submitted.length, 0);
  console.log("Live state and endpointing checks passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
