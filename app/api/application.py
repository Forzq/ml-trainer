"""Composition root: initialize services and mount feature routers."""
import logging
import secrets
from contextlib import asynccontextmanager
from functools import partial
from urllib.parse import urlsplit
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
from app.api.admission import limit_response
from app.api.security import install_security
from app.api.routes import system, catalog, history, progress, sessions, audio, beta, beta_admin
from app.api.routes.avatar import avatar_router
from app.beta.access import BetaAccess
from app.beta.admin_access import AdminAccess
from app.beta.quotas import UsageLimit

LOG = logging.getLogger("ml-trainer")


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    access = None
    administrator = None
    if settings.beta_origin:
        origin = urlsplit(settings.beta_origin)
        if (origin.scheme != "https" or not origin.hostname or origin.username is not None
                or origin.path or origin.query or origin.fragment or origin.port is not None):
            raise ValueError("MOCKROOM_BETA_ORIGIN must be an HTTPS origin without a port or path.")
        if min(settings.beta_identity_daily_limit, settings.beta_total_daily_limit) < 0:
            raise ValueError("Beta request limits must be non-negative.")
        if not 1 <= settings.beta_max_in_flight <= 16:
            raise ValueError("MOCKROOM_BETA_MAX_IN_FLIGHT must be between 1 and 16.")
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        access = BetaAccess(settings.data_dir / "beta.sqlite3")
        administrator = AdminAccess(access.connect)

    @asynccontextmanager
    async def lifespan(app):
        store = Store(settings)
        app.state.store = store
        try:
            app.state.sessions = SessionReader(store)
            app.state.token = secrets.token_urlsafe(32)
            app.state.speech = Speech(settings)
            app.state.training = TrainingService(
                store, app.state.sessions, settings,
                evaluate=evaluate, discuss=discuss,
                reserve_provider=partial(
                    access.quotas.consume_provider, account_limit=settings.beta_identity_daily_limit,
                    total_limit=settings.beta_total_daily_limit,
                ) if access else None,
            )
            yield
        finally:
            store.close()

    app = FastAPI(title="ML Trainer", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None if access else "/openapi.json")
    app.state.settings = settings
    install_security(app, access, administrator)
    if access:
        app.include_router(beta.create_router(access, settings))
        app.include_router(beta_admin.create_router(access, administrator, settings))
    app.include_router(avatar_router())
    app.include_router(system.create_router(app, access))
    for module in (catalog, history, progress, sessions, audio):
        app.include_router(module.create_router(app))

    @app.exception_handler(TrainingError)
    async def training_error(request, error):
        return JSONResponse({"detail": error.detail}, status_code=error.status_code)

    @app.exception_handler(UsageLimit)
    async def usage_limit(request, error):
        return limit_response(error)

    @app.exception_handler(Exception)
    async def server_error(request, error):
        LOG.exception("Request failed: %s", request.url.path)
        return JSONResponse({"detail": "Не удалось выполнить запрос. Подробности в logs/server.log."}, status_code=500)

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app
