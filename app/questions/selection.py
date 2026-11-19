"""Balance topics while preferring less-practiced questions within each topic."""
from collections import deque

from app.questions.catalog import TOPICS


def select_questions(cards: list[dict], counts: dict[int, int], limit: int) -> list[dict]:
    queues = {topic["id"]: deque() for topic in TOPICS}
    for card in sorted(cards, key=lambda card: (counts.get(card["id"], 0), card["id"])):
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
