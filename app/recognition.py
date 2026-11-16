"""Speech recognition: Deepgram first, OpenAI Whisper as an optional fallback."""
import logging

import httpx

from app.config import Settings

LOG = logging.getLogger("ml-trainer.recognition")
PROVIDER_ERRORS = (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError)
EXTENSIONS = {
    "audio/webm": "webm", "video/webm": "webm",
    "audio/mp4": "mp4", "video/mp4": "mp4",
    "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mpga": "mpga",
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
    "audio/ogg": "ogg", "application/ogg": "ogg",
    "audio/flac": "flac", "audio/x-flac": "flac",
    "audio/m4a": "m4a", "audio/x-m4a": "m4a",
}


class RecognitionError(Exception):
    """A safe user-facing error after all configured recognizers have failed."""


async def recognize_audio(raw: bytes, content_type: str, settings: Settings) -> tuple[str, str]:
    attempted = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
        if settings.deepgram_key:
            attempted.append("Deepgram")
            try:
                response = await client.post(
                    "https://api.deepgram.com/v1/listen",
                    params={"model": "nova-3", "language": "multi", "smart_format": "true"},
                    headers={"Authorization": f"Token {settings.deepgram_key}", "Content-Type": content_type},
                    content=raw,
                    # Leave time for the fallback when it is configured.
                    timeout=httpx.Timeout(30 if settings.openai_key else 90, connect=10),
                )
                response.raise_for_status()
                text = response.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
                if not isinstance(text, str):
                    raise ValueError("Invalid Deepgram transcript")
                return text, "deepgram"
            except PROVIDER_ERRORS as error:
                # Never log provider bodies, credentials or the recording.
                LOG.warning("Deepgram recognition failed (%s)", type(error).__name__)
        if settings.openai_key:
            attempted.append("Whisper")
            try:
                mime = content_type.split(";", 1)[0].strip().lower()
                extension = EXTENSIONS.get(mime, "webm")
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {settings.openai_key}"},
                    data={"model": settings.openai_transcription_model, "response_format": "json"},
                    files={"file": (f"answer.{extension}", raw, mime)},
                )
                response.raise_for_status()
                text = response.json()["text"]
                if not isinstance(text, str):
                    raise ValueError("Invalid Whisper transcript")
                return text, "whisper"
            except PROVIDER_ERRORS as error:
                LOG.warning("Whisper recognition failed (%s)", type(error).__name__)
    providers = " и ".join(attempted) or "Сервисы распознавания"
    raise RecognitionError(f"{providers}: не удалось распознать запись. Проверь API-ключи, баланс и подключение.")
