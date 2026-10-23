"""Record each category's question once, with Gemini TTS on Vertex AI.

    uv run python -m pipeline.voice            # record questions that have no audio yet
    uv run python -m pipeline.voice --force    # re-record all (after changing VOICE or STYLE)

The question is the only thing the game speaks, so every clip is made ahead of
time: players hear the same voice in every browser, and play costs nothing.
"""

from __future__ import annotations

import argparse
import json
import logging

from ai_api_unified import AIFactory

from .build import CATALOG, ROOT

AUDIO = ROOT / "public" / "audio"
VOICE = "Puck"
STYLE = ("You are the warm, upbeat host of a deep-sea trivia game show, asking the contestant a question. "
         "Clear and lively, a little playful, never shouty.")


def record(force: bool = False) -> None:
    client = AIFactory.get_ai_voice_client()
    fmt = next(f for f in client.list_output_formats if f.key == "mp3_24000")
    voice = client.get_voice_by_name(VOICE)
    AUDIO.mkdir(parents=True, exist_ok=True)
    for path in sorted(CATALOG.glob("*.json")):
        if path.name == "index.json":
            continue
        out = AUDIO / f"{path.stem}.mp3"
        if out.exists() and not force:
            continue
        prompt = json.loads(path.read_text())["prompt"]
        audio = client.text_to_voice_with_emotion_prompt(
            emotion_prompt=STYLE, text_to_convert=f"{prompt}.", voice=voice, audio_format=fmt)
        out.write_bytes(audio)
        print(f"  {prompt} -> public/audio/{out.name} ({len(audio) // 1024} KB)")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    record(ap.parse_args().force)


if __name__ == "__main__":
    main()
