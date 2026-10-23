"""Record questions with Gemini TTS on Vertex AI, once per voice and accent.

Clips live at public/audio/<voice>-<accent>/<slug>.mp3. Recording is just in
time: the page asks for each question's clip while the player answers the one
before (a clip takes about 4 seconds, a round 25 or more), which keeps Vertex
requests to about one every 30 seconds. The server records a missing clip the
first time someone asks for it, then serves the file. The
set of clips is bounded (categories x voices x accents), so the endpoint can't
be used to synthesize arbitrary text.
"""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from . import voices

AUDIO = Path(__file__).resolve().parent.parent / "public" / "audio"
STYLE = ("You are the warm, upbeat host of a deep-sea trivia game show, asking the contestant a question. "
         "Clear and lively, a little playful, never shouty.")

log = logging.getLogger(__name__)
# Vertex limits requests per minute per model. When the Pro voice model hits its
# quota, the Flash model (a separate quota) records the clip instead.
FALLBACK_MODEL = "gemini-2.5-flash-tts"
_clients: dict[str, object] = {}
_client_lock = threading.Lock()
_path_locks: dict[Path, threading.Lock] = {}
_locks_lock = threading.Lock()


def clip_path(slug: str, voice: str, accent: str) -> Path:
    return AUDIO / voices.folder(voice, accent) / f"{slug}.mp3"


def _get_client(model: str | None = None):
    with _client_lock:
        key = model or "default"
        if key not in _clients:
            from ai_api_unified import AIFactory  # imported lazily: playing needs no TTS setup

            client = AIFactory.get_ai_voice_client(voice_engine="google")
            if model:
                client.selected_model = next(m for m in client.list_models_capabilities if m.name == model)
            _clients[key] = client
        return _clients[key]


def _over_quota(exc: Exception) -> bool:
    text = str(exc)
    return getattr(exc, "code", None) == 429 or "429" in text or "Quota exceeded" in text


def _synthesize(client, prompt: str, voice: str, accent: str) -> bytes:
    lang, _, adjective = voices.ACCENTS[accent]
    selection = client.get_voice_by_name(voice).model_copy(update={"locale": lang, "language": lang})
    fmt = next(f for f in client.list_output_formats if f.key == "mp3_24000")
    return client.text_to_voice_with_emotion_prompt(
        emotion_prompt=f"{STYLE} Speak with {adjective} English accent.",
        text_to_convert=f"{prompt}.", voice=selection, audio_format=fmt)


def _lock_for(path: Path) -> threading.Lock:
    with _locks_lock:
        return _path_locks.setdefault(path, threading.Lock())


def record(slug: str, prompt: str, voice: str, accent: str, *, force: bool = False) -> Path:
    """Return the clip's path, recording it first if it doesn't exist."""
    path = clip_path(slug, voice, accent)
    with _lock_for(path):
        if path.exists() and not force:
            return path
        try:
            audio = _synthesize(_get_client(), prompt, voice, accent)
        except Exception as exc:
            if not _over_quota(exc):
                raise
            log.warning("TTS quota reached; recording %s with %s", slug, FALLBACK_MODEL)
            audio = _synthesize(_get_client(FALLBACK_MODEL), prompt, voice, accent)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(audio)
        tmp.replace(path)
        return path


PREVIEW_TEXT = "Welcome to Krillion. Here comes your first question."


def record_preview(voice: str, accent: str) -> Path:
    """A short greeting for the voice picker's Preview button."""
    return record("_preview", PREVIEW_TEXT.rstrip("."), voice, accent)
