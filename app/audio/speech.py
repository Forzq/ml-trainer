"""Fish Audio speech synthesis with a bounded in-memory cache."""
import asyncio
import hashlib
import re
from collections import OrderedDict
from contextlib import aclosing

import httpx

from app.core.config import Settings, TrainerVoice

TONE_CUES = {
    "natural": "",
    "calm": "[calm]",
    "very_calm_slow": "[very calm and slowly]",
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
        self.pending: dict[str, list] = {}

    async def synthesize(self, text: str, tone: str = "natural", *, voice: TrainerVoice = "female") -> bytes:
        return b"".join([chunk async for chunk in self.stream(text, tone, voice=voice)])

    async def stream(self, text: str, tone: str = "natural", *, voice: TrainerVoice = "female"):
        settings = self.settings
        if settings.tts_provider != "fish":
            raise SpeechError(409, "Озвучка Fish Audio выключена. Укажи TTS_PROVIDER=fish в .env.")
        if not settings.fish_key:
            raise SpeechError(409, "Добавь FISH_AUDIO_API_KEY в .env и перезапусти приложение.")
        voice_id = settings.fish_voice_for(voice)
        voice_env = "FISH_AUDIO_MALE_VOICE_ID" if voice == "male" else "FISH_AUDIO_VOICE_ID"
        if not re.fullmatch(r"[a-fA-F0-9]{32}", voice_id):
            raise SpeechError(409, f"Проверь {voice_env}: нужен идентификатор голоса из 32 символов.")
        if settings.fish_model not in {"s2-pro", "s2.1-pro", "s2.1-pro-free", "drama-3"}:
            # Fish silently falls back to a paid default for an unknown model header.
            raise SpeechError(409, "Неизвестная FISH_AUDIO_MODEL. Используй s2.1-pro-free, s2.1-pro, s2-pro или drama-3.")
        text = text.strip()
        if not text or len(text) > 6000:
            raise SpeechError(422, "Для озвучки нужен текст длиной от 1 до 6000 символов.")
        if tone not in TONE_CUES:
            raise SpeechError(422, "Неизвестная интонация. Выбери один из вариантов в настройках голоса.")
        if settings.fish_latency not in {"normal", "balanced", "low"}:
            raise SpeechError(409, "Неизвестный FISH_AUDIO_LATENCY. Используй low, balanced или normal.")
        # Direct only the TTS model; chat text and LLM evaluation stay unchanged.
        synthesis_text = f"{TONE_CUES[tone]} {text}" if TONE_CUES[tone] else text
        cache_parts = (settings.fish_model, voice_id, settings.fish_latency, synthesis_text)
        key = hashlib.sha256("\0".join(cache_parts).encode()).hexdigest()
        # Deduplicate the same phrase, but never queue new speech behind an unrelated request.
        pending = self.pending.setdefault(key, [asyncio.Lock(), 0])
        if settings.beta_origin and pending[0].locked():
            raise SpeechError(409, "Эта фраза уже озвучивается. Попробуй через пару секунд.")
        pending[1] += 1
        try:
            async with pending[0]:
                async with aclosing(self._generate(key, synthesis_text, voice_id)) as stream:
                    async for chunk in stream:
                        yield chunk
        finally:
            pending[1] -= 1
            if pending[1] == 0:
                self.pending.pop(key, None)

    async def _generate(self, key: str, synthesis_text: str, voice_id: str):
        settings = self.settings
        if key in self.cache:
            self.cache.move_to_end(key)
            yield self.cache[key]
            return
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
                async with client.stream(
                    "POST", "https://api.fish.audio/v1/tts",
                    headers={"Authorization": f"Bearer {settings.fish_key}", "model": settings.fish_model},
                    json={"text": synthesis_text, "reference_id": voice_id, "format": "mp3",
                          "mp3_bitrate": 128, "normalize": True, "latency": settings.fish_latency,
                          "chunk_length": 100 if settings.fish_latency == "low" else 200 if settings.fish_latency == "balanced" else 300},
                ) as response:
                    if response.status_code != 200:
                        messages = {
                            401: "Fish Audio отклонил API-ключ. Проверь FISH_AUDIO_API_KEY.",
                            402: "Fish Audio требует доступ или баланс для выбранной модели. Проверь тариф; можно использовать FISH_AUDIO_MODEL=s2.1-pro-free, пока этот режим доступен.",
                            403: "Нет доступа к Fish Audio или выбранному голосу. Проверь ключ и доступность голоса в аккаунте.",
                            404: "Выбранный голос Fish Audio не найден. Проверь его идентификатор в .env.",
                            429: "Лимит запросов Fish Audio. Подожди немного и нажми кнопку озвучки снова.",
                        }
                        raise SpeechError(502, messages.get(response.status_code, "Fish Audio не смог озвучить текст. Проверь модель и доступность голоса."))
                    mime = response.headers.get("content-type", "").split(";")[0]
                    if mime not in {"audio/mpeg", "audio/mp3", "application/octet-stream"}:
                        raise SpeechError(502, "Fish Audio вернул неожиданный формат вместо аудио.")
                    chunks = []
                    size = 0
                    started = False
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.MAX_AUDIO_BYTES:
                            raise SpeechError(502, "Ответ озвучки слишком большой. Попробуй более короткий текст.")
                        chunks.append(chunk)
                        if not started and size >= 1024:
                            # Validate a minimal initial buffer before returning HTTP 200.
                            started = True
                            yield b"".join(chunks)
                        elif started:
                            yield chunk
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
