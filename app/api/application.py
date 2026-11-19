"""Composition root: initialize services and mount feature routers."""
import logging
import secrets
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import ROOT, Settings
from app.storage.store import Store
from app.audio.speech import Speech
from app.training.reader import SessionReader
from app.training.evaluator import evaluate, discuss
from app.training.service import TrainingService
from app.training.errors import TrainingError
from app.api.security import install_security
from app.api.routes import system, catalog, history, sessions, audio
from app.api.routes.avatar import avatar_router

LOG = logging.getLogger("ml-trainer")


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        store = Store(settings)
        app.state.store = store
        try:
            app.state.sessions = SessionReader(store)
            app.state.token = secrets.token_urlsafe(32)
            app.state.session_lock = threading.Lock()
            app.state.speech = Speech(settings)
            app.state.training = TrainingService(
                store, app.state.sessions, settings, app.state.session_lock,
                evaluate=evaluate, discuss=discuss,
            )
            yield
        finally:
            store.close()

    app = FastAPI(title="ML Trainer", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    install_security(app)
    app.include_router(avatar_router(settings.data_dir))
    for module in (system, catalog, history, sessions, audio):
        app.include_router(module.create_router(app))

    @app.exception_handler(TrainingError)
    async def training_error(request, error):
        return JSONResponse({"detail": error.detail}, status_code=error.status_code)

    @app.exception_handler(Exception)
    async def server_error(request, error):
        LOG.exception("Request failed: %s", request.url.path)
        return JSONResponse({"detail": "Не удалось выполнить запрос. Подробности в logs/server.log."}, status_code=500)

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app
