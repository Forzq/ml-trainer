"""Invitation exchange and logout for the hosted beta."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.beta.access import COOKIE, SESSION_SECONDS, digest


class InviteCode(BaseModel):
    code: str = Field(min_length=1, max_length=128)


def create_router(access):
    router = APIRouter(prefix="/api/beta")

    @router.post("/redeem")
    def redeem(body: InviteCode, request: Request, response: Response):
        if access.authenticate(request.cookies.get(COOKIE)):
            raise HTTPException(409, "Сначала выйди из текущего профиля.")
        address = request.client.host if request.client else "unknown"
        access.quotas.consume("invite", [("ip:" + digest(address), 10), ("global", 120)], window=60,
                              message="Слишком много попыток входа. Попробуй через минуту.")
        token = access.redeem(body.code.strip())
        if token is None:
            raise HTTPException(400, "Приглашение недействительно, просрочено или уже использовано.")
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, secure=True, httponly=True, samesite="strict")
        return {"ok": True}

    @router.post("/logout")
    def logout(request: Request, response: Response):
        access.logout(request.cookies[COOKIE])
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict")
        return {"ok": True}

    return router
