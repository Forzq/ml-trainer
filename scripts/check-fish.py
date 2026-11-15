"""One live Fish Audio request using the configured key and voice. Writes a local sample."""
import asyncio
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.speech import Speech, SpeechError, TONE_CUES


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tone", choices=list(TONE_CUES), default="natural")
    options = parser.parse_args()
    settings = Settings()
    print("Testing Fish Audio model:", settings.fish_model)
    try:
        audio = await Speech(settings).synthesize(
            "Привет! Я твой тренер по машинному обучению. Давай разберём переобучение.", options.tone
        )
    except SpeechError as error:
        # Print no upstream body, headers or credentials.
        print("Fish Audio check failed:", error.status, error.detail)
        raise SystemExit(1) from None
    name = "fish-voice-test.mp3" if options.tone == "natural" else f"fish-voice-test-{options.tone}.mp3"
    path = ROOT / "logs" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(audio)
    print("Audio received:", len(audio), "bytes")
    print("Sample saved:", path)


if __name__ == "__main__":
    asyncio.run(main())
