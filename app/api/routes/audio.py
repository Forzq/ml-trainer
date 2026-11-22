"""Speech recognition, conservative transcript editing and audio playback endpoints."""
import logging
import httpx
from fastapi import APIRouter, HTTPException, File, Form, UploadFile
from fastapi.responses import Response, StreamingResponse
from app.audio.speech import SpeechError
from app.audio.recognition import RecognitionError, recognize_audio
from app.audio.transcription import clean_transcript
from app.api.schemas import SpeechRequest

LOG = logging.getLogger("ml-trainer")

def create_router(app):
    settings = app.state.settings
    router = APIRouter()

    @router.post("/api/transcribe")
    async def transcribe(audio: UploadFile = File(...), session_id: str | None = Form(None),
                         question_id: int | None = Form(None)):
        if not settings.stt_enabled:
            raise HTTPException(409, "Для распознавания добавь DEEPGRAM_API_KEY или OPENAI_API_KEY в .env и перезапусти приложение.")
        raw = await audio.read(20 * 1024 * 1024 + 1)
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(413, "Запись слишком длинная. Лимит — 20 МБ.")
        if not raw:
            raise HTTPException(422, "Запись пустая.")
        context = None
        if (session_id is None) != (question_id is None):
            raise HTTPException(422, "Для контекста записи нужны сессия и вопрос.")
        if session_id is not None:
            current = app.state.sessions.state(session_id)
            if current["completed"] or current["question"]["id"] != question_id:
                raise HTTPException(409, "Вопрос уже изменился. Запиши ответ на текущий вопрос.")
            context = current["question"]
        try:
            text, provider = await recognize_audio(raw, audio.content_type or "audio/webm", settings)
        except RecognitionError as error:
            raise HTTPException(502, str(error)) from None
        raw_text = text
        cleanup = "disabled" if not settings.transcription_enabled else "skipped"
        if settings.transcription_enabled and text.strip():
            try:
                text = await clean_transcript(raw_text, settings, context)
                cleanup = "applied"
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
                # Preserve the recognized speech even when the optional editor is unavailable.
                LOG.warning("Transcript cleanup unavailable; returning original recognition")
                text = raw_text
                cleanup = "unavailable"
        return {"text": text, "raw_text": raw_text, "cleanup": cleanup, "provider": provider}

    @router.post("/api/speech")
    async def speech(body: SpeechRequest):
        if body.stream:
            iterator = app.state.speech.stream(body.text, body.tone, voice=body.voice)
            try:
                first = await anext(iterator)
            except SpeechError as error:
                await iterator.aclose()
                raise HTTPException(error.status, error.detail) from None

            async def audio_chunks():
                try:
                    yield first
                    async for chunk in iterator:
                        yield chunk
                except SpeechError as error:
                    LOG.warning("Speech stream interrupted: %s", error.detail)
                    raise RuntimeError("Speech stream interrupted") from None
                finally:
                    await iterator.aclose()

            return StreamingResponse(audio_chunks(), media_type="audio/mpeg", headers={"X-Accel-Buffering": "no"})
        try:
            audio = await app.state.speech.synthesize(body.text, body.tone, voice=body.voice)
        except SpeechError as error:
            raise HTTPException(error.status, error.detail) from None
        return Response(audio, media_type="audio/mpeg")

    return router
