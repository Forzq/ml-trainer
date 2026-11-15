"""Browser smoke test using installed Edge and an isolated temporary database."""
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright

from app.config import Settings
from app.server import create_app


def main():
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / ".pytest-tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / ".pytest-tmp", prefix="browser-") as temporary:
        settings = Settings(data_dir=Path(temporary), deepgram_key="", openrouter_key="", model="", embedding_model="", qdrant_url="", qdrant_key="")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.1)
            assert server.started, "Test server did not start"
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True, args=[
                    "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                ])
                context = browser.new_context(viewport={"width": 1360, "height": 1000}, permissions=["microphone"])
                context.add_init_script("localStorage.setItem('ml-sound','off')")
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url)
                expect(page.get_by_role("heading", name="Время разобраться в ML")).to_be_visible()
                assert page.locator(".topic-card").count() == 3
                page.screenshot(path=str(ROOT / "logs/preview-home.png"), full_page=True)
                page.get_by_role("button", name="Подключения", exact=True).first.click()
                expect(page.get_by_role("heading", name="Подключения", exact=True)).to_be_visible()
                page.get_by_role("button", name="Понятно").click()
                page.locator(".topic-card").first.click()
                page.locator("#session-count").select_option("2")
                page.get_by_role("button", name="Начать тренировку", exact=True).last.click()
                expect(page.locator("#answer-input")).to_be_visible()
                page.locator("#answer-input").fill("Модель запоминает шум, хуже работает на новых данных. Сравниваем с валидацией.")
                page.reload()
                expect(page.locator("#answer-input")).to_have_value("Модель запоминает шум, хуже работает на новых данных. Сравниваем с валидацией.")
                page.get_by_role("button", name="Ответить голосом", exact=True).click()
                expect(page.locator("#toast")).to_contain_text("нужен ключ Deepgram")
                page.get_by_role("button", name="Проверить ответ", exact=True).click()
                expect(page.get_by_role("button", name="Следующий вопрос", exact=True)).to_be_visible()
                expect(page.locator(".message-text").last).to_contain_text("Демо-разбор")
                page.screenshot(path=str(ROOT / "logs/preview-training.png"), full_page=True)
                page.get_by_role("button", name="Следующий вопрос", exact=True).click()
                page.get_by_role("button", name="Пока не знаю — показать объяснение").click()
                page.get_by_role("button", name="Итоги тренировки").click()
                expect(page.get_by_role("heading", name="Практика завершена")).to_be_visible()
                page.get_by_role("link", name="История", exact=True).click()
                expect(page.locator(".history-item")).to_have_count(1)
                page.get_by_role("button", name="Посмотреть", exact=True).click()
                expect(page.get_by_role("heading", name="Практика завершена")).to_be_visible()
                page.get_by_role("link", name="Банк вопросов").click()
                expect(page.locator(".question-card")).to_have_count(6)
                page.get_by_role("button", name="Метрики", exact=True).click()
                expect(page.locator(".question-card")).to_have_count(2)
                page.locator("#card-search").fill("recall")
                expect(page.locator(".question-card").first.locator("h3")).to_have_text("Precision и recall")
                # Exercise actual browser recording, with only the provider response mocked.
                def configured(route):
                    response = route.fetch()
                    config = response.json()
                    config["deepgram"] = True
                    route.fulfill(response=response, json=config)
                page.route("**/api/config", configured)
                page.route("**/api/transcribe", lambda route: route.fulfill(json={"text": "Голосовой ответ из тестовой записи"}))
                page.goto(url)
                page.get_by_role("button", name="Начать тренировку", exact=True).click()
                page.get_by_role("button", name="Начать тренировку", exact=True).last.click()
                page.get_by_role("button", name="Ответить голосом", exact=True).click()
                expect(page.get_by_role("button", name="Закончить запись", exact=True)).to_be_visible()
                page.wait_for_timeout(1200)
                page.get_by_role("button", name="Закончить запись", exact=True).click()
                expect(page.locator("#answer-input")).to_have_value("Голосовой ответ из тестовой записи")
                assert page.evaluate("state.stream === null"), "Microphone stream was not released"
                page.get_by_role("button", name="Завершить", exact=True).click()
                expect(page.get_by_role("heading", name="Практика завершена")).to_be_visible()
                page.get_by_role("button", name="На главную", exact=True).click()
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.get_by_role("heading", name="Время разобраться в ML")).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile layout overflows"
                page.screenshot(path=str(ROOT / "logs/preview-mobile.png"), full_page=True)
                assert errors == [], errors
                browser.close()
                print(json.dumps({"result": "passed", "checks": ["home", "settings", "topic session", "draft restore", "demo evaluation", "skip", "results", "history", "vector search", "microphone recording and release", "mobile layout"], "javascript_errors": errors}, ensure_ascii=False))
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    main()
