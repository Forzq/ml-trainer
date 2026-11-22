"""Validate and sync the catalog to the configured Qdrant, preserving history."""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.questions.catalog import load_cards
from app.core.config import Settings
from app.storage.store import Store
from qdrant_client import QdrantClient


def history_snapshot(path):
    if not path.exists():
        return {}
    result = {}
    with sqlite3.connect(path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("sessions", "attempts", "discussions"):
            if table in tables:
                rows = db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                result[table] = {"rows": len(rows), "digest": hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-search-probes", action="store_true", help="Verify persisted cards without extra embedding requests")
    options = parser.parse_args()
    settings = Settings()
    cards = load_cards()
    print("Validated questions:", len(cards), flush=True)
    if not settings.qdrant_url:
        try:
            probe = QdrantClient(path=str(settings.data_dir / "qdrant"))
            probe.close()
        except RuntimeError:
            raise SystemExit("Close ML Trainer before importing the local Qdrant bank.") from None
    path = settings.data_dir / "history.sqlite3"
    before = history_snapshot(path)
    backup = settings.data_dir / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if path.exists() or (settings.data_dir / "qdrant").exists():
        backup.mkdir(parents=True)
        if path.exists():
            with sqlite3.connect(path) as source, sqlite3.connect(backup / "history.sqlite3") as target:
                source.backup(target)
        if not settings.qdrant_url and (settings.data_dir / "qdrant").exists():
            shutil.copytree(settings.data_dir / "qdrant", backup / "qdrant")
        print("Backup:", backup, flush=True)
    print("Syncing embeddings and Qdrant...", flush=True)
    try:
        store = Store(settings)
    except Exception as error:
        # Provider responses and credentials do not belong in diagnostic output.
        print("Import failed:", type(error).__name__, "Close ML Trainer and check the configured embeddings provider.")
        raise SystemExit(1) from None
    try:
        persisted = store.search()
        assert {card["id"] for card in persisted} == {card["id"] for card in cards}
        assert store.vectors.count(store.collection, exact=True).count == len(cards)
        assert {card["id"]: card for card in persisted} == store.by_id
        queries = {"classical_ml": "Чем precision отличается от recall?",
                   "data_science": "Что означает p-value при проверке нулевой гипотезы?",
                   "nlp": "Зачем использовать TF-IDF и как работает IDF?",
                   "cv": "Как вычислить IoU пересечения и объединения двух bounding boxes?",
                   "dl": "Чем model.eval() отличается от отключения autograd через no_grad()?",
                   "ml_system_design": "Как уложить онлайн-инференс в бюджет задержки p95?"}
        probes = {} if options.skip_search_probes else {
            topic: [card["id"] for card in store.search(query, topic=topic)[:5]]
            for topic, query in queries.items() if any(card["topic_id"] == topic for card in cards)
        }
        result = {"questions": len(persisted), "topics": dict(Counter(card["topic_id"] for card in persisted)),
                  "levels": dict(Counter(card["level"] for card in persisted)), "collection": store.collection,
                  "embeddings": store.embeddings.name, "semantic": store.embeddings.remote,
                  "search_probe_ids": probes.get("classical_ml", []), "search_probes": probes,
                  "topic_levels": {topic: dict(Counter(card["level"] for card in persisted if card["topic_id"] == topic))
                                   for topic in queries}, "backup": str(backup)}
    finally:
        store.close()
    after = history_snapshot(path)
    assert all(after.get(table) == snapshot for table, snapshot in before.items()), "Existing history changed"
    result["history_preserved"] = True
    result["history_rows"] = {table: snapshot["rows"] for table, snapshot in after.items()}
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs/question-import.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
