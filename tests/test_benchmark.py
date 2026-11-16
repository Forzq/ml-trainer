import csv
import importlib.util
import json
from copy import deepcopy

import pytest

from app.benchmark import case_fingerprint, load_dataset, oracle_result, select_cases, summarise
from app.config import ROOT

DATASET=ROOT/"evals/mentor-draft-v1.json"


def load_script(name):
    spec=importlib.util.spec_from_file_location(name.replace("-","_"),ROOT/"scripts"/(name+".py"))
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def record(case, card, repeat=0):
    return {"case_id":case["id"],"repeat":repeat,"elapsed_seconds":1,"result":oracle_result(card,case)}


def test_all_candidates_are_drafts_and_question_groups_do_not_leak():
    data=load_dataset(DATASET)
    assert len(data["cases"])==88 and len(data["questions_by_id"])==11
    assert not select_cases(data)
    assert len(select_cases(data,include_drafts=True))==40
    assert len(select_cases(data,"test",True))==40
    assert len(select_cases(data,"regression",True))==8
    assert {c["question_id"] for c in select_cases(data,include_drafts=True)}.isdisjoint(
        {c["question_id"] for c in select_cases(data,"test",True)})
    assert {c["review"]["status"] for c in data["cases"]}=={"draft"}
    assert all(c["expected"] is None for c in data["cases"])
    assert all(not any(word in c["id"] for word in ("correct","wrong","partial","unknown")) for c in data["cases"])


def test_metrics_detect_overgrading_and_do_not_hide_api_failures():
    data=load_dataset(DATASET); cases=select_cases(data,"regression",True); cards=data["questions_by_id"]
    perfect=[record(c,cards[c["question_id"]]) for c in cases]
    report=summarise(perfect,cases,cards)
    assert report["score_mae_to_allowed_range_valid_only"]==0
    assert report["macro_f1_including_failures"]==1 and report["credit_accuracy_including_failures"]==1
    always_full=deepcopy(perfect)
    full=next(row["result"] for row in perfect if row["result"]["score"]==100)
    for row in always_full: row["result"]=deepcopy(full)
    report=summarise(always_full,cases,cards)
    assert report["score_mae_to_allowed_range_valid_only"]==55
    assert report["severe_overgrades_gt20"]==5 and report["status_accuracy_including_failures"]<1
    failed=[{**row,"result":None,"error":{"type":"ReadTimeout"}} for row in perfect]
    report=summarise(failed,cases,cards)
    assert report["failure_rate"]==1 and report["status_accuracy_including_failures"]==0
    assert report["macro_f1_including_failures"]==0 and report["score_mae_to_allowed_range_valid_only"] is None


def test_same_score_cannot_hide_wrong_criterion_statuses():
    data=load_dataset(DATASET); case=next(c for c in data["cases"] if c["question_id"]==302 and c["kind"]=="wrong")
    row=record(case,data["questions_by_id"][302])
    for criterion in row["result"]["criterion_results"]: criterion["status"]="not_answered"
    metrics=summarise([row],[case],data["questions_by_id"])
    assert metrics["score_mae_to_allowed_range_valid_only"]==0
    assert metrics["status_accuracy_including_failures"]==0
    assert metrics["status_confusion"]["incorrect"]["not_answered"]==4


def test_equivalence_and_repeat_instability_are_reported():
    data=load_dataset(DATASET); cases=[c for c in data["cases"] if c["question_id"]==302 and c["equivalence_group"]=="q302-correct"]
    rows=[record(c,data["questions_by_id"][302]) for c in cases]
    rows[1]["result"]["score"]=90
    metrics=summarise(rows,cases,data["questions_by_id"])
    assert metrics["complete_equivalence_groups"]==1 and metrics["mean_equivalent_score_spread"]==10
    assert metrics["equivalent_groups_over_5_points"]==1
    repeated=[record(cases[0],data["questions_by_id"][302],i) for i in range(3)]
    repeated[1]["result"]["score"]=85
    assert summarise(repeated,cases,data["questions_by_id"])["mean_repeat_score_spread"]==15


def test_review_is_blind_and_import_is_atomic(tmp_path):
    review=load_script("review-judge-gold"); data=load_dataset(DATASET); sheet=tmp_path/"sheet.csv"
    review.export_sheet(data,sheet,"regression",1)
    rows=list(csv.DictReader(sheet.open(encoding="utf-8-sig",newline=""),delimiter=";"))
    assert "proposed_expected" not in rows[0] and "kind" not in rows[0]
    assert all(not row["human_status"] and not row["human_credits"] for row in rows)
    assert review.import_sheet(data,sheet,"fixture-human")==0
    rows[0].update(human_status="correct",human_credits="4",rationale="Fixture label only")
    def save():
        with sheet.open("w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=review.FIELDS,delimiter=";"); writer.writeheader(); writer.writerows(rows)
    save()
    with pytest.raises(ValueError): review.import_sheet(data,sheet,"fixture-human")
    assert all(case["review"]["status"]=="draft" for case in data["cases"])
    for row in rows: row.update(human_status="correct",human_credits="4",rationale="Fixture label only")
    save(); assert review.import_sheet(data,sheet,"fixture-human")==1
    case=next(case for case in data["cases"] if case["id"]==rows[0]["case_id"])
    assert case["review"]["fingerprint"]==case_fingerprint(case,data["questions_by_id"][302])
    rows[0]["answer"]="Silently changed answer"; save()
    with pytest.raises(ValueError,match="Readonly"): review.import_sheet(data,sheet,"fixture-human")


def test_human_can_reject_a_bad_rubric_without_creating_gold(tmp_path):
    review=load_script("review-judge-gold"); data=load_dataset(DATASET); sheet=tmp_path/"reject.csv"
    review.export_sheet(data,sheet,"regression",1)
    rows=list(csv.DictReader(sheet.open(encoding="utf-8-sig",newline=""),delimiter=";"))
    for row in rows: row.update(human_status="reject",rationale="Fixture: unclear criterion")
    with sheet.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=review.FIELDS,delimiter=";"); writer.writeheader(); writer.writerows(rows)
    assert review.import_sheet(data,sheet,"fixture-human")==1
    case=next(case for case in data["cases"] if case["id"]==rows[0]["case_id"])
    assert case["review"]["status"]=="rejected" and case["expected"] is None
    assert not select_cases(data,"regression")


@pytest.mark.parametrize("mutation",["leak","stale_snapshot","stale_review"])
def test_bad_dataset_versions_are_rejected(tmp_path,mutation):
    data=json.loads(DATASET.read_text(encoding="utf-8"))
    if mutation=="leak": data["cases"][0]["split"]="test"
    if mutation=="stale_snapshot": data["questions"][0]["question"] += " Different question."
    if mutation=="stale_review":
        data["cases"][0]["expected"]=data["cases"][0]["proposed_expected"]
        data["cases"][0]["review"]={"status":"approved","reviewer":"fixture","fingerprint":"stale"}
    path=tmp_path/"bad.json"; path.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(ValueError): load_dataset(path)


def test_cli_dry_run_never_calls_model_and_labels_are_not_sent(monkeypatch,tmp_path,capsys):
    cli=load_script("eval-judge"); monkeypatch.setattr(cli,"ROOT",tmp_path)
    data=load_dataset(DATASET); case=select_cases(data,include_drafts=True,limit=1)[0]
    calls=[]
    def fake_evaluate(card,answer,settings,profile):
        assert not {"expected","proposed_expected","review","kind"}.intersection(card)
        assert answer==case["answer"] and profile==case["profile"]
        calls.append(True); return oracle_result(card,case)
    monkeypatch.setattr(cli,"evaluate",fake_evaluate)
    monkeypatch.setattr("sys.argv",["eval-judge","--dataset",str(DATASET),"--include-drafts"])
    cli.main(); assert not calls and not (tmp_path/"logs").exists()
    monkeypatch.setattr("sys.argv",["eval-judge","--dataset",str(DATASET),"--include-drafts","--run","--model","fixture-model","--limit","1"])
    # Only this fixture path is allowed; no actual network request is made.
    monkeypatch.setattr(cli.Settings,"ai_enabled",property(lambda self:True))
    cli.main(); assert len(calls)==1
    reports=list((tmp_path/"logs/judge-evals").glob("*/report.json"))
    assert json.loads(reports[0].read_text(encoding="utf-8"))["metadata"]["gold_status"]=="draft_exploratory"
