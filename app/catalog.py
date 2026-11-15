"""Question bank schema and the five interview training topics."""
import json
from typing import Literal

from pydantic import BaseModel, Field

from app.config import ROOT

LEVELS = ("Junior", "Middle", "Senior")
TOPICS = [
    {"id": "classical_ml", "name": "Классический ML", "description": "Модели, метрики, признаки и валидация", "symbol": "◈"},
    {"id": "data_science", "name": "Data Science", "description": "Статистика, анализ данных и эксперименты", "symbol": "◷"},
    {"id": "nlp", "name": "NLP", "description": "Язык, тексты и языковые модели", "symbol": "✳"},
    {"id": "cv", "name": "CV", "description": "Изображения и компьютерное зрение", "symbol": "▧"},
    {"id": "dl", "name": "DL", "description": "Нейронные сети и глубокое обучение", "symbol": "∿"},
]
LEGACY_TOPICS = {"fundamentals": "classical_ml", "metrics": "classical_ml", "linear": "classical_ml"}


def canonical_topic(topic: str) -> str:
    return LEGACY_TOPICS.get(topic, topic)


class Criterion(BaseModel):
    label: str = Field(min_length=3)
    keywords: list[str] = Field(min_length=1)


class Question(BaseModel):
    id: int = Field(gt=0)
    topic_id: str
    topic: str
    title: str = Field(min_length=3)
    question: str = Field(min_length=15)
    level: Literal["Junior", "Middle", "Senior"]
    tags: list[str] = Field(min_length=1)
    reference: str = Field(min_length=60, max_length=6000)
    criteria: list[Criterion] = Field(min_length=2, max_length=6)


def load_cards(path=None) -> list[dict]:
    raw = json.loads((path or ROOT / "content/questions.json").read_text(encoding="utf-8"))
    cards = [Question.model_validate(card).model_dump() for card in raw]
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
