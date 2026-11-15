import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    data_dir: Path = ROOT / "data"
    deepgram_key: str = os.getenv("DEEPGRAM_API_KEY", "")
    openrouter_key: str = os.getenv("OPENROUTER_API_KEY", "")
    model: str = os.getenv("OPENROUTER_MODEL", "")
    embedding_model: str = os.getenv("OPENROUTER_EMBEDDING_MODEL", "")
    qdrant_url: str = os.getenv("QDRANT_URL", "")
    qdrant_key: str = os.getenv("QDRANT_API_KEY", "")
    tts_provider: str = os.getenv("TTS_PROVIDER", "fish" if os.getenv("FISH_AUDIO_API_KEY") else "system")
    fish_key: str = os.getenv("FISH_AUDIO_API_KEY", "")
    fish_voice_id: str = os.getenv("FISH_AUDIO_VOICE_ID", "1db1618b6eaf4571ac7db70e20eb6727")
    fish_model: str = os.getenv("FISH_AUDIO_MODEL", "s2.1-pro-free")

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openrouter_key and self.model)

    @property
    def fish_enabled(self) -> bool:
        return self.tts_provider == "fish" and bool(self.fish_key and self.fish_voice_id)
