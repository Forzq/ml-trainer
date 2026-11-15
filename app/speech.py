"""Fish Audio speech synthesis with a bounded in-memory cache."""
import asyncio
import hashlib
import re
from collections import OrderedDict

import httpx

from app.config import Settings

TONE_CUES = {
    "natural": "",
    "calm": "[calm]",
    "friendly": "[friendly]",
    "excited": "[excited]",
    "soft": "[soft tone]",
    "whisper": "[whispering]",
}


class SpeechError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


class Speech:
    MAX_CACHE_BYTES = 16 * 1024 * 1024
    MAX_AUDIO_BYTES = 8 * 1024 * 1024

    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache: OrderedDict[str, bytes] = OrderedDict()
        self.cache_bytes = 0
        self.lock = asyncio.Lock()

    async def synthesize(self, text: str, tone: str = "natural") -> bytes:
        settings = self.settings
        if settings.tts_provider != "fish":
            raise SpeechError(409, "Озвучка Fish Audio выключена. Укажи TTS_PROVIDER=fish в .env.")
        if not settings.fish_key:
            raise SpeechError(409, "Добавь FISH_AUDIO_API_KEY в .env и перезапусти приложение.")
        if not re.fullmatch(r"[a-fA-F0-9]{32}", settings.fish_voice_id):
            raise SpeechError(409, "Проверь FISH_AUDIO_VOICE_ID: нужен идентификатор голоса из 32 символов.")
        if settings.fish_model not in {"s2-pro", "s2.1-pro", "s2.1-pro-free", "drama-3"}:
            # Fish silently falls back to a paid default for an unknown model header.
            raise SpeechError(409, "Неизвестная FISH_AUDIO_MODEL. Используй s2.1-pro-free, s2.1-pro, s2-pro или drama-3.")
        text = text.strip()
        if not text or len(text) > 6000:
            raise SpeechError(422, "Для озвучки нужен текст длиной от 1 до 6000 символов.")
        if tone not in TONE_CUES:
            raise SpeechError(422, "Неизвестная интонация. Выбери один из вариантов в настройках голоса.")
        # Direct only the TTS model; chat text and LLM evaluation stay unchanged.
        synthesis_text = f"{TONE_CUES[tone]} {text}" if TONE_CUES[tone] else text
        key = hashlib.sha256((settings.fish_model + "\0" + settings.fish_voice_id + "\0" + synthesis_text).encode()).hexdigest()
        async with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
                    async with client.stream(
                        "POST", "https://api.fish.audio/v1/tts",
                        headers={"Authorization": f"Bearer {settings.fish_key}", "model": settings.fish_model},
                        json={"text": synthesis_text, "reference_id": settings.fish_voice_id, "format": "mp3",
                              "mp3_bitrate": 128, "normalize": True, "latency": "normal"},
                    ) as response:
                        if response.status_code != 200:
                            messages = {
                                401: "Fish Audio отклонил API-ключ. Проверь FISH_AUDIO_API_KEY.",
                                402: "Fish Audio требует доступ или баланс для выбранной модели. Проверь тариф; можно использовать FISH_AUDIO_MODEL=s2.1-pro-free, пока этот режим доступен.",
                                403: "Нет доступа к Fish Audio или выбранному голосу. Проверь ключ и доступность голоса в аккаунте.",
                                404: "Голос Fish Audio не найден. Проверь FISH_AUDIO_VOICE_ID.",
                                429: "Лимит запросов Fish Audio. Подожди немного и нажми кнопку озвучки снова.",
                            }
                            raise SpeechError(502, messages.get(response.status_code, "Fish Audio не смог озвучить текст. Проверь модель и доступность голоса."))
                        mime = response.headers.get("content-type", "").split(";")[0]
                        if mime not in {"audio/mpeg", "audio/mp3", "application/octet-stream"}:
                            raise SpeechError(502, "Fish Audio вернул неожиданный формат вместо аудио.")
                        chunks = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self.MAX_AUDIO_BYTES:
                                raise SpeechError(502, "Ответ озвучки слишком большой. Попробуй более короткий текст.")
                            chunks.append(chunk)
                        audio = b"".join(chunks)
                        if len(audio) < 1024:
                            raise SpeechError(502, "Fish Audio вернул пустую или слишком короткую запись. Проверь доступность выбранного голоса и модели, затем повтори озвучку.")
            except httpx.TimeoutException:
                raise SpeechError(504, "Fish Audio не ответил вовремя. Можно повторить озвучку кнопкой рядом с сообщением.") from None
            except httpx.RequestError:
                raise SpeechError(502, "Нет соединения с Fish Audio. Проверь интернет и повтори озвучку.") from None
            while self.cache and (len(self.cache) >= 32 or self.cache_bytes + len(audio) > self.MAX_CACHE_BYTES):
                _, removed = self.cache.popitem(last=False)
                self.cache_bytes -= len(removed)
            self.cache[key] = audio
            self.cache_bytes += len(audio)
            return audio
