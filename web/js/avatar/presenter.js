"use strict";

function syncTrainerAvatar() {
  const speaking = speech.status === "playing";
  if (!speaking && (state.recorder?.state === "recording" || (live.running && ["listening", "followup"].includes(live.phase)))) {
    trainerAvatar.update("listening", "Слушаю тебя");
  } else if ((state.busy && !speaking) || speech.status === "loading") {
    trainerAvatar.update("thinking", "Думаю над ответом…");
  } else {
    const attempt = state.session?.attempts.find((item) => item.question.id === state.session?.question?.id);
    const reaction = attempt ? (attempt.mode === "ai" && attempt.score >= 70 ? "positive" : "supportive") : "neutral";
    trainerAvatar.update(reaction, speaking ? "Говорю…" : attempt ? "Можно обсудить ответ" : "Готов к тренировке", speaking);
  }
}

