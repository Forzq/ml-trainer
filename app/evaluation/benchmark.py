"""Local, human-calibrated evaluation of the ML answer evaluator."""
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from app.questions.catalog import Question
from app.questions.rubric import Evaluation, prepare_card, score_evaluation

STATUSES = ("correct", "partial", "incorrect", "not_answered")
CREDITS = {"correct": {4}, "partial": {1, 2, 3}, "incorrect": {0}, "not_answered": {0}}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def case_fingerprint(case, card):
    return digest({"question": card, "answer": case["answer"], "profile": case["profile"]})


def validate_labels(labels, card):
    expected_ids = {criterion["id"] for criterion in card["criteria"]}
    if len(labels) != len(expected_ids) or {row["id"] for row in labels} != expected_ids:
        raise ValueError("Labels must cover each criterion exactly once")
    for row in labels:
        values = row["credits"]
        if row["status"] not in CREDITS or not values or any(type(v) is not int or v not in CREDITS[row["status"]] for v in values):
            raise ValueError("Invalid gold status/credit combination")
        if len(values) != len(set(values)) or len(values) > 2:
            raise ValueError("Use one credit, or two adjacent credits for genuine ambiguity")
        if len(values) == 2 and max(values) - min(values) != 1:
            raise ValueError("Ambiguous credits must be adjacent")
        if not row.get("rationale", "").strip():
            raise ValueError("Human labels need a rationale")


def load_dataset(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported dataset schema")
    cards = {}
    for raw in data["questions"]:
        card = Question.model_validate(prepare_card(raw)).model_dump()
        if raw.get("rubric_version") != card["rubric_version"] or card["id"] in cards:
            raise ValueError("Question snapshot changed or duplicate question ID")
        cards[card["id"]] = card
    ids, splits = set(), defaultdict(set)
    for case in data["cases"]:
        if case["id"] in ids or case["question_id"] not in cards:
            raise ValueError("Duplicate case or unknown question")
        ids.add(case["id"])
        if case["split"] not in {"dev", "test", "regression"} or not case["answer"].strip():
            raise ValueError("Invalid split or empty answer")
        if case["profile"].get("candidate_level") not in {"Junior", "Middle", "Senior"}:
            raise ValueError("Invalid candidate level")
        splits[case["question_id"]].add(case["split"])
        card = cards[case["question_id"]]
        validate_labels(case["proposed_expected"], card)
        review = case["review"]
        if review["status"] not in {"draft", "approved", "rejected"}:
            raise ValueError("Unknown review state")
        if review["status"] == "approved":
            if not review.get("reviewer", "").strip() or review.get("fingerprint") != case_fingerprint(case, card):
                raise ValueError("Human review missing or stale after a question/answer change")
            validate_labels(case["expected"], card)
    if any(len(values) != 1 for values in splits.values()):
        raise ValueError("Variants of a question must stay in the same split")
    data["questions_by_id"] = cards
    return data


def labels_for(case):
    return case["expected"] if case["review"]["status"] == "approved" else case["proposed_expected"]


def select_cases(data, split="dev", include_drafts=False, limit=None):
    cases = [case for case in data["cases"] if case["split"] == split and
             (case["review"]["status"] == "approved" or (include_drafts and case["review"]["status"] == "draft"))]
    return cases[:limit] if limit else cases


def score_bounds(card, labels):
    by_id = {row["id"]: row for row in labels}
    return tuple(int(sum(c["max_points"] * operation(by_id[c["id"]]["credits"]) / 4 for c in card["criteria"]) + .5)
                 for operation in (min, max))


def oracle_result(card, case):
    """Fixture for testing infrastructure, never evidence of model quality."""
    raw = {"feedback": "Local infrastructure self-check.", "criterion_results": [
        {"id": row["id"], "status": row["status"], "credit": min(row["credits"]),
         "evidence": case["answer"][:200] if row["status"] != "not_answered" else ""}
        for row in labels_for(case)]}
    return score_evaluation(card, Evaluation.model_validate(raw), "local-oracle", case["profile"])


def _mean(values):
    return round(statistics.mean(values), 4) if values else None


def _percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3) if values else None


def summarise(records, cases, cards):
    selected = {case["id"]: case for case in cases}
    confusion = {label: {guess: 0 for guess in (*STATUSES, "invalid")} for label in STATUSES}
    score_errors, signed_errors, credit_errors, latencies = [], [], [], []
    severe_over = severe_under = failures = agreements = credit_agreements = total = 0
    topic_rows = defaultdict(list); runs = defaultdict(list); semantic_groups = defaultdict(dict)
    valid = []
    for record in records:
        case = selected[record["case_id"]]; card = cards[case["question_id"]]
        gold = labels_for(case); result = record.get("result")
        latencies.append(record["elapsed_seconds"])
        topic_rows[card["topic_id"]].append(record)
        if not result:
            failures += 1
            for row in gold: confusion[row["status"]]["invalid"] += 1; total += 1
            continue
        valid.append(record)
        low, high = score_bounds(card, gold); score = result["score"]
        error = low - score if score < low else score - high if score > high else 0
        signed = score - high if score > high else score - low if score < low else 0
        score_errors.append(error); signed_errors.append(signed)
        severe_over += score > high + 20; severe_under += score < low - 20
        predicted = {row["id"]: row for row in result["criterion_results"]}
        for row in gold:
            guess = predicted[row["id"]]; total += 1
            confusion[row["status"]][guess["status"]] += 1
            agreements += row["status"] == guess["status"]
            credit_agreements += guess["credit"] in row["credits"]
            credit_errors.append(min(abs(guess["credit"] - value) for value in row["credits"]))
        runs[case["id"]].append(score)
        if case.get("equivalence_group"):
            semantic_groups[(case["equivalence_group"], record["repeat"])][case["id"]] = score
    f1 = {}
    for label in STATUSES:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in STATUSES if other != label)
        fn = sum(value for guess, value in confusion[label].items() if guess != label)
        f1[label] = round(2 * tp / (2 * tp + fp + fn), 4) if 2 * tp + fp + fn else None
    spreads = [max(values) - min(values) for values in runs.values() if len(values) > 1]
    equivalent_spreads = []
    for (group, repeat), values in semantic_groups.items():
        required = {case["id"] for case in cases if case.get("equivalence_group") == group}
        if len(required) > 1 and set(values) == required:
            equivalent_spreads.append(max(values.values()) - min(values.values()))
    topic_metrics = {}
    for topic, rows in topic_rows.items():
        errors = []
        for row in rows:
            if row.get("result"):
                case = selected[row["case_id"]]; low, high = score_bounds(cards[case["question_id"]], labels_for(case))
                errors.append(max(low - row["result"]["score"], row["result"]["score"] - high, 0))
        topic_metrics[topic] = {"attempted": len(rows), "failures": sum(not bool(r.get("result")) for r in rows), "score_mae_to_allowed_range": _mean(errors)}
    return {"attempted": len(records), "valid": len(valid), "failures": failures,
            "failure_rate": failures / len(records) if records else None,
            "unique_questions": len({selected[r["case_id"]]["question_id"] for r in records}),
            "score_mae_to_allowed_range_valid_only": _mean(score_errors), "signed_score_bias_valid_only": _mean(signed_errors),
            "severe_overgrades_gt20": severe_over, "severe_undergrades_gt20": severe_under,
            "severe_overgrade_rate_valid_only": severe_over/len(valid) if valid else None,
            "severe_undergrade_rate_valid_only": severe_under/len(valid) if valid else None,
            "status_accuracy_including_failures": agreements / total if total else None,
            "credit_accuracy_including_failures": credit_agreements / total if total else None,
            "credit_mae_valid_only_0_to_4": _mean(credit_errors),
            "macro_f1_including_failures": _mean([value for value in f1.values() if value is not None]),
            "status_f1": f1, "status_support": {label:sum(confusion[label].values()) for label in STATUSES},
            "status_confusion": confusion, "by_topic": topic_metrics,
            "latency_p50_seconds": _percentile(latencies, .5), "latency_p95_seconds": _percentile(latencies, .95),
            "repeat_groups": len(spreads), "mean_repeat_score_spread": _mean(spreads),
            "complete_equivalence_groups": len(equivalent_spreads), "mean_equivalent_score_spread": _mean(equivalent_spreads),
            "equivalent_groups_over_5_points": sum(value > 5 for value in equivalent_spreads)}
