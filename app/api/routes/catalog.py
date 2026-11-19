"""Question search endpoints."""
from typing import Literal
import httpx
from fastapi import APIRouter, HTTPException
from app.training.reader import public_card

def create_router(app):
    router = APIRouter()

    @router.get("/api/cards")
    def cards(q: str = "", topic: str = "all", level: Literal["all", "Junior", "Middle", "Senior"] = "all"):
        if len(q) > 500:
            raise HTTPException(422, "Поисковый запрос слишком длинный.")
        try:
            rows = app.state.store.search(q, topic, level)
        except httpx.HTTPError:
            raise HTTPException(502, "Сервис векторизации недоступен. Проверь настройки embeddings.")
        return {"cards": [dict(public_card(c), **({"similarity": c["similarity"]} if "similarity" in c else {})) for c in rows]}

    return router
