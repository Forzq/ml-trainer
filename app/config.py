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

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openrouter_key and self.model)
