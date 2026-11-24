"""Admit paid beta requests without waiting for provider capacity."""
import re
from threading import BoundedSemaphore

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.beta.quotas import UsageLimit

PAID_SESSION_ACTION = re.compile(r"/api/sessions/[^/]+/(answer|discuss)")


def uses_provider(request, settings):
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


class BetaProviderAdmission:
    def __init__(self, app, *, access, settings):
        self.app = app
        self.access = access
        self.settings = settings
        self.slots = BoundedSemaphore(settings.beta_max_in_flight)

    async def __call__(self, scope, receive, send):
        owner = scope.get("state", {}).get("owner")
        if scope["type"] != "http" or not owner or not uses_provider(Request(scope), self.settings):
            await self.app(scope, receive, send)
            return
        if not self.slots.acquire(blocking=False):
            response = JSONResponse(
                {"detail": "Сервис занят. Повтори запрос через пару секунд."},
                status_code=503,
                headers={"Retry-After": "2"},
            )
            await response(scope, receive, send)
            return

        try:
            try:
                await run_in_threadpool(
                    self.access.quotas.consume_provider, owner,
                    self.settings.beta_identity_daily_limit, self.settings.beta_total_daily_limit,
                )
            except UsageLimit as error:
                await limit_response(error)(scope, receive, send)
                return
            # Hold the slot until the ASGI response ends, even for streaming audio.
            await self.app(scope, receive, send)
        finally:
            self.slots.release()
