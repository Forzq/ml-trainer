"""Compare production judge outputs with frozen, independently reviewed labels."""
import argparse
import csv
import json
import random
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.evaluation.benchmark import digest, load_dataset, oracle_result, select_cases, summarise
from app.core.config import Settings
from app.training.prompts import SYSTEM_PROMPT, voice_instruction
from app.questions.rubric import CREDIT_RULES, PROMPT_VERSION
from app.training.evaluator import evaluate


def positive(value):
    number = int(value)
    if number < 1: raise argparse.ArgumentTypeError("Use a positive integer")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT/"evals/mentor-draft-v1.json")
    parser.add_argument("--split", choices=["dev", "test", "regression"], default="dev")
    parser.add_argument("--include-drafts", action="store_true", help="Exploratory synthetic evaluation, not validated human gold")
    parser.add_argument("--model", help="OpenRouter model ID; defaults to the configured trainer")
    parser.add_argument("--limit", type=positive)
    parser.add_argument("--repeats", type=positive, default=1)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Send selected synthetic/reviewed inputs to OpenRouter")
    mode.add_argument("--self-test", action="store_true", help="Local oracle: test tooling only, never model quality")
    args = parser.parse_args()
    data = load_dataset(args.dataset)
    cases = select_cases(data, args.split, args.include_drafts, args.limit)
    settings = Settings()
    if args.model: settings.model = args.model
    plan = {"dataset": data["id"], "split": args.split, "selected_cases": len(cases),
            "planned_calls": len(cases)*args.repeats if args.run else 0,
            "repeats": args.repeats, "model": settings.model if args.run else "local-oracle" if args.self_test else "not-run",
            "review_states": dict(Counter(case["review"]["status"] for case in data["cases"])),
            "warning": "DRAFT labels are not independently established gold" if args.include_drafts else None}
    print(json.dumps(plan, ensure_ascii=True), flush=True)
    if not args.run and not args.self_test:
        print("Plan only: no API calls. Review labels first, or use --include-drafts for an exploratory run.")
        return
    if not cases: raise SystemExit("No eligible cases. Import human labels or explicitly choose --include-drafts.")
    if args.run and not settings.ai_enabled: raise SystemExit("Configure OPENROUTER_API_KEY and a model in .env.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT/"logs/judge-evals"/(stamp + "-" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    original = {key: value for key, value in data.items() if key != "questions_by_id"}
    metadata = {**plan, "dataset_sha256": digest(original), "prompt_version": PROMPT_VERSION,
                "prompt_sha256": digest(SYSTEM_PROMPT.format(mentor_voice=voice_instruction("female"))),
                "credit_rules_sha256": digest(CREDIT_RULES),
                "planned_attempts": len(cases)*args.repeats,
                "gold_status": "human_reviewed" if all(case["review"]["status"] == "approved" for case in cases) else "draft_exploratory",
                "backend": "OpenRouter production evaluator" if args.run else "LOCAL ORACLE — NOT A MODEL EVALUATION"}
    records = []; interrupted = False
    try:
        with (output/"predictions.jsonl").open("w", encoding="utf-8", buffering=1) as stream:
            for repeat in range(args.repeats):
                for case in cases:
                    record = {"case_id": case["id"], "repeat": repeat, "result": None}
                    started = time.perf_counter()
                    try:
                        card = data["questions_by_id"][case["question_id"]]
                        # Human/proposed labels NEVER enter the evaluator's input.
                        record["result"] = evaluate(card, case["answer"], settings, profile=case["profile"]) if args.run else oracle_result(card, case)
                        if record["result"].get("mode") != "ai": raise ValueError("Demo mode is not an evaluator benchmark")
                    except Exception as error:
                        record["result"] = None
                        record["error"] = {"type": type(error).__name__, "http_status": getattr(getattr(error, "response", None), "status_code", None)}
                    record["elapsed_seconds"] = round(time.perf_counter()-started, 4)
                    records.append(record); stream.write(json.dumps(record, ensure_ascii=False)+"\n")
                    print(f"{len(records)}/{metadata['planned_attempts']} {case['id']}: " +
                          (str(record["result"]["score"]) if record["result"] else "FAILED"), flush=True)
    except KeyboardInterrupt:
        interrupted = True
    report = {"metadata": metadata, "complete": not interrupted and len(records)==metadata["planned_attempts"],
              "metrics": summarise(records, cases, data["questions_by_id"])}
    (output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Judge evaluation report", "", f"Backend: {metadata['backend']}", f"Labels: {metadata['gold_status']}",
             f"Split: {args.split}; complete: {report['complete']}", "", "```json", json.dumps(report["metrics"], ensure_ascii=False, indent=2), "```",
             "", "Numerical agreement does not assess factual accuracy or helpfulness of feedback. Inspect predictions.jsonl manually.",
             "Draft-label and local-oracle results are not evidence of a model's real quality."]
    (output/"report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    # Feedback correctness needs human review; never grade it with the judge itself.
    by_id={case["id"]:case for case in cases}
    rows=[record for record in records if record.get("result")]; random.Random(1729).shuffle(rows)
    columns=["case_id","repeat","question","answer","feedback","factual_accuracy_1_5","fairness_1_5","usefulness_1_5","invented_claim_yes_no","comment"]
    with (output/"feedback-review.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,delimiter=";"); writer.writeheader()
        for record in rows:
            case=by_id[record["case_id"]]; card=data["questions_by_id"][case["question_id"]]
            values={"case_id":case["id"],"repeat":record["repeat"],"question":card["question"],"answer":case["answer"],"feedback":record["result"]["feedback"]}
            writer.writerow({key:("'"+value if isinstance(value,str) and value.startswith(("=","+","-","@","\t","\r")) else value) for key,value in values.items()})
    print("Report: " + str(output/"report.md"))
    if interrupted: raise SystemExit(130)


if __name__ == "__main__": main()
