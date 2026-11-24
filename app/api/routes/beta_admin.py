"""Browser administration for the hosted beta."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr, ValidationError
from starlette.concurrency import run_in_threadpool

from app.beta.access import digest
from app.beta.admin_access import ADMIN_COOKIE, ADMIN_SESSION_SECONDS
from app.beta.quotas import DEFAULT_ACCOUNT, GLOBAL, account_subject
from app.core.build_info import current_build
from app.core.config import ROOT
from app.integrations.openrouter import current_key_budget

ADMIN_LOGIN = "/api/admin/login"
ADMIN_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
             "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


class Credentials(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=256)


class DailyLimit(BaseModel):
    target: Literal["global", "default", "account"]
    account_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    maximum: int | None = Field(ge=0, le=2**63 - 1)


class AccountNote(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class NewInvitation(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    hours: int = Field(default=72, ge=1, le=720)


def usage_status(access, settings):
    used, maximum, default, reset, accounts = access.quotas.provider_usage(
        settings.beta_identity_daily_limit, settings.beta_total_daily_limit,
    )
    names = access.display_names()
    notes = access.account_notes()
    remaining = max(0, maximum - used)
    return {
        "build": current_build(),
        "global": {"used": used, "limit": maximum, "remaining": remaining},
        "default_limit": default,
        "reset_at": reset,
        "accounts": [
            {"id": identifier, "label": label, "display_name": names.get(identifier),
             "active": bool(active), "used": count,
             "limit": limit, "custom": custom, "notes": notes.get(identifier, []),
             "remaining": min(max(0, limit - count), remaining) if active else 0}
            for identifier, label, active, count, limit, custom in accounts
        ],
    }


def create_router(access, administrator, settings):
    router = APIRouter()

    @router.get("/admin")
    def admin_page():
        return FileResponse(ROOT / "web" / "admin.html", headers={"Content-Security-Policy": ADMIN_CSP})

    @router.post(ADMIN_LOGIN)
    async def login(request: Request, response: Response):
        address = request.client.host if request.client else "unknown"
        await run_in_threadpool(
            access.quotas.consume, "admin-login", [("ip:" + digest(address), 8)], window=300,
            message="Слишком много попыток входа. Попробуй через несколько минут.",
        )
        try:
            body = Credentials.model_validate_json(await request.body())
        except ValidationError:
            raise HTTPException(422, "Введи логин и пароль.") from None
        token = await run_in_threadpool(administrator.login, body.login, body.password.get_secret_value())
        if token is None:
            raise HTTPException(401, "Неверный логин или пароль.")
        response.set_cookie(ADMIN_COOKIE, token, max_age=ADMIN_SESSION_SECONDS,
                            secure=True, httponly=True, samesite="strict")
        return {"ok": True}

    @router.post("/api/admin/logout")
    def logout(request: Request, response: Response):
        administrator.logout(request.cookies[ADMIN_COOKIE])
        response.delete_cookie(ADMIN_COOKIE, secure=True, httponly=True, samesite="strict")
        return {"ok": True}

    @router.get("/api/admin/usage")
    def usage():
        return usage_status(access, settings)

    @router.put("/api/admin/limits")
    def set_limit(body: DailyLimit):
        if body.target == "account":
            if not body.account_id:
                raise HTTPException(422, "Выбери участника.")
            subject = account_subject(body.account_id)
        else:
            subject = GLOBAL if body.target == "global" else DEFAULT_ACCOUNT
        try:
            access.quotas.set_provider_limit(subject, body.maximum)
        except ValueError:
            raise HTTPException(404, "Участник не найден.") from None
        return usage_status(access, settings)

    @router.post("/api/admin/accounts/{account_id}/reset-usage")
    def reset_usage(account_id: str = Path(pattern=r"^[a-f0-9]{32}$")):
        if not access.quotas.reset_account_usage(account_id):
            raise HTTPException(404, "Участник не найден.")
        return usage_status(access, settings)

    @router.post("/api/admin/accounts/{account_id}/notes", status_code=201)
    def add_note(body: AccountNote, account_id: str = Path(pattern=r"^[a-f0-9]{32}$")):
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "Введи заметку.")
        if not access.add_account_note(account_id, text):
            raise HTTPException(404, "Участник не найден.")
        return usage_status(access, settings)

    @router.post("/api/admin/invites", status_code=201)
    def create_invite(body: NewInvitation):
        label = " ".join(body.label.split())
        if not label or not label.isprintable():
            raise HTTPException(422, "Введи имя или метку участника.")
        account_id, _, code = access.issue(label, body.hours * 3600)
        return {"account_id": account_id, "code": code}

    @router.get("/api/admin/openrouter")
    def openrouter_budget():
        return current_key_budget(settings)

    return router
