"""Check editing of synthetic transcripts with the configured OpenRouter model."""
import asyncio
import argparse
import json
import re
import sys
import time
from dataclasses import replace
from statistics import median
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.transcription import clean_transcript


async def main():
    settings = Settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", help="Test another editor model; may be repeated")
    options = parser.parse_args()
    if not settings.transcription_enabled:
        raise SystemExit("Configure the existing OpenRouter model and key first.")
    cases = [
        ("Эээ, я бы смотрел на rock aug и pr aug, но не уверен, что понимаю разницу.",
         [r"ROC-AUC", r"PR-AUC", r"не уверен"]),
        ("Эм, precision — это доля найденных среди всех реальных положительных. Я так понимаю.",
         [r"precision.*доля найденных среди всех реальных положительных"]),
        ("Эээ, не знаю. По-моему, у L1 штраф — сумма квадратов, у L2 — сумма модулей, но я могу путать.",
         [r"не знаю", r"L1.*сумма квадратов", r"L2.*сумма модулей", r"могу путать"]),
    ]
    models = options.model or [settings.transcription_model_name]
    comparisons = []
    for model in models:
        results = []
        for raw, expected in cases:
            started = time.monotonic()
            try:
                text = await clean_transcript(raw, replace(settings, transcription_model=model), {"question": "Расскажи о метриках и регуляризации в ML.", "topic": "ML"})
                passed = all(re.search(pattern, text, re.IGNORECASE) for pattern in expected)
                passed = passed and not re.search(r"\b(?:э{2,}|эм)\b", text, re.IGNORECASE)
                result = {"raw": raw, "text": text, "seconds": round(time.monotonic() - started, 2), "passed": passed}
            except Exception as error:
                # Do not print provider response bodies, credentials or exception payloads.
                result = {"seconds": round(time.monotonic() - started, 2), "passed": False, "error": type(error).__name__}
            results.append(result)
            print(json.dumps({"model": model, **result}, ensure_ascii=True), flush=True)
        comparisons.append({"model": model, "cases": results,
                            "median_seconds": round(median(result["seconds"] for result in results), 2),
                            "passed": all(result["passed"] for result in results)})
    (ROOT / "logs").mkdir(exist_ok=True)
    filename = "transcription-benchmark.json" if options.model else "transcription-check.json"
    (ROOT / "logs" / filename).write_text(json.dumps(comparisons, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{key: value for key, value in result.items() if key != "cases"} for result in comparisons]), flush=True)
    if not all(result["passed"] for result in comparisons):
        raise SystemExit(f"Review logs/{filename}: an editing constraint was not preserved.")


if __name__ == "__main__":
    asyncio.run(main())
