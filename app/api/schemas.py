"""Validated HTTP request bodies."""
from typing import Literal
from pydantic import BaseModel, Field


class NewSession(BaseModel):
    topic: str = "all"
    level: Literal["all", "Junior", "Middle", "Senior"] = "all"
    candidate_level: Literal["Junior", "Middle", "Senior"] = "Middle"
    count: int = Field(default=4, ge=1, le=20)

class Answer(BaseModel):
    question_id: int
    answer: str = Field(default="", max_length=12000)
    skip: bool = False

class DiscussionMessage(BaseModel):
    question_id: int
    message: str = Field(min_length=1, max_length=12000)

class NextQuestion(BaseModel):
    question_id: int

class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    tone: Literal["natural", "calm", "very_calm_slow", "friendly", "excited", "soft", "whisper"] = "natural"
    stream: bool = False
