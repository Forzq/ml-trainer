"""Personalized progress across the current question bank."""
from fastapi import APIRouter, Request


def create_router(app):
    router = APIRouter()

    @router.get("/api/progress")
    def progress(request: Request):
        store = app.state.store
        return store.progress_catalog.snapshot(store.question_grades(request.state.owner))

    return router
