"""Access policy for the local desktop and hosted beta."""
import re
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.beta.access import COOKIE
from app.beta.quotas import UsageLimit

REDEEM = "/api/beta/redeem"
PAID_SESSION_ACTION = re.compile(r"/api/sessions/[^/]+/(answer|discuss)/?")


def quota_applies(request, settings):
    path = request.url.path.rstrip("/")
    if request.method == "POST":
        return ((settings.ai_enabled and PAID_SESSION_ACTION.fullmatch(path))
                or (settings.stt_enabled and path == "/api/transcribe")
                or (settings.fish_enabled and path == "/api/speech"))
    return (request.method == "GET" and path == "/api/cards"
            and settings.embedding_model and settings.openrouter_key
            and request.query_params.get("q", "").strip())


def limit_response(error):
    return JSONResponse({"detail": str(error)}, status_code=429,
                        headers={"Retry-After": str(error.retry_after), "Cache-Control": "no-store"})


def install_security(app, access=None):
    settings = app.state.settings
    hosts = ["127.0.0.1", "localhost", "testserver"]
    if access:
        hosts.append(urlsplit(settings.beta_origin).hostname)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    async def authorize(request, call_next):
        request.state.owner = ""
        if access:
            path = request.url.path
            if path == "/api" or path.startswith("/api/"):
                if path.rstrip("/") == "/api/shutdown":
                    return JSONResponse({"detail": "Маршрут недоступен."}, status_code=404)
                if path != "/api/health" or request.method not in ("GET", "HEAD"):
                    if str(request.base_url).rstrip("/") != settings.beta_origin:
                        return JSONResponse({"detail": "Подключись к Mockroom по HTTPS."}, status_code=403)
                    if request.method not in ("GET", "HEAD") and (
                        request.headers.get("origin") != settings.beta_origin
                        or request.headers.get("x-mockroom-client") != "web"
                    ):
                        return JSONResponse({"detail": "Недопустимый источник запроса."}, status_code=403)
                    if path != REDEEM or request.method != "POST":
                        owner = await run_in_threadpool(access.authenticate, request.cookies.get(COOKIE))
                        if owner is None:
                            return JSONResponse({"detail": "Войди по приглашению."}, status_code=401)
                        request.state.owner = owner
                        if quota_applies(request, settings):
                            try:
                                await run_in_threadpool(
                                    access.quotas.consume_provider, owner, settings.beta_identity_daily_limit,
                                    settings.beta_total_daily_limit,
                                )
                            except UsageLimit as error:
                                return limit_response(error)
        elif request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Недопустимый источник запроса."}, status_code=403)
            if request.headers.get("x-app-token") != getattr(app.state, "token", None):
                return JSONResponse({"detail": "Обнови страницу приложения."}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def secure_response(request: Request, call_next):
        response = await authorize(request, call_next)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response
