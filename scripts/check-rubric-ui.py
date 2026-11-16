"""Test weighted AI feedback end-to-end using a local provider stub."""
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright
from app.catalog import load_cards
from app.config import Settings
from app.server import create_app

CLIENT = httpx.Client


def main():
    card = next(card for card in load_cards() if card["id"] == 302)
    received = []
    def respond(request):
        payload = json.loads(request.content); context = json.loads(payload["messages"][-1]["content"])
        received.append(context)
        rows = []
        for criterion, credit, status in zip(context["criteria"], [2, 4, 4, 0], ["partial", "correct", "correct", "incorrect"], strict=True):
            rows.append({"id": criterion["id"], "credit": credit, "status": status, "evidence": context["student_answer"][:120]})
        content = json.dumps({"feedback": "Высота, ширина и RGB объяснены верно. Батч — число изображений, обрабатываемых вместе.", "criterion_results": rows}, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    directory = ROOT / "logs/rubric-ui-check"; directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory, ignore_cleanup_errors=True) as temporary:
        settings = Settings(data_dir=Path(temporary), deepgram_key="", openai_key="", openrouter_key="test-key",
                            model="test-model", embedding_model="", qdrant_url="", qdrant_key="", tts_provider="system", fish_key="")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
        with patch("app.store.load_cards", return_value=[card]), patch("app.trainer.httpx.Client", side_effect=lambda **kwargs: CLIENT(transport=httpx.MockTransport(respond), **kwargs)):
            thread = threading.Thread(target=server.run, daemon=True); thread.start()
            for _ in range(100):
                if server.started: break
                time.sleep(.05)
            assert server.started
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="msedge", headless=True)
                    page = browser.new_page(viewport={"width":1360,"height":1000})
                    errors=[]; page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{port}")
                    expect(page.get_by_role("heading", name="Время разобраться в ML")).to_be_visible()
                    page.evaluate("state.sound=false; showStart('cv')")
                    expect(page.locator("#candidate-level")).to_have_value("Middle")
                    page.get_by_role("button", name="Начать тренировку", exact=True).last.click()
                    expect(page.locator("#answer-input")).to_be_visible()
                    assert "HWC" not in page.evaluate("state.session.question.question")
                    expect(page.locator(".optional-followups")).to_contain_text("не влияет на балл")
                    page.locator("#answer-input").fill("Изображение состоит из пикселей. RGB — три канала. Батч — размер области фильтра.")
                    page.get_by_role("button", name="Проверить ответ", exact=True).click()
                    expect(page.locator(".rubric-breakdown summary")).to_contain_text("60/100")
                    page.locator(".rubric-breakdown summary").click()
                    expect(page.locator(".rubric-row")).to_have_count(4)
                    expect(page.locator(".rubric-status.partial")).to_have_text("Частично верно")
                    expect(page.locator(".rubric-status.incorrect")).to_have_text("Неверно")
                    expect(page.locator(".rubric-status.correct")).to_have_count(2)
                    page.screenshot(path=str(ROOT/"logs/preview-weighted-rubric.png"),full_page=True)
                    page.reload()
                    expect(page.locator(".rubric-breakdown summary")).to_contain_text("60/100")
                    page.get_by_role("button", name="Завершить", exact=True).click()
                    expect(page.locator(".result-row > summary")).to_contain_text("60%")
                    page.locator(".result-row > summary").click()
                    expect(page.locator(".rubric-breakdown summary")).to_contain_text("60/100")
                    assert len(received)==1 and received[0]["candidate_level"]=="Middle"
                    assert received[0]["question_level"]=="Junior" and received[0]["followups"]
                    assert not errors, errors
                    browser.close()
            finally:
                server.should_exit=True; thread.join(timeout=10)
    print(json.dumps({"result":"passed", "checks":["Middle profile", "optional followups", "weighted partial score", "criterion statuses", "history persists rubric", "results detail"]}))


if __name__ == "__main__": main()
