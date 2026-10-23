"""Record questions with Gemini TTS on Vertex AI, once per voice and accent.

Clips live at public/audio/<voice>-<accent>/<slug>.mp3. The server records a
missing clip the first time someone asks for it, then serves the file. The
set of clips is bounded (categories x voices x accents), so the endpoint can't
be used to synthesize arbitrary text.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import voices

AUDIO = Path(__file__).resolve().parent.parent / "public" / "audio"
STYLE = ("You are the warm, upbeat host of a deep-sea trivia game show, asking the contestant a question. "
         "Clear and lively, a little playful, never shouty.")

log = logging.getLogger(__name__)
_client = None
_client_lock = threading.Lock()
_path_locks: dict[Path, threading.Lock] = {}
_locks_lock = threading.Lock()
_warming: set[str] = set()
_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="tts-warm")


def clip_path(slug: str, voice: str, accent: str) -> Path:
    return AUDIO / voices.folder(voice, accent) / f"{slug}.mp3"


def _get_client():
    global _client
    with _client_lock:
        if _client is None:
            from ai_api_unified import AIFactory  # imported lazily: playing needs no TTS setup

            _client = AIFactory.get_ai_voice_client(voice_engine="google")
        return _client


def _lock_for(path: Path) -> threading.Lock:
    with _locks_lock:
        return _path_locks.setdefault(path, threading.Lock())


def record(slug: str, prompt: str, voice: str, accent: str, *, force: bool = False) -> Path:
    """Return the clip's path, recording it first if it doesn't exist."""
    path = clip_path(slug, voice, accent)
    with _lock_for(path):
        if path.exists() and not force:
            return path
        client = _get_client()
        lang, _, adjective = voices.ACCENTS[accent]
        selection = client.get_voice_by_name(voice).model_copy(update={"locale": lang, "language": lang})
        fmt = next(f for f in client.list_output_formats if f.key == "mp3_24000")
        audio = client.text_to_voice_with_emotion_prompt(
            emotion_prompt=f"{STYLE} Speak with {adjective} English accent.",
            text_to_convert=f"{prompt}.", voice=selection, audio_format=fmt)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(audio)
        tmp.replace(path)
        return path


PREVIEW_TEXT = "Welcome to Krillion. Here comes your first question."


def record_preview(voice: str, accent: str) -> Path:
    """A short greeting for the voice picker's Preview button."""
    return record("_preview", PREVIEW_TEXT.rstrip("."), voice, accent)


def warm(voice: str, accent: str, prompts: dict[str, str]) -> bool:
    """Record a game's questions in the background, so each is ready before
    it is asked. Returns False if this voice is already warming up."""
    key = voices.folder(voice, accent) + ":" + ",".join(sorted(prompts))
    with _locks_lock:
        if key in _warming:
            return False
        _warming.add(key)

    def run() -> None:
        try:
            for slug, prompt in prompts.items():
                if not clip_path(slug, voice, accent).exists():
                    record(slug, prompt, voice, accent)
        except Exception:
            log.exception("warming %s failed", key)
        finally:
            with _locks_lock:
                _warming.discard(key)

    _pool.submit(run)
    return True
