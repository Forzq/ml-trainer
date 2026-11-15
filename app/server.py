import json
import logging
import secrets
import threading
import uuid
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT, Settings
from app.store import Store
from app.trainer import evaluate

LOG = logging.getLogger("ml-trainer")
TOPICS = [
    {"id": "fundamentals", "name": "Основы ML", "description": "Обобщение, выборки и обучение", "symbol": "◈"},
    {"id": "metrics", "name": "Метрики", "description": "Качество модели и цена ошибок", "symbol": "◷"},
    {"id": "linear", "name": "Линейные модели", "description": "Регрессия, веса и регуляризация", "symbol": "∿"},
]


def public_card(card):
    return {key: card[key] for key in ("id", "topic_id", "topic", "title", "question", "level", "tags")}


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(settings)
        app.state.token = secrets.token_urlsafe(32)
        app.state.session_lock = threading.Lock()
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
            "embedding": store.embeddings.name, "semantic": store.embeddings.remote,
            "database": "Qdrant Server" if settings.qdrant_url else "Qdrant Local",
            "collection": store.collection, "cards": len(store.cards),
            "topics": [dict(topic, count=sum(c["topic_id"] == topic["id"] for c in store.cards)) for topic in TOPICS],
        }

    @app.get("/api/cards")
    def cards(q: str = "", topic: str = "all"):
        if len(q) > 500:
            raise HTTPException(422, "Поисковый запрос слишком длинный.")
        try:
            rows = app.state.store.search(q, topic)
        except httpx.HTTPError:
            raise HTTPException(502, "Сервис векторизации недоступен. Проверь настройки embeddings.")
        return {"cards": [dict(public_card(c), **({"similarity": c["similarity"]} if "similarity" in c else {})) for c in rows]}

    @app.get("/api/history")
    def history():
        return {"sessions": app.state.store.history()}

    def session_state(session_id):
        store = app.state.store
        with store.connect() as db:
            row = db.execute("SELECT id, topic, question_ids, completed_at FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Тренировка не найдена.")
            attempts = db.execute(
                "SELECT question_id, answer, feedback, score, mode FROM attempts WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        ids = json.loads(row[2])
        done = {a[0] for a in attempts}
        pending = [i for i in ids if i not in done and i in store.by_id]
        complete = bool(row[3]) or not pending
        return {
            "id": row[0], "topic": row[1], "total": len(ids), "answered": len(attempts),
            "completed": complete,
            "question": public_card(store.by_id[pending[0]]) if pending and not complete else None,
            "attempts": [{**json.loads(a[2]), "question": public_card(store.by_id[a[0]]),
                          "answer": a[1], "score": a[3], "mode": a[4]} for a in attempts if a[0] in store.by_id],
        }

    class NewSession(BaseModel):
        topic: str = "all"
        count: int = Field(default=4, ge=1, le=20)

    @app.post("/api/sessions")
    def new_session(body: NewSession):
        store = app.state.store
        if body.topic not in ["all"] + [t["id"] for t in TOPICS]:
            raise HTTPException(422, "Неизвестная тема.")
        selected = store.search(topic=body.topic)
        if not selected:
            raise HTTPException(422, "В этой теме пока нет вопросов.")
        # Prefer less-practiced cards; deterministic order makes the starter easy to inspect.
        with store.connect() as db:
            counts = dict(db.execute("SELECT question_id, COUNT(*) FROM attempts GROUP BY question_id"))
            selected.sort(key=lambda card: (counts.get(card["id"], 0), card["id"]))
            session_id = str(uuid.uuid4())
            db.execute("INSERT INTO sessions(id,topic,question_ids) VALUES(?,?,?)",
                       (session_id, body.topic, json.dumps([c["id"] for c in selected[:body.count]])))
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
                ids = db.execute("SELECT question_ids FROM sessions WHERE id=?", (session_id,)).fetchone()[0]
                count = db.execute("SELECT COUNT(*) FROM attempts WHERE session_id=?", (session_id,)).fetchone()[0]
                if count >= len(json.loads(ids)):
                    db.execute("UPDATE sessions SET completed_at=CURRENT_TIMESTAMP WHERE id=?", (session_id,))
            return {"evaluation": result, "session": session_state(session_id)}

    @app.post("/api/sessions/{session_id}/finish")
    def finish(session_id: str):
        with app.state.session_lock:
            session_state(session_id)
            with app.state.store.connect() as db:
                db.execute("UPDATE sessions SET completed_at=COALESCE(completed_at,CURRENT_TIMESTAMP) WHERE id=?", (session_id,))
            return session_state(session_id)

    @app.post("/api/transcribe")
    async def transcribe(audio: UploadFile = File(...)):
        if not settings.deepgram_key:
            raise HTTPException(409, "Для распознавания добавь DEEPGRAM_API_KEY в .env и перезапусти приложение.")
        raw = await audio.read(20 * 1024 * 1024 + 1)
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(413, "Запись слишком длинная. Лимит — 20 МБ.")
        if not raw:
            raise HTTPException(422, "Запись пустая.")
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(
                    "https://api.deepgram.com/v1/listen",
                    params={"model": "nova-3", "language": "multi", "smart_format": "true"},
                    headers={"Authorization": f"Token {settings.deepgram_key}", "Content-Type": audio.content_type or "audio/webm"},
                    content=raw,
                )
                response.raise_for_status()
                text = response.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            raise HTTPException(502, "Deepgram не смог распознать запись. Проверь ключ и подключение.")
        return {"text": text}

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
