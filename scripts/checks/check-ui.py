"""Browser smoke test using installed Edge and an isolated temporary database."""
import json
import base64
import io
import socket
import sys
import tempfile
import threading
import time
import wave
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright

from app.core.config import Settings
from app.server import create_app


def main():
    (ROOT / "logs").mkdir(exist_ok=True)
    # Keep browser fixtures outside pytest's managed directory and its Windows ACLs.
    (ROOT / "logs/ui-check").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / "logs/ui-check", prefix="browser-", ignore_cleanup_errors=True) as temporary:
        settings = Settings(data_dir=Path(temporary), deepgram_key="", openai_key="", openrouter_key="", model="", embedding_model="", qdrant_url="", qdrant_key="", tts_provider="system", fish_key="")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            create_app(settings), host="127.0.0.1", port=port, log_level="warning",
            timeout_graceful_shutdown=3,
        ))
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
                assert page.locator(".topic-card").count() == 6
                expect(page.locator(".topic-card").filter(has_text="Системный дизайн")).to_be_visible()
                assert page.locator(".topic-card:disabled").count() == 0
                page.locator(".topic-card").filter(has_text="Системный дизайн").click()
                expect(page.locator("#session-topic")).to_have_value("ml_system_design")
                page.locator("#session-level").select_option("Middle")
                assert page.locator("#session-count option:not([disabled])").evaluate_all(
                    "options => options.map(option => Number(option.value))"
                ) == [2, 4, 6, 10, 17]
                page.locator("#session-level").select_option("all")
                page.locator("#close-start").click()
                expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                # Legacy mute must not silently disable the new default automatic narration.
                assert page.evaluate("state.sound === true")
                page.screenshot(path=str(ROOT / "logs/preview-home.png"), full_page=True)
                settings_link = page.get_by_role("link", name="Настройки", exact=True)
                overview_link = page.get_by_role("link", name="Обзор", exact=True)
                back_to_training = page.get_by_role("button", name="К тренировке", exact=True)
                settings_link.click()
                expect(page.get_by_role("heading", name="Настройки", exact=True)).to_be_visible()
                expect(settings_link).to_have_attribute("aria-current", "page")
                expect(page.locator("#auto-speech")).to_be_checked()
                page.locator("#voice-volume").evaluate("el => { el.value='35'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
                page.locator("#auto-speech").uncheck()
                page.locator("#live-silence").select_option("5000")
                page.locator("#live-sensitivity").select_option("0.025")
                page.locator("#theme-choice").select_option("light")
                expect(page.locator("html")).to_have_attribute("data-theme", "light")
                page.reload()
                expect(page.locator("html")).to_have_attribute("data-theme", "light")
                expect(page.get_by_role("heading", name="Настройки", exact=True)).to_be_visible()
                assert page.evaluate("state.volume === 0.35 && state.sound === false")
                assert page.evaluate("live.timing.silenceMs === 5000 && live.threshold === 0.025")
                expect(page.locator("#voice-volume-output")).to_have_text("35%")
                page.screenshot(path=str(ROOT / "logs/preview-light.png"), full_page=True)
                page.locator("#theme-choice").select_option("dark")
                page.reload()
                expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                expect(page.get_by_role("heading", name="Подключения", exact=True)).to_be_visible()
                page.screenshot(path=str(ROOT / "logs/preview-settings.png"), full_page=True)
                overview_link.click()
                page.locator(".topic-card").first.click()
                expect(page.locator("#prioritize-interviews")).to_be_checked()
                page.locator("#session-count").select_option("2")
                page.get_by_role("button", name="Начать тренировку", exact=True).last.click()
                expect(page.locator("#answer-input")).to_be_visible()
                expect(page.locator(".page-title .interview-frequency")).to_be_visible()
                assert page.evaluate("state.session.question.from_interview")
                page.locator("#answer-input").fill("Модель запоминает шум, хуже работает на новых данных. Сравниваем с валидацией.")
                page.reload()
                expect(page.locator("#answer-input")).to_have_value("Модель запоминает шум, хуже работает на новых данных. Сравниваем с валидацией.")
                page.get_by_role("button", name="Ответить голосом", exact=True).click()
                expect(page.locator("#toast")).to_contain_text("DEEPGRAM_API_KEY или OPENAI_API_KEY")
                answer_input = page.locator("#answer-input")
                answer_input.press("End")
                answer_input.press("Shift+Enter")
                expect(answer_input).to_have_value("Модель запоминает шум, хуже работает на новых данных. Сравниваем с валидацией.\n")
                answer_input.press("Enter")
                expect(page.get_by_role("button", name="Следующий вопрос", exact=True)).to_be_visible()
                expect(page.locator(".message-text").last).to_contain_text("Демо-разбор")
                expect(answer_input).to_be_focused()
                page.screenshot(path=str(ROOT / "logs/preview-training.png"), full_page=True)
                first_question = page.evaluate("state.session.question.id")
                expect(page.locator("#answer-input")).to_be_visible()
                page.locator("#answer-input").fill("Я уже упомянул новые данные. Почему ты считаешь ответ неполным?")
                page.reload()
                expect(page.locator("#answer-input")).to_have_value("Я уже упомянул новые данные. Почему ты считаешь ответ неполным?")
                assert page.evaluate("state.session.reviewing")
                assert page.evaluate("state.session.question.id") == first_question
                answer_input.press("Control+Enter")
                expect(page.locator("#answer-input")).to_have_value("")
                expect(page.locator(".message-text").last).to_contain_text("Демо-режим")
                expect(page.get_by_role("button", name="Следующий вопрос", exact=True)).to_be_enabled()
                page.screenshot(path=str(ROOT / "logs/preview-discussion.png"), full_page=True)
                assert page.evaluate("state.session.attempts[0].discussion.length") == 1
                page.get_by_role("button", name="Следующий вопрос", exact=True).click()
                page.wait_for_function("state.session.current_index === 1 && !state.session.reviewing")
                expect(page.locator(".message-text")).to_have_count(1)
                expect(page.locator("#answer-input")).to_have_value("")
                assert page.evaluate("state.session.question.id") != first_question
                page.get_by_role("button", name="Пока не знаю — показать объяснение").click()
                expect(page.get_by_role("button", name="Итоги тренировки")).to_be_visible()
                assert not page.evaluate("state.session.completed")
                page.locator("#answer-input").fill("Уточни ещё раз последний вопрос.")
                page.get_by_role("button", name="Отправить", exact=True).click()
                expect(page.locator("#answer-input")).to_have_value("")
                assert page.evaluate("state.session.attempts[1].discussion.length") == 1
                page.get_by_role("button", name="Итоги тренировки").click()
                expect(page.get_by_role("heading", name="Практика завершена")).to_be_visible()
                page.get_by_role("link", name="История", exact=True).click()
                expect(page.locator(".history-item")).to_have_count(1)
                page.get_by_role("button", name="Посмотреть", exact=True).click()
                expect(page.get_by_role("heading", name="Практика завершена")).to_be_visible()
                expect(page.locator(".history-discussion")).to_have_count(2)
                expect(page.locator(".history-discussion").first).to_contain_text("Я уже упомянул новые данные")
                library_requests = []
                page.on("request", lambda request: library_requests.append(request.url)
                        if urlsplit(request.url).path == "/api/cards" else None)
                library_link = page.get_by_role("link", name="Банк вопросов")
                library_link.click()
                expect(page.locator(".question-card")).to_have_count(569)
                assert len(library_requests) == 1
                overview_link.click()
                library_link.click()
                expect(page.locator(".question-card")).to_have_count(569)
                page.reload()
                expect(page.locator(".question-card")).to_have_count(569)
                assert len(library_requests) == 1
                page.evaluate("localStorage.setItem('ml-library-cards-v1', JSON.stringify({version:'old', cards:[]}))")
                page.reload()
                expect(page.locator(".question-card")).to_have_count(569)
                assert len(library_requests) == 2
                expect(page.locator(".question-card .interview-frequency")).to_have_count(569)
                expect(page.locator(".question-card").first.get_by_role("img", name="Оценка частоты на собеседованиях — очень часто, 3 из 3")).to_be_visible()
                page.locator("#card-search").fill("mock-interview")
                expect(page.locator(".question-card")).to_have_count(93)
                expect(page.locator(".question-card .tag").filter(has_text="mock-interview")).to_have_count(93)
                page.locator("#card-search").fill("github_ques")
                expect(page.locator(".question-card")).to_have_count(248)
                expect(page.locator(".question-card .tag").filter(has_text="github_ques")).to_have_count(248)
                page.locator("#card-search").fill("")
                expect(page.locator(".question-card")).to_have_count(569)
                page.screenshot(path=str(ROOT / "logs/preview-library.png"), full_page=True)
                page.get_by_role("button", name="Классический ML", exact=True).click()
                page.locator("#library-level").select_option("Senior")
                expect(page.locator(".question-card")).to_have_count(20)
                assert page.locator(".question-card-footer > .tag:first-child").all_text_contents() == ["Senior"] * 20
                page.locator("#library-level").select_option("all")
                expect(page.locator(".question-card")).to_have_count(113)
                assert len(library_requests) == 2
                with page.expect_request(lambda request: "/api/cards?q=recall&" in request.url):
                    page.locator("#card-search").fill("recall")
                expect(page.locator(".question-card h3").filter(has_text="Precision и recall")).to_have_count(1)
                assert len(library_requests) == 3
                page.locator("#card-search").fill("")
                page.get_by_role("button", name="Data Science", exact=True).click()
                expect(page.locator(".question-card")).to_have_count(113)
                page.locator("#library-level").select_option("Middle")
                expect(page.locator(".question-card")).to_have_count(47)
                page.get_by_role("button", name="NLP", exact=True).click()
                expect(page.locator(".question-card")).to_have_count(50)
                page.locator("#library-level").select_option("Senior")
                expect(page.locator(".question-card")).to_have_count(21)
                assert page.locator(".question-card .eyebrow").all_text_contents() == ["NLP"] * 21
                page.get_by_role("button", name="CV", exact=True).click()
                expect(page.locator(".question-card")).to_have_count(20)
                assert page.locator(".question-card .eyebrow").all_text_contents() == ["CV"] * 20
                page.get_by_role("button", name="DL", exact=True).click()
                page.locator("#library-level").select_option("Middle")
                expect(page.locator(".question-card")).to_have_count(41)
                assert page.locator(".question-card .eyebrow").all_text_contents() == ["DL"] * 41
                page.get_by_role("button", name="Системный дизайн", exact=True).click()
                expect(page.locator(".question-card")).to_have_count(17)
                expect(page.locator(".question-card h3").filter(has_text="Скоринг при лимите одобрений")).to_be_visible()
                page.locator("#card-search").fill("mock-interview")
                expect(page.locator(".question-card")).to_have_count(9)
                page.locator("#card-search").fill("")
                # Exercise actual browser recording, with only the provider response mocked.
                def configured(route):
                    response = route.fetch()
                    config = response.json()
                    config["deepgram"] = False
                    config["whisper"] = True
                    route.fulfill(response=response, json=config)
                page.route("**/api/config", configured)
                transcriptions = []
                def transcription_response(route):
                    transcriptions.append(route.request.post_data_buffer.decode("utf-8", errors="replace"))
                    if len(transcriptions) == 1:
                        route.fulfill(json={"text": "Я сравню ROC-AUC и PR-AUC, но не уверен.",
                                            "raw_text": "Ээ, я сравню rock aug и pr aug, но не уверен.", "cleanup": "applied", "provider": "whisper"})
                    else:
                        route.fulfill(json={"text": "Эм, это моя оговорка.", "raw_text": "Эм, это моя оговорка.", "cleanup": "unavailable", "provider": "whisper"})
                page.route("**/api/transcribe", transcription_response)
                page.goto(url)
                settings_link.click()
                expect(page.locator(".connection").filter(has_text="OpenAI Whisper")).to_contain_text("Настроен")
                overview_link.click()
                page.get_by_role("button", name="Начать тренировку", exact=True).click()
                page.locator("#session-topic").select_option("cv")
                page.locator("#session-level").select_option("Middle")
                page.get_by_role("button", name="Начать тренировку", exact=True).last.click()
                page.wait_for_function("state.session?.question?.level === 'Middle' && state.session?.question?.topic_id === 'cv'")
                assert page.evaluate("state.session.question.level") == "Middle"
                assert page.evaluate("state.session.question.topic_id") == "cv"
                page.locator("#answer-input").fill("Мой пример:")
                page.get_by_role("button", name="Ответить голосом", exact=True).click()
                expect(page.get_by_role("button", name="Закончить запись", exact=True)).to_be_visible()
                page.wait_for_timeout(1200)
                page.get_by_role("button", name="Закончить запись", exact=True).click()
                expect(page.locator("#answer-input")).to_have_value("Мой пример: Я сравню ROC-AUC и PR-AUC, но не уверен.")
                expect(page.locator("#toast")).to_contain_text("Использован Whisper")
                expect(page.locator("#transcription-review")).to_contain_text("Ээ, я сравню rock aug и pr aug, но не уверен.")
                page.locator("#transcription-review summary").click()
                expect(page.locator("#transcription-review p")).to_be_visible()
                assert 'name="session_id"' in transcriptions[0] and 'name="question_id"' in transcriptions[0]
                page.get_by_role("button", name="Ответить голосом", exact=True).click()
                expect(page.get_by_role("button", name="Закончить запись", exact=True)).to_be_visible()
                page.wait_for_timeout(500)
                page.get_by_role("button", name="Закончить запись", exact=True).click()
                expect(page.locator("#answer-input")).to_have_value("Мой пример: Я сравню ROC-AUC и PR-AUC, но не уверен. Эм, это моя оговорка.")
                expect(page.locator("#toast")).to_contain_text("очистка недоступна")
                expect(page.locator("#transcription-review")).to_have_count(0)
                assert page.evaluate("state.stream === null"), "Microphone stream was not released"
                # Validate the Fish playback path without making paid provider requests.
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(b"\0" * (24000 * 2 * 3))
                wav_bytes = buffer.getvalue()
                spoken_texts = []
                spoken_tones = []
                spoken_voices = []
                def speech_response(route):
                    spoken_texts.append(route.request.post_data_json["text"])
                    spoken_tones.append(route.request.post_data_json["tone"])
                    spoken_voices.append(route.request.post_data_json["voice"])
                    route.fulfill(body=wav_bytes, content_type="audio/wav")
                page.route("**/api/speech", speech_response)
                page.evaluate("state.config.tts = {provider:'fish', ready:true, voice_id:'1db1618b6eaf4571ac7db70e20eb6727', model:'s2.1-pro-free'}; syncVoiceControls()")
                settings_link.click()
                page.get_by_role("button", name="Послушать голос", exact=True).click()
                page.wait_for_function("speech.status === 'playing'")
                assert page.evaluate("speech.audio && !speech.audio.paused")
                assert page.evaluate("speech.audio.volume === 0.35")
                calls_before_volume = len(spoken_texts)
                page.locator("#voice-volume").evaluate("el => { el.value='15'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
                assert page.evaluate("speech.audio.volume === 0.15")
                assert len(spoken_texts) == calls_before_volume
                page.locator("#speech-indicator").click()
                assert page.evaluate("speech.audio === null && speech.objectUrl === null && speech.status === 'idle'")
                before_tone = len(spoken_texts)
                page.locator("#trainer-voice").select_option("male")
                assert page.evaluate("localStorage.getItem('ml-trainer-voice') === 'male'")
                page.locator("#voice-tone").select_option("very_calm_slow")
                page.screenshot(path=str(ROOT / "logs/preview-voice-controls.png"), full_page=True)
                assert len(spoken_texts) == before_tone, "Selecting a tone must not send a synthesis request"
                page.locator(".voice-preview").click()
                page.wait_for_function("speech.status === 'playing'")
                assert spoken_tones[-1] == "very_calm_slow"
                assert spoken_voices[-1] == "male" and "Я подготовил вопрос" in spoken_texts[-1]
                page.locator("#speech-indicator").click()
                # A delayed response that ignores AbortSignal must not start audio after cancellation.
                page.evaluate("""() => {
                    window.fishOriginalFetch = window.fetch;
                    window.fetch = (input, options) => String(input).includes('/api/speech')
                        ? new Promise(resolve => { window.resolveLateSpeech = resolve; })
                        : window.fishOriginalFetch(input, options);
                    speak('test delayed audio', {force:true});
                }""")
                page.wait_for_function("speech.status === 'loading' && Boolean(window.resolveLateSpeech)")
                page.locator("#speech-indicator").click()
                page.evaluate("""encoded => {
                    const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
                    window.resolveLateSpeech(new Response(bytes, {headers:{'Content-Type':'audio/wav'}}));
                    window.fetch = window.fishOriginalFetch;
                }""", base64.b64encode(wav_bytes).decode())
                page.wait_for_timeout(150)
                assert page.evaluate("speech.audio === null && speech.status === 'idle'")
                # Submit an answer and assert feedback starts without a replay-button click.
                page.locator("#auto-speech").check()
                back_to_training.click()
                requests_before_answer = len(spoken_texts)
                page.get_by_role("button", name="Проверить ответ", exact=True).click()
                expect(page.get_by_role("button", name="Следующий вопрос", exact=True)).to_be_visible()
                page.wait_for_function("speech.status === 'playing'")
                feedback = page.evaluate("state.session.attempts[state.session.attempts.length-1].feedback")
                assert len(spoken_texts) == requests_before_answer + 1
                assert spoken_texts[-1] == feedback
                assert spoken_tones[-1] == "very_calm_slow"
                assert page.evaluate("speech.audio.volume === 0.15")
                page.locator("#answer-input").fill("Не согласен с замечанием. Объясни, что именно я упустил.")
                page.get_by_role("button", name="Отправить", exact=True).click()
                expect(page.locator("#answer-input")).to_have_value("")
                page.wait_for_function("speech.status === 'playing'")
                feedback = page.evaluate("state.session.attempts[state.session.attempts.length-1].discussion.slice(-1)[0].reply")
                assert spoken_texts[-1] == feedback
                expect(page.get_by_role("button", name="Следующий вопрос", exact=True)).to_be_enabled()
                page.locator('[data-action="toggle-sound"]').click()
                assert page.evaluate("speech.status === 'idle'")
                page.get_by_role("button", name="Озвучить сообщение", exact=True).last.click()
                page.wait_for_function("speech.status === 'playing'")
                assert spoken_texts[-1] == feedback
                assert page.evaluate("state.sound === false"), "Manual replay must not turn automatic narration on"
                page.locator("#speech-indicator").click()
                settings_link.click()
                page.locator("#voice-volume").evaluate("el => { el.value='0'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
                back_to_training.click()
                before_zero = len(spoken_texts)
                page.get_by_role("button", name="Озвучить сообщение", exact=True).last.click()
                expect(page.locator("#toast")).to_contain_text("0%")
                assert len(spoken_texts) == before_zero
                settings_link.click()
                page.locator("#voice-volume").evaluate("el => { el.value='15'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
                back_to_training.click()
                page.get_by_role("button", name="Завершить", exact=True).click()
                expect(page.get_by_role("heading", name="Практика завершена")).to_be_visible()
                page.reload()
                expect(page.get_by_role("heading", name="Практика завершена")).to_be_visible()
                assert page.evaluate("state.volume === 0.15 && state.sound === false && state.tone === 'very_calm_slow'")
                page.set_viewport_size({"width": 320, "height": 640})
                assert page.locator(".result-numbers").evaluate("row => row.scrollWidth <= row.clientWidth")
                page.get_by_role("button", name="На главную", exact=True).click()
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.get_by_role("heading", name="Время разобраться в ML")).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile layout overflows"
                page.screenshot(path=str(ROOT / "logs/preview-mobile.png"), full_page=True)
                settings_link.click()
                expect(page.get_by_role("heading", name="Настройки", exact=True)).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile settings overflow"
                assert page.locator("#theme-choice").evaluate("select => parseFloat(getComputedStyle(select).paddingRight) >= 32")
                page.set_viewport_size({"width": 320, "height": 640})
                page.locator('[data-page="library"]').click()
                expect(page.locator(".question-card").first).to_be_visible()
                expect(page.locator(".question-card > p").first).to_have_css("font-size", "15px")
                for selector in (".page-title", ".level-filter"):
                    assert page.locator(selector).evaluate("block => block.scrollWidth <= block.clientWidth"), selector
                page.set_viewport_size({"width": 390, "height": 844})
                overview_link.click()
                # More than one history page must not truncate the home counters.
                before_stats = httpx.get(url + "/api/stats").json()
                with server.config.app.state.store.connect() as db:
                    oldest_session = db.execute("SELECT id FROM sessions ORDER BY created_at, rowid LIMIT 1").fetchone()[0]
                    feedback = json.dumps({"feedback": "Проверочный разбор", "covered": [], "missing": []})
                    for index in range(32):
                        session_id = f"pagination-{index}"
                        db.execute("INSERT INTO sessions(id,topic,question_ids,completed_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
                                   (session_id, "classical_ml", "[1]"))
                        db.execute("INSERT INTO attempts(session_id,question_id,answer,feedback,score,mode) VALUES(?,?,?,?,?,?)",
                                   (session_id, 1, "Проверочный ответ", feedback, 50, "demo"))
                page.reload()
                expect(page.locator(".metric strong").nth(1)).to_have_text(str(before_stats["answered"] + 32))
                expect(page.locator(".metric strong").nth(2)).to_have_text(str(before_stats["completed"] + 32))
                page.get_by_role("link", name="История", exact=True).click()
                expect(page.locator(".history-item")).to_have_count(30)
                expect(page.locator(".history-page-info")).to_contain_text("Страница 1 из 2")
                expect(page.get_by_role("button", name="Предыдущая страница истории")).to_be_disabled()
                page.get_by_role("button", name="Следующая страница истории").click()
                expect(page.locator(".history-item")).to_have_count(before_stats["sessions"] + 2)
                expect(page.locator(".history-page-info")).to_contain_text("Страница 2 из 2")
                expect(page.get_by_role("button", name="Следующая страница истории")).to_be_disabled()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "History pagination overflows"
                page.screenshot(path=str(ROOT / "logs/preview-history-mobile.png"), full_page=True)
                page.locator(f'[data-action="open-session"][data-id="{oldest_session}"]').click()
                expect(page.get_by_role("heading", name="Практика завершена")).to_be_visible()
                expect(page.locator(".history-discussion")).to_have_count(2)
                page.get_by_role("link", name="История", exact=True).click()
                expect(page.locator(".history-page-info")).to_contain_text("Страница 2 из 2")
                page.get_by_role("button", name="Предыдущая страница истории").click()
                expect(page.locator(".history-item")).to_have_count(30)
                expect(page.locator(".history-page-info")).to_contain_text("Страница 1 из 2")
                page.set_viewport_size({"width": 1360, "height": 1000})
                page.screenshot(path=str(ROOT / "logs/preview-history.png"), full_page=True)
                page.get_by_role("link", name="Обзор", exact=True).click()
                expect(page.get_by_role("heading", name="Время разобраться в ML")).to_be_visible()
                page.get_by_role("button", name="Начать тренировку", exact=True).click()
                page.locator("#session-topic").select_option("all")
                page.locator("#session-level").select_option("Junior")
                page.locator("#session-count").select_option("20")
                page.get_by_role("button", name="Начать тренировку", exact=True).last.click()
                page.wait_for_function("state.session?.total === 20 && state.session?.topic === 'all'")
                session_id = page.evaluate("state.session.id")
                store = server.config.app.state.store
                with store.connect() as db:
                    ids = json.loads(db.execute("SELECT question_ids FROM sessions WHERE id=?", (session_id,)).fetchone()[0])
                cards = [store.by_id[question_id] for question_id in ids]
                topic_counts = Counter(card["topic_id"] for card in cards)
                assert set(topic_counts) == {topic["id"] for topic in page.evaluate("state.config.topics")}
                assert max(topic_counts.values()) - min(topic_counts.values()) <= 1
                assert all(card["level"] == "Junior" for card in cards)
                first_topic = page.evaluate("state.session.question.topic_id")
                page.get_by_role("button", name="Пока не знаю — показать объяснение").click()
                expect(page.get_by_role("button", name="Следующий вопрос", exact=True)).to_be_visible()
                page.get_by_role("button", name="Следующий вопрос", exact=True).click()
                page.wait_for_function("state.session.current_index === 1")
                assert page.evaluate("state.session.question.topic_id") != first_topic
                assert errors == [], errors
                browser.close()
                print(json.dumps({"result": "passed", "checks": ["dark default", "theme switching and persistence", "home", "settings", "topic session", "draft restore", "demo evaluation", "skip", "results", "history", "vector search", "microphone recording and release", "Fish playback and stop", "late TTS response cancellation", "automatic feedback narration", "manual replay while auto off", "live volume without new request", "zero volume", "voice preferences persistence", "mobile layout", "global counters beyond 30 sessions", "history pagination and old session replay", "balanced all-topic session"], "javascript_errors": errors}, ensure_ascii=False))
        finally:
            server.should_exit = True
            thread.join(timeout=30)
            assert not thread.is_alive(), "Test server did not shut down"


if __name__ == "__main__":
    main()
