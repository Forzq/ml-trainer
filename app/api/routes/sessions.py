"""HTTP adapters for the training application service."""
from fastapi import APIRouter, Request
from app.api.schemas import NewSession, Answer, DiscussionMessage, NextQuestion


def create_router(app):
    router = APIRouter(prefix="/api/sessions")

    @router.post("")
    def new_session(body: NewSession, request: Request):
        return app.state.training.new_session(body, owner=request.state.owner)

    @router.get("/{session_id}")
    def get_session(session_id: str, request: Request):
        return app.state.sessions.state(session_id, owner=request.state.owner)

    @router.post("/{session_id}/answer")
    def answer(session_id: str, body: Answer, request: Request):
        return app.state.training.answer(session_id, body, owner=request.state.owner)

    @router.post("/{session_id}/discuss")
    def discussion(session_id: str, body: DiscussionMessage, request: Request):
        return app.state.training.discussion(session_id, body, owner=request.state.owner)

    @router.post("/{session_id}/next")
    def next_question(session_id: str, body: NextQuestion, request: Request):
        return app.state.training.next_question(session_id, body, owner=request.state.owner)

    @router.post("/{session_id}/finish")
    def finish(session_id: str, request: Request):
        return app.state.training.finish(session_id, owner=request.state.owner)

    return router
