"""Balance topics while preferring less-practiced questions within each topic."""
from collections import deque

from app.questions.catalog import TOPICS, has_interview_recording


def select_questions(cards: list[dict], counts: dict[int, int], limit: int, *, prioritize_interviews: bool = False) -> list[dict]:
    queues = {topic["id"]: deque() for topic in TOPICS}

    def order(card):
        practiced = counts.get(card["id"], 0)
        if prioritize_interviews:
            return practiced, not has_interview_recording(card), -(card.get("interview_frequency") or 0), card["id"]
        return practiced, card["id"]

    for card in sorted(cards, key=order):
        queues[card["topic_id"]].append(card)
    # Start with less-practiced topics so short sessions reach different sections.
    topic_order = sorted((topic for topic, queue in queues.items() if queue), key=lambda topic: (
        counts.get(queues[topic][0]["id"], 0),
        sum(counts.get(card["id"], 0) for card in queues[topic]),
    ))
    selected = []
    while topic_order and len(selected) < limit:
        for topic in topic_order:
            selected.append(queues[topic].popleft())
            if len(selected) == limit:
                return selected
        topic_order = [topic for topic in topic_order if queues[topic]]
    return selected
