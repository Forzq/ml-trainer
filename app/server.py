import json
import logging
import secrets
import threading
import uuid
from contextlib import asynccontextmanager
from typing import Literal

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT, Settings
from app.store import Store
from app.speech import Speech, SpeechError
from app.trainer import discuss, evaluate
from app.transcription import clean_transcript
from app.recognition import RecognitionError, recognize_audio
from app.catalog import LEVELS, TOPICS, canonical_topic
from app.selection import select_questions

LOG = logging.getLogger("ml-trainer")


def public_card(card):
    return {key: card[key] for key in ("id", "topic_id", "topic", "title", "question", "level", "tags")}


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(settings)
        app.state.token = secrets.token_urlsafe(32)
        app.state.session_lock = threading.Lock()
        app.state.speech = Speech(settings)
        yield
        app.state.store.close()

    app = FastAPI(title="ML Trainer", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Недопустимый источник запроса."}, status_code=403)
            if request.headers.get("x-app-token") != getattr(app.state, "token", None):
                return JSONResponse({"detail": "Обнови страницу приложения."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Exception)
    async def server_error(request, error):
        LOG.exception("Request failed: %s", request.url.path)
        return JSONResponse({"detail": "Не удалось выполнить запрос. Подробности в logs/server.log."}, status_code=500)

    @app.get("/api/health")
    def health():
        return {"app": "ml-trainer", "version": "0.1.0", "status": "ok"}

    @app.get("/api/config")
    def config():
        store = app.state.store
        return {
            "token": app.state.token, "ai": settings.ai_enabled,
            "deepgram": bool(settings.deepgram_key), "model": settings.model,
            "whisper": bool(settings.openai_key), "whisper_model": settings.openai_transcription_model,
            "transcription": {"ready": settings.transcription_enabled, "model": settings.transcription_model_name},
            "tts": {"provider": settings.tts_provider, "ready": settings.fish_enabled,
                    "voice_id": settings.fish_voice_id, "model": settings.fish_model},
            "embedding": store.embeddings.name, "semantic": store.embeddings.remote,
            "database": "Qdrant Server" if settings.qdrant_url else "Qdrant Local",
            "collection": store.collection, "cards": len(store.cards),
            "levels": list(LEVELS),
            "topics": [dict(topic, count=sum(c["topic_id"] == topic["id"] for c in store.cards),
                            levels={level: sum(c["topic_id"] == topic["id"] and c["level"] == level for c in store.cards)
                                    for level in LEVELS}) for topic in TOPICS],
        }

    @app.get("/api/cards")
    def cards(q: str = "", topic: str = "all", level: Literal["all", "Junior", "Middle", "Senior"] = "all"):
        if len(q) > 500:
            raise HTTPException(422, "Поисковый запрос слишком длинный.")
        try:
            rows = app.state.store.search(q, topic, level)
        except httpx.HTTPError:
            raise HTTPException(502, "Сервис векторизации недоступен. Проверь настройки embeddings.")
        return {"cards": [dict(public_card(c), **({"similarity": c["similarity"]} if "similarity" in c else {})) for c in rows]}

    @app.get("/api/stats")
    def stats():
        return app.state.store.stats()

    @app.get("/api/history")
    def history(page: int = Query(default=1, ge=1), page_size: int = Query(default=30, ge=1, le=100)):
        return app.state.store.history(page, page_size)

    def session_state(session_id):
        store = app.state.store
        with store.connect() as db:
            row = db.execute("SELECT id, topic, question_ids, completed_at, current_index FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Тренировка не найдена.")
            attempts = db.execute(
                "SELECT question_id, answer, feedback, score, mode FROM attempts WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
            turns = db.execute(
                "SELECT id, question_id, message, reply, mode, created_at FROM discussions WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        ids = json.loads(row[2])
        done = {a[0] for a in attempts}
        index = min(row[4], max(0, len(ids) - 1))
        active_id = ids[index] if ids else None
        complete = bool(row[3]) or active_id not in store.by_id
        return {
            "id": row[0], "topic": canonical_topic(row[1]), "total": len(ids), "answered": len(attempts),
            "completed": complete, "current_index": index,
            "reviewing": not complete and active_id in done,
            "question": public_card(store.by_id[active_id]) if not complete else None,
            "attempts": [{**json.loads(a[2]), "question": public_card(store.by_id[a[0]]),
                          "answer": a[1], "score": a[3], "mode": a[4],
                          "discussion": [{"id": t[0], "message": t[2], "reply": t[3], "mode": t[4], "created_at": t[5]}
                                         for t in turns if t[1] == a[0]]} for a in attempts if a[0] in store.by_id],
        }

    class NewSession(BaseModel):
        topic: str = "all"
        level: Literal["all", "Junior", "Middle", "Senior"] = "all"
        count: int = Field(default=4, ge=1, le=20)

    @app.post("/api/sessions")
    def new_session(body: NewSession):
        store = app.state.store
        if body.topic not in ["all"] + [t["id"] for t in TOPICS]:
            raise HTTPException(422, "Неизвестная тема.")
        selected = store.search(topic=body.topic, level=body.level)
        if not selected:
            raise HTTPException(422, "Для выбранной темы и сложности пока нет вопросов.")
        # Balance eligible topics and prefer less-practiced cards within each topic.
        with store.connect() as db:
            counts = dict(db.execute("SELECT question_id, COUNT(*) FROM attempts GROUP BY question_id"))
            selected = select_questions(selected, counts, body.count)
            session_id = str(uuid.uuid4())
            db.execute("INSERT INTO sessions(id,topic,question_ids) VALUES(?,?,?)",
                       (session_id, body.topic, json.dumps([c["id"] for c in selected])))
        return session_state(session_id)

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str):
        return session_state(session_id)

    class Answer(BaseModel):
        question_id: int
        answer: str = Field(default="", max_length=12000)
        skip: bool = False

    @app.post("/api/sessions/{session_id}/answer")
    def answer(session_id: str, body: Answer):
        with app.state.session_lock:
            state = session_state(session_id)
            if state["completed"]:
                raise HTTPException(409, "Эта тренировка уже завершена.")
            if state["reviewing"]:
                raise HTTPException(409, "Ответ уже разобран. Можно обсудить его в чате или перейти к следующему вопросу.")
            if body.question_id != state["question"]["id"]:
                raise HTTPException(409, "Вопрос уже изменился. Обнови тренировку.")
            text = body.answer.strip()
            if not body.skip and not text:
                raise HTTPException(422, "Напиши или запиши ответ.")
            card = app.state.store.by_id[body.question_id]
            if body.skip:
                result = {"score": 0, "feedback": "Ориентир для ответа: " + card["reference"],
                          "covered": [], "missing": [c["label"] for c in card["criteria"]], "mode": "skipped"}
            else:
                try:
                    result = evaluate(card, text, settings)
                except (httpx.HTTPError, ValueError, KeyError, IndexError):
                    raise HTTPException(502, "Модель не смогла проверить ответ. Проверь ключ, баланс и название модели. Ответ сохранён в поле ввода; можно повторить запрос.")
            with app.state.store.connect() as db:
                db.execute("INSERT INTO attempts(session_id,question_id,answer,feedback,score,mode) VALUES(?,?,?,?,?,?)",
                           (session_id, body.question_id, text, json.dumps(result, ensure_ascii=False), result["score"], result["mode"]))
            return {"evaluation": result, "session": session_state(session_id)}

    class DiscussionMessage(BaseModel):
        question_id: int
        message: str = Field(min_length=1, max_length=12000)

    @app.post("/api/sessions/{session_id}/discuss")
    def discussion(session_id: str, body: DiscussionMessage):
        with app.state.session_lock:
            state = session_state(session_id)
            if state["completed"] or not state["reviewing"]:
                raise HTTPException(409, "Обсуждение доступно после разбора текущего ответа.")
            if state["question"]["id"] != body.question_id:
                raise HTTPException(409, "Вопрос уже изменился. Обнови тренировку.")
            text = body.message.strip()
            if not text:
                raise HTTPException(422, "Напиши или запиши уточнение.")
            attempt = next(item for item in state["attempts"] if item["question"]["id"] == body.question_id)
            try:
                result = discuss(app.state.store.by_id[body.question_id], attempt, text, settings)
            except (httpx.HTTPError, ValueError, KeyError, IndexError):
                raise HTTPException(502, "Тренер не смог ответить. Сообщение осталось в поле ввода; можно отправить ещё раз.")
            with app.state.store.connect() as db:
                db.execute("INSERT INTO discussions(session_id,question_id,message,reply,mode) VALUES(?,?,?,?,?)",
                           (session_id, body.question_id, text, result["reply"], result["mode"]))
            return {"discussion": result, "session": session_state(session_id)}

    class NextQuestion(BaseModel):
        question_id: int

    @app.post("/api/sessions/{session_id}/next")
    def next_question(session_id: str, body: NextQuestion):
        with app.state.session_lock:
            state = session_state(session_id)
            if state["completed"] or not state["reviewing"]:
                raise HTTPException(409, "Сначала ответь на текущий вопрос или пропусти его.")
            if state["question"]["id"] != body.question_id:
                raise HTTPException(409, "Вопрос уже изменился. Обнови тренировку.")
            with app.state.store.connect() as db:
                if state["current_index"] + 1 >= state["total"]:
                    db.execute("UPDATE sessions SET completed_at=CURRENT_TIMESTAMP WHERE id=?", (session_id,))
                else:
                    db.execute("UPDATE sessions SET current_index=current_index+1 WHERE id=?", (session_id,))
            return session_state(session_id)

    @app.post("/api/sessions/{session_id}/finish")
    def finish(session_id: str):
        with app.state.session_lock:
            session_state(session_id)
            with app.state.store.connect() as db:
                db.execute("UPDATE sessions SET completed_at=COALESCE(completed_at,CURRENT_TIMESTAMP) WHERE id=?", (session_id,))
            return session_state(session_id)

    @app.post("/api/transcribe")
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
            current = session_state(session_id)
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

    class SpeechRequest(BaseModel):
        text: str = Field(min_length=1, max_length=6000)
        tone: Literal["natural", "calm", "friendly", "excited", "soft", "whisper"] = "natural"
        stream: bool = False

    @app.post("/api/speech")
    async def speech(body: SpeechRequest):
        if body.stream:
            iterator = app.state.speech.stream(body.text, body.tone)
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
            audio = await app.state.speech.synthesize(body.text, body.tone)
        except SpeechError as error:
            raise HTTPException(error.status, error.detail) from None
        return Response(audio, media_type="audio/mpeg")

    @app.post("/api/shutdown")
    def shutdown():
        controller = getattr(app.state, "controller", None)
        if controller:
            threading.Timer(0.5, lambda: setattr(controller, "should_exit", True)).start()
        return {"ok": True}

    @app.get("/")
    def index():
        return FileResponse(ROOT / "web" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app


if __name__ == "__main__":
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="info"))
    app.state.controller = server
    server.run()
