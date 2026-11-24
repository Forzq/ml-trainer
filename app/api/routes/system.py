"""Application status, public configuration, page and shutdown endpoints."""
import threading
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from app.core.config import ROOT
from app.core.build_info import current_build
from app.questions.catalog import TOPICS, LEVELS

def create_router(app, access=None):
    settings = app.state.settings
    router = APIRouter()

    @router.get("/api/health")
    def health():
        build = current_build()
        return {"app": "ml-trainer", "version": build["version"], "status": "ok", "build_id": build["id"]}

    @router.get("/api/config")
    def config(request: Request):
        store = app.state.store
        return {
            "token": "" if settings.beta_origin else app.state.token,
            "beta": bool(settings.beta_origin),
            "display_name": access.display_name(request.state.owner) if access else None,
            "ai": settings.ai_enabled,
            "deepgram": bool(settings.deepgram_key), "model": settings.trainer_model_name,
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

    @router.post("/api/shutdown")
    def shutdown():
        controller = getattr(app.state, "controller", None)
        if controller:
            threading.Timer(0.5, lambda: setattr(controller, "should_exit", True)).start()
        return {"ok": True}

    @router.get("/")
    def index():
        return FileResponse(ROOT / "web" / "index.html")

    return router
