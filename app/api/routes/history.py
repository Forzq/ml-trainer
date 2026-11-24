"""Training history pagination and global counters."""
from fastapi import APIRouter, Query, Request


def create_router(app):
    router = APIRouter()

    @router.get("/api/stats")
    def stats(request: Request):
        return app.state.store.stats(request.state.owner)

    @router.get("/api/history")
    def history(request: Request, page: int = Query(default=1, ge=1), page_size: int = Query(default=30, ge=1, le=100)):
        return app.state.store.history(page, page_size, owner=request.state.owner)

    return router
