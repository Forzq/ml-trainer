"""Validated HTTP request bodies."""
from typing import Literal
from pydantic import BaseModel, Field
from app.core.config import TrainerVoice


class NewSession(BaseModel):
    topic: str = "all"
    skill: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$", max_length=64)
    level: Literal["all", "Junior", "Middle", "Senior"] = "all"
    candidate_level: Literal["Junior", "Middle", "Senior"] = "Middle"
    count: int = Field(default=4, ge=1, le=20)
    prioritize_interviews: bool = False

class Answer(BaseModel):
    question_id: int
    answer: str = Field(default="", max_length=12000)
    skip: bool = False
    voice: TrainerVoice = "female"

class DiscussionMessage(BaseModel):
    question_id: int
    message: str = Field(min_length=1, max_length=12000)
    voice: TrainerVoice = "female"

class NextQuestion(BaseModel):
    question_id: int

class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    tone: Literal["natural", "calm", "very_calm_slow", "friendly", "excited", "soft", "whisper"] = "natural"
    stream: bool = False
    voice: TrainerVoice = "female"
