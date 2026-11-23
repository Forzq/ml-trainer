"""Stable offline feature hashing, with an optional semantic API provider."""
import hashlib
import math
import re

import httpx

from app.core.config import Settings


class Embeddings:
    BATCH_SIZE = 64

    def __init__(self, settings: Settings):
        self.settings = settings
        self.remote = bool(settings.embedding_model and settings.openrouter_key)
        self.name = settings.embedding_model if self.remote else "hashing-char-3-5-v1"

    def encode(self, texts: list[str]) -> list[list[float]]:
        if self.remote:
            with httpx.Client(timeout=60, proxy=self.settings.openrouter_proxy_url or None) as client:
                vectors = []
                for offset in range(0, len(texts), self.BATCH_SIZE):
                    batch = texts[offset:offset + self.BATCH_SIZE]
                    response = client.post(
                        "https://openrouter.ai/api/v1/embeddings",
                        headers={"Authorization": f"Bearer {self.settings.openrouter_key}"},
                        json={"model": self.name, "input": batch},
                    )
                    response.raise_for_status()
                    rows = sorted(response.json()["data"], key=lambda row: row["index"])
                    if [row["index"] for row in rows] != list(range(len(batch))):
                        raise ValueError("Embedding provider returned unexpected vector indices")
                    vectors.extend(row["embedding"] for row in rows)
                return vectors
        return [self._hash(text) for text in texts]

    @staticmethod
    def _hash(text: str) -> list[float]:
        # A real vector baseline, intentionally lexical rather than semantic.
        text = " ".join(re.findall(r"[\w]+", text.lower().replace("ё", "е")))
        vector = [0.0] * 768
        for word in text.split():
            padded = f"^{word}$"
            for size in (3, 4, 5):
                for offset in range(max(0, len(padded) - size + 1)):
                    digest = hashlib.blake2b(padded[offset:offset + size].encode(), digest_size=8).digest()
                    index = int.from_bytes(digest[:4], "little") % len(vector)
                    vector[index] += 1 if digest[4] % 2 else -1
        norm = math.sqrt(sum(value * value for value in vector)) or 1
        return [value / norm for value in vector]
