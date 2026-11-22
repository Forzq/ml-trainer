import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

TrainerVoice = Literal["female", "male"]


@dataclass
class Settings:
    data_dir: Path = ROOT / "data"
    deepgram_key: str = os.getenv("DEEPGRAM_API_KEY", "")
    openai_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_transcription_model: str = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1") or "whisper-1"
    openrouter_key: str = os.getenv("OPENROUTER_API_KEY", "")
    model: str = os.getenv("OPENROUTER_MODEL", "")
    transcription_model: str = os.getenv("OPENROUTER_TRANSCRIPTION_MODEL", "")
    embedding_model: str = os.getenv("OPENROUTER_EMBEDDING_MODEL", "")
    qdrant_url: str = os.getenv("QDRANT_URL", "")
    qdrant_key: str = os.getenv("QDRANT_API_KEY", "")
    tts_provider: str = os.getenv("TTS_PROVIDER", "fish" if os.getenv("FISH_AUDIO_API_KEY") else "system")
    fish_key: str = os.getenv("FISH_AUDIO_API_KEY", "")
    fish_voice_id: str = os.getenv("FISH_AUDIO_VOICE_ID", "1db1618b6eaf4571ac7db70e20eb6727")
    fish_model: str = os.getenv("FISH_AUDIO_MODEL", "s2.1-pro-free")
    fish_latency: str = os.getenv("FISH_AUDIO_LATENCY", "low")
    fish_male_voice_id: str = os.getenv("FISH_AUDIO_MALE_VOICE_ID") or "de9a2c99fcee4dfbbaec90327eab36d8"

    def fish_voice_for(self, voice: TrainerVoice) -> str:
        return self.fish_male_voice_id if voice == "male" else self.fish_voice_id

    @property
    def stt_enabled(self) -> bool:
        return bool(self.deepgram_key or self.openai_key)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openrouter_key and self.model)

    @property
    def transcription_model_name(self) -> str:
        return self.transcription_model or self.model

    @property
    def transcription_enabled(self) -> bool:
        return bool(self.openrouter_key and self.transcription_model_name)

    @property
    def fish_enabled(self) -> bool:
        return self.tts_provider == "fish" and bool(self.fish_key and self.fish_voice_id)
