"""HTTP adapters for the training application service."""
from fastapi import APIRouter
from app.api.schemas import NewSession, Answer, DiscussionMessage, NextQuestion


def create_router(app):
    router = APIRouter(prefix="/api/sessions")

    @router.post("")
    def new_session(body: NewSession):
        return app.state.training.new_session(body)

    @router.get("/{session_id}")
    def get_session(session_id: str):
        return app.state.sessions.state(session_id)

    @router.post("/{session_id}/answer")
    def answer(session_id: str, body: Answer):
        return app.state.training.answer(session_id, body)

    @router.post("/{session_id}/discuss")
    def discussion(session_id: str, body: DiscussionMessage):
        return app.state.training.discussion(session_id, body)

    @router.post("/{session_id}/next")
    def next_question(session_id: str, body: NextQuestion):
        return app.state.training.next_question(session_id, body)

    @router.post("/{session_id}/finish")
    def finish(session_id: str):
        return app.state.training.finish(session_id)

    return router
