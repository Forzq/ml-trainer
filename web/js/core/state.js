"use strict";

const $ = (selector) => document.querySelector(selector);
const isDesktop = () => typeof window.pywebview?.api?.close === "function";
const speechRecognitionReady = () => Boolean(state.config?.deepgram || state.config?.whisper);
const storage = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch {} },
  remove(key) { try { localStorage.removeItem(key); } catch {} },
};
function savedVolume() {
  const stored = storage.get("ml-voice-volume");
  const value = stored === null ? 75 : Number(stored);
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) / 100 : 0.75;
}

const voiceTones = new Set(["natural", "calm", "very_calm_slow", "friendly", "excited", "soft", "whisper"]);
const savedTone = storage.get("ml-voice-tone");
// A separate preference makes automatic narration explicit and enabled on first use.
const state = { config: null, session: null, busy: false, awaitingNext: false, libraryTopic: "all", libraryLevel: "all", query: "", sound: storage.get("ml-auto-speech") !== "off", volume: savedVolume(), tone: voiceTones.has(savedTone) ? savedTone : "natural", page: "home", historyPage: 1, historyVersion: 0, recorder: null, stream: null, recordingTimer: null, toastTimer: null, searchVersion: 0 };
const speech = { version: 0, controller: null, audio: null, reader: null, receiving: false, utterance: null, objectUrl: null, status: "idle", completion: null, resolve: null };
