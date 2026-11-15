"""One live Fish Audio request using the configured key and voice. Writes a local sample."""
import asyncio
import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.speech import Speech, SpeechError, TONE_CUES


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tone", choices=list(TONE_CUES), default="natural")
    parser.add_argument("--compare-latency", action="store_true", help="Compare two live free-tier requests: normal vs low latency")
    options = parser.parse_args()
    settings = Settings()
    if options.compare_latency and settings.fish_model != "s2.1-pro-free":
        parser.error("Latency comparison only runs on the explicitly configured free model.")
    print("Testing Fish Audio model:", settings.fish_model, flush=True)
    text = "Привет! Я твой тренер по машинному обучению. Давай разберём переобучение."
    if options.compare_latency:
        text += " Модель может запоминать шум обучающей выборки и хуже работать на новых данных. Чтобы это проверить, сравни качество на обучении и валидации. Затем попробуй регуляризацию или более простую модель."
    measurements = []
    for latency in (["normal", "low"] if options.compare_latency else [settings.fish_latency]):
        print("Starting request:", latency, flush=True)
        started = time.monotonic()
        chunks = []
        first_audio = None
        try:
            async for chunk in Speech(replace(settings, fish_latency=latency)).stream(text, options.tone):
                if first_audio is None:
                    first_audio = time.monotonic() - started
                    print("First audio:", round(first_audio, 3), "s", flush=True)
                chunks.append(chunk)
        except SpeechError as error:
            # Print no upstream body, headers or credentials.
            print("Fish Audio check failed:", error.status, error.detail)
            raise SystemExit(1) from None
        total = time.monotonic() - started
        audio = b"".join(chunks)
        name = (f"fish-latency-{latency}.mp3" if options.compare_latency else
                "fish-voice-test.mp3" if options.tone == "natural" else f"fish-voice-test-{options.tone}.mp3")
        path = ROOT / "logs" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(audio)
        measurement = {"latency": latency, "first_audio_seconds": round(first_audio, 3),
                       "complete_seconds": round(total, 3), "chunks": len(chunks), "bytes": len(audio)}
        measurements.append(measurement)
        print(json.dumps(measurement), flush=True)
        print("Sample saved:", path, flush=True)
    if options.compare_latency:
        (ROOT / "logs/speech-benchmark.json").write_text(json.dumps({"model": settings.fish_model,
            "characters": len(text), "measurements": measurements}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
