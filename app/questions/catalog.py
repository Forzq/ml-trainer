"""Question bank schema and interview training topics."""
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.config import ROOT
from app.questions.rubric import prepare_card

LEVELS = ("Junior", "Middle", "Senior")
TOPICS = [
    {"id": "classical_ml", "name": "Классический ML", "description": "Модели, метрики, признаки и валидация", "symbol": "◈"},
    {"id": "data_science", "name": "Data Science", "description": "Статистика, анализ данных и эксперименты", "symbol": "◷"},
    {"id": "nlp", "name": "NLP", "description": "Язык, тексты и языковые модели", "symbol": "✳"},
    {"id": "cv", "name": "CV", "description": "Изображения и компьютерное зрение", "symbol": "▧"},
    {"id": "dl", "name": "DL", "description": "Нейронные сети и глубокое обучение", "symbol": "∿"},
    {"id": "ml_system_design", "name": "Системный дизайн", "description": "Архитектура ML-систем, запуск и мониторинг", "symbol": "⌘"},
]
LEGACY_TOPICS = {"fundamentals": "classical_ml", "metrics": "classical_ml", "linear": "classical_ml"}
MOCK_INTERVIEW_TAG = "mock-interview"
GITHUB_QUESTION_TAG = "github_ques"
SOURCE_TAGS = frozenset((MOCK_INTERVIEW_TAG, GITHUB_QUESTION_TAG))


def canonical_topic(topic: str) -> str:
    return LEGACY_TOPICS.get(topic, topic)


def has_interview_recording(card: dict) -> bool:
    return any(source.get("format", "mock") in {"mock", "interview-review", "real-interview"}
               for source in card.get("mock_sources", []))


class Criterion(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=3)
    keywords: list[str] = Field(min_length=1)
    max_points: int = Field(strict=True, ge=4, le=100)


class MockInterviewSource(BaseModel):
    video_url: str = Field(pattern=r"^https://[^\s]+$")
    title: str = Field(min_length=3)
    published_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_seconds: int = Field(ge=0)
    end_seconds: int = Field(gt=0)
    interviewer_summary: str = Field(min_length=15, max_length=1200)
    format: Literal["mock", "expert-review", "interview-review", "real-interview"] = Field(
        default="mock", exclude_if=lambda value: value == "mock",
    )

    @model_validator(mode="after")
    def valid_clip(self):
        date.fromisoformat(self.published_on)
        if self.end_seconds <= self.start_seconds:
            raise ValueError("A video clip must end after its start")
        return self


class GitHubQuestionSource(BaseModel):
    url: str = Field(pattern=r"^https://github\.com/[^/\s]+/[^/\s]+/blob/[^\s]+$")
    collection: str = Field(min_length=3, max_length=200)


class Question(BaseModel):
    id: int = Field(gt=0)
    topic_id: str
    topic: str
    title: str = Field(min_length=3)
    question: str = Field(min_length=15)
    level: Literal["Junior", "Middle", "Senior"]
    interview_frequency: int | None = Field(default=None, strict=True, ge=1, le=3, exclude_if=lambda value: value is None)
    tags: list[str] = Field(min_length=1)
    reference: str = Field(min_length=60, max_length=6000)
    criteria: list[Criterion] = Field(min_length=2, max_length=6)
    followups: list[str] = Field(default_factory=list, max_length=8)
    rubric_version: str
    mock_sources: list[MockInterviewSource] = Field(default_factory=list, exclude_if=lambda sources: not sources)
    github_sources: list[GitHubQuestionSource] = Field(default_factory=list, exclude_if=lambda sources: not sources)

    @model_validator(mode="after")
    def valid_rubric(self):
        if sum(c.max_points for c in self.criteria) != 100 or len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("Rubric needs unique criterion IDs and weights totalling 100")
        if any(not text.strip() for text in self.followups):
            raise ValueError("Empty followup")
        if bool(self.mock_sources) != (MOCK_INTERVIEW_TAG in self.tags):
            raise ValueError("The mock-interview tag requires a video source")
        if bool(self.github_sources) != (GITHUB_QUESTION_TAG in self.tags):
            raise ValueError("The github_ques tag requires a GitHub source")
        return self


def load_cards(path=None) -> list[dict]:
    raw = json.loads((path or ROOT / "content/questions.json").read_text(encoding="utf-8"))
    cards = [Question.model_validate(prepare_card(card)).model_dump() for card in raw]
    if not cards:
        raise ValueError("The question bank is empty")
    topics = {topic["id"]: topic["name"] for topic in TOPICS}
    ids, questions = set(), set()
    for card in cards:
        question = " ".join(card["question"].casefold().split())
        if card["id"] in ids or question in questions:
            raise ValueError("Duplicate question ID or text in the bank")
        if topics.get(card["topic_id"]) != card["topic"]:
            raise ValueError("Unknown or inconsistent question topic")
        if any(not word.strip() for criterion in card["criteria"] for word in criterion["keywords"]):
            raise ValueError("Empty demo evaluation keyword")
        ids.add(card["id"])
        questions.add(question)
    return cards
