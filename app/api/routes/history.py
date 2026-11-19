"""Training history pagination and global counters."""
from fastapi import APIRouter, Query


def create_router(app):
    router = APIRouter()

    @router.get("/api/stats")
    def stats():
        return app.state.store.stats()

    @router.get("/api/history")
    def history(page: int = Query(default=1, ge=1), page_size: int = Query(default=30, ge=1, le=100)):
        return app.state.store.history(page, page_size)

    return router
