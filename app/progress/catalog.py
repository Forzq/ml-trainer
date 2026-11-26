"""Map stable question IDs to study topics and calculate mastery."""
import json
from collections import defaultdict
from pathlib import Path

from app.questions.catalog import LEVELS, TOPICS

MASTERY_SCORE = 70


class ProgressCatalog:
    def __init__(self, cards):
        curriculum = json.loads(Path(__file__).with_name("curriculum.json").read_text(encoding="utf-8"))
        by_topic = defaultdict(dict)
        for card in cards:
            by_topic[card["topic_id"]][card["id"]] = card

        self._topics = []
        self._groups = {}
        for topic in TOPICS:
            topic_id = topic["id"]
            question_bank = by_topic[topic_id]
            groups, assigned = [], set()
            for entry in curriculum[topic_id]:
                ids = set(entry["questions"])
                if ids & assigned or len(ids) != len(entry["questions"]):
                    raise ValueError(f"Duplicate progress question in {topic_id}/{entry['id']}")
                assigned.update(ids)
                members = [question_bank[identifier] for identifier in entry["questions"] if identifier in question_bank]
                if members:
                    groups.append(({key: value for key, value in entry.items() if key != "questions"}, members))
            other = [card for identifier, card in question_bank.items() if identifier not in assigned]
            if other:
                groups.append(({
                    "id": "other", "name": "Другие вопросы",
                    "summary": "Дополнительные вопросы по этому направлению. Открой банк, чтобы посмотреть формулировки, или пройди тренировку по этой ветке.",
                    "branches": [],
                }, other))

            for info, members in groups:
                key = (topic_id, info["id"])
                if key in self._groups:
                    raise ValueError(f"Duplicate progress skill {topic_id}/{info['id']}")
                self._groups[key] = members
            self._topics.append((topic, groups))

    def cards_for(self, topic_id, skill_id):
        return self._groups.get((topic_id, skill_id))

    def snapshot(self, grades):
        topics = []
        for info, groups in self._topics:
            skills = [self._summarize_skill(skill, cards, grades) for skill, cards in groups]
            # Give a small branch the same weight as a large branch when coloring the parent.
            coverage = int(100 * sum(skill["mastered"] / skill["total"] for skill in skills) / len(skills)) if skills else 0
            topics.append(dict(info, skills=skills, coverage=coverage, **self._totals(skills)))
        return {"mastery_score": MASTERY_SCORE, "topics": topics, "totals": self._totals(topics)}

    @staticmethod
    def _totals(groups):
        return {key: sum(group[key] for group in groups) for key in ("mastered", "attempted", "total")}

    @staticmethod
    def _summarize_skill(skill, cards, grades):
        questions = []
        levels = dict.fromkeys(LEVELS, 0)
        for card in cards:
            identifier, level = card["id"], card["level"]
            levels[level] += 1
            questions.append({"id": identifier, "title": card["title"], "level": level,
                              "attempted": identifier in grades, "best_score": grades.get(identifier)})
        mastered = sum(q["best_score"] is not None and q["best_score"] >= MASTERY_SCORE for q in questions)
        return dict(skill, questions=questions, levels=levels, total=len(cards), mastered=mastered,
                    attempted=sum(q["attempted"] for q in questions), coverage=100 * mastered // len(cards))
