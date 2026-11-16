"""Export a blind CSV worksheet and import actual human annotations."""
import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.benchmark import case_fingerprint, load_dataset, validate_labels

FIELDS = ["case_id", "question_id", "fingerprint", "question", "question_level", "answer", "reference", "sources",
          "criterion_id", "criterion", "max_points", "human_status", "human_credits", "rationale"]


def safe_cell(value):
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def export_sheet(data, path, split=None, limit=None):
    cases = [case for case in data["cases"] if split is None or case["split"] == split]
    if limit: cases=cases[:limit]
    random.Random(1729).shuffle(cases)
    if path.exists(): raise ValueError("Worksheet exists; choose another output to preserve annotations")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer=csv.DictWriter(stream, fieldnames=FIELDS, delimiter=";"); writer.writeheader()
        for case in cases:
            card=data["questions_by_id"][case["question_id"]]
            for criterion in card["criteria"]:
                writer.writerow({"case_id":case["id"],"question_id":card["id"],"fingerprint":case_fingerprint(case,card),
                    "question":safe_cell(card["question"]),"question_level":card["level"],"answer":safe_cell(case["answer"]),
                    "reference":safe_cell(card["reference"]),"criterion_id":criterion["id"],"criterion":safe_cell(criterion["label"]),
                    "sources":" | ".join(data.get("reference_sources",{}).get(str(card["id"]),[])),
                    "max_points":criterion["max_points"],"human_status":"","human_credits":"","rationale":""})
    return len(cases)


def import_sheet(data, path, reviewer):
    if not reviewer.strip(): raise ValueError("A human reviewer name is required")
    cases={case["id"]:case for case in data["cases"]}; grouped=defaultdict(list)
    with path.open(encoding="utf-8-sig",newline="") as stream:
        for row in csv.DictReader(stream,delimiter=";"):
            if row["case_id"] not in cases: raise ValueError("Unknown case in worksheet")
            case=cases[row["case_id"]]; card=data["questions_by_id"][case["question_id"]]
            if row["fingerprint"]!=case_fingerprint(case,card) or int(row["question_id"])!=card["id"]:
                raise ValueError("Worksheet refers to a different question or answer revision")
            rubric={criterion["id"]:criterion for criterion in card["criteria"]}
            criterion=rubric.get(row["criterion_id"])
            if not criterion or any(row[key] != safe_cell(value) for key,value in {
                "question":card["question"],"answer":case["answer"],"reference":card["reference"],
                "criterion":criterion["label"],"max_points":criterion["max_points"]}.items()):
                raise ValueError("Readonly question, answer, or rubric cells were edited; make a new dataset revision")
            grouped[case["id"]].append(row)
    updates=[]
    for identifier, rows in grouped.items():
        filled=[bool(row["human_status"].strip() or row["human_credits"].strip() or row["rationale"].strip()) for row in rows]
        if not any(filled): continue
        if all(row["human_status"].strip()=="reject" for row in rows):
            if any(row["human_credits"].strip() or not row["rationale"].strip() for row in rows):
                raise ValueError("Rejected rubric needs a reason and no credits")
            updates.append((cases[identifier],None,data["questions_by_id"][cases[identifier]["question_id"]],
                            "Rejected by human: " + " | ".join(dict.fromkeys(row["rationale"].strip() for row in rows))))
            continue
        labels=[]
        for row in rows:
            labels.append({"id":row["criterion_id"],"status":row["human_status"].strip(),
                           "credits":sorted({int(value.strip()) for value in row["human_credits"].split("|") if value.strip()}),
                           "rationale":row["rationale"].strip()})
        case=cases[identifier]; card=data["questions_by_id"][case["question_id"]]
        validate_labels(labels,card)
        updates.append((case, labels, card, "Imported from a completed human worksheet; not proof of independent expert consensus."))
    # Validate the entire sheet before changing anything.
    for case, labels, card, note in updates:
        previous=case["review"]
        if previous["status"]=="approved":
            case.setdefault("review_history",[]).append({"review":previous,"expected":case["expected"]})
        case["expected"]=labels
        case["review"]={"status":"approved" if labels else "rejected","reviewer":reviewer.strip(),"fingerprint":case_fingerprint(case,card),
                        "reviewed_at":datetime.now(timezone.utc).isoformat(),"note":note}
    return len(updates)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["export","import"])
    parser.add_argument("--dataset",type=Path,default=ROOT/"evals/mentor-draft-v1.json")
    parser.add_argument("--sheet",type=Path,required=True)
    parser.add_argument("--split",choices=["dev","test","regression"])
    parser.add_argument("--limit",type=int)
    parser.add_argument("--reviewer",default="")
    parser.add_argument("--out",type=Path,help="A new reviewed dataset file; the original is preserved")
    args=parser.parse_args(); data=load_dataset(args.dataset)
    if args.limit is not None and args.limit<1: parser.error("--limit must be positive")
    if args.action=="export":
        count=export_sheet(data,args.sheet,args.split,args.limit); print(f"Exported {count} cases for blind human review: {args.sheet}")
    else:
        if not args.out or not args.reviewer: parser.error("Import requires --out and --reviewer")
        if args.out.exists(): parser.error("Output exists; use a new versioned filename")
        count=import_sheet(data,args.sheet,args.reviewer)
        if not count: parser.error("No completed human annotations; nothing was promoted to gold")
        del data["questions_by_id"]; data["id"] += "-human-reviewed"
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(f"Saved {count} human-reviewed cases: {args.out}")


if __name__=="__main__": main()
