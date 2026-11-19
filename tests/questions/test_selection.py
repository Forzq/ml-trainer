from collections import Counter

import pytest

from app.questions.catalog import TOPICS
from app.questions.selection import select_questions


def cards_for(topic, count, offset=0):
    return [{"id": offset + index, "topic_id": topic} for index in range(1, count + 1)]


@pytest.mark.parametrize("limit", [1, 2, 4, 5, 7, 20])
def test_mixed_session_balances_every_round_without_duplicates(limit):
    cards = [card for index, topic in enumerate(TOPICS)
             for card in cards_for(topic["id"], 4, index * 100)]
    selected = select_questions(cards, {}, limit)
    assert len(selected) == len({card["id"] for card in selected}) == limit
    for end in range(1, limit + 1):
        counts = Counter(card["topic_id"] for card in selected[:end])
        sizes = [counts[topic["id"]] for topic in TOPICS]
        assert max(sizes) - min(sizes) <= 1
    assert all(first["topic_id"] != second["topic_id"] for first, second in zip(selected, selected[1:]))


def test_question_priority_within_topics_survives_mixing():
    cards = [card for index, topic in enumerate(TOPICS)
             for card in cards_for(topic["id"], 4, index * 100)]
    counts = {card["id"]: {1: 9, 2: 5, 3: 0, 4: 0}[card["id"] % 100] for card in cards}
    selected = select_questions(cards, counts, 20)
    for index, topic in enumerate(TOPICS):
        ids = [card["id"] for card in selected if card["topic_id"] == topic["id"]]
        assert ids == [index * 100 + number for number in [3, 4, 2, 1]]


def test_less_practiced_topics_lead_short_sessions():
    cards = [card for index, topic in enumerate(TOPICS)
             for card in cards_for(topic["id"], 4, index * 100)]
    # The first topic still has unseen questions, but has already had more practice.
    counts = {1: 1}
    selected = select_questions(cards, counts, 2)
    assert [card["topic_id"] for card in selected] == ["data_science", "nlp"]


def test_sparse_topics_fill_remaining_slots_and_missing_topics_are_ignored():
    cards = cards_for("classical_ml", 4) + cards_for("data_science", 1, 100) + cards_for("cv", 4, 300)
    selected = select_questions(cards, {}, 20)
    assert len(selected) == len({card["id"] for card in selected}) == len(cards)
    assert [card["topic_id"] for card in selected[:3]] == ["classical_ml", "data_science", "cv"]
    assert [card["topic_id"] for card in selected[3:]] == ["classical_ml", "cv"] * 3
    assert select_questions([], {}, 20) == []


def test_single_topic_keeps_less_practiced_question_order():
    cards = cards_for("classical_ml", 4)
    selected = select_questions(cards, {1: 5, 2: 1}, 3)
    assert [card["id"] for card in selected] == [3, 4, 2]
