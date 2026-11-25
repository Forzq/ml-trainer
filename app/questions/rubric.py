"""Versioned question rubrics and deterministic scoring of model judgements."""
import hashlib
import json
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROMPT_VERSION = "weighted-rubric-v3"
CREDIT_RULES = {
    "0": "Критерий не раскрыт или объяснён неверно.",
    "1": "Есть отдельный верный элемент, но большая часть смысла не раскрыта или ошибочна.",
    "2": "Верно объяснена примерно половина ключевого содержания критерия.",
    "3": "Главная идея верна, но есть существенный пропуск или локальная неточность.",
    "4": "Критерий раскрыт корректно и достаточно для заданного вопроса; формулировка может отличаться от эталона.",
}


def prepare_card(card):
    result = deepcopy(card)
    result.setdefault("followups", [])
    count = len(result["criteria"])
    for index, criterion in enumerate(result["criteria"]):
        criterion.setdefault("id", f"c{index + 1}")
        criterion.setdefault("max_points", 100 // count + (index < 100 % count))
    payload = {key: result.get(key) for key in ("question", "level", "reference", "criteria", "followups")}
    result["rubric_version"] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return result


class CriterionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    status: Literal["correct", "partial", "incorrect", "not_answered"]
    credit: int = Field(strict=True, ge=0, le=4)
    evidence: str = Field(max_length=400)

    @model_validator(mode="after")
    def consistent_status(self):
        expected = {"correct": {4}, "partial": {1, 2, 3}, "incorrect": {0}, "not_answered": {0}}
        if self.credit not in expected[self.status]:
            raise ValueError("Credit contradicts criterion status")
        if self.status != "not_answered" and not self.evidence.strip():
            raise ValueError("A judgement needs evidence from the answer")
        return self


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    feedback: str = Field(min_length=1, max_length=6000)
    criterion_results: list[CriterionResult] = Field(min_length=1, max_length=6)


def score_evaluation(card, evaluation, model, profile):
    card = prepare_card(card)
    rubric = {criterion["id"]: criterion for criterion in card["criteria"]}
    returned = [result.id for result in evaluation.criterion_results]
    if len(returned) != len(set(returned)) or set(returned) != set(rubric):
        raise ValueError("Evaluation must cover each rubric criterion exactly once")
    if sum(c["max_points"] for c in rubric.values()) != 100:
        raise ValueError("Rubric weights must total 100")
    by_id = {item.id: item for item in evaluation.criterion_results}
    rows = []
    for criterion in card["criteria"]:
        item = by_id[criterion["id"]]
        # Quarter points are exact binary fractions. Round only the final total.
        earned = criterion["max_points"] * item.credit / 4
        rows.append(dict(item.model_dump(), label=criterion["label"], max_points=criterion["max_points"], earned_points=earned))
    return {"score": int(sum(row["earned_points"] for row in rows) + .5), "feedback": evaluation.feedback.strip(),
            "criterion_results": rows, "covered": [r["label"] for r in rows if r["status"] == "correct"],
            "partial": [r["label"] for r in rows if r["status"] == "partial"],
            "missing": [r["label"] for r in rows if r["status"] in {"incorrect", "not_answered"}],
            "mode": "ai", "model": model, "prompt_version": PROMPT_VERSION,
            "rubric_version": card["rubric_version"], "profile": profile}
