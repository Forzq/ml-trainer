"""One live OpenRouter discussion request, with synthetic data and no session/database writes."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx

from app.config import Settings
from app.trainer import discuss


def main():
    settings = Settings()
    if not settings.ai_enabled:
        raise SystemExit("Set OPENROUTER_API_KEY and OPENROUTER_MODEL in .env first.")
    card = json.loads((ROOT / "content/questions.json").read_text(encoding="utf-8"))[0]
    attempt = {
        "answer": "Переобучение — модель запоминает шум обучающих данных и хуже работает на новых данных. Его можно заметить по разрыву качества на обучении и валидации.",
        "feedback": "Ты не упомянул, что при переобучении качество на новых данных падает.",
        "discussion": [],
    }
    try:
        result = discuss(card, attempt, "Я прямо сказал, что модель хуже работает на новых данных. Перепроверь своё замечание.", settings)
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        raise SystemExit("Discussion request failed. Check the OpenRouter model, key, balance and connection.") from None
    path = ROOT / "logs/discussion-check.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Discussion reply received. Mode:", result["mode"], "Characters:", len(result["reply"]))
    print("Saved synthetic test reply:", path)


if __name__ == "__main__":
    main()
