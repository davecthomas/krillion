"""Voices and accents a player can choose for the questions.

Every voice is a Gemini TTS voice. The accent sets the language code sent to
Google and is also named in the style prompt, which steers delivery more
reliably than the language code alone.
"""

from __future__ import annotations

# (id, character, gender). Character words follow Google's Gemini TTS voice list.
VOICES: list[tuple[str, str, str]] = [
    ("Achernar", "soft", "female"), ("Achird", "friendly", "male"), ("Algenib", "gravelly", "male"),
    ("Algieba", "smooth", "male"), ("Alnilam", "firm", "male"), ("Aoede", "breezy", "female"),
    ("Autonoe", "bright", "female"), ("Callirrhoe", "easy-going", "female"), ("Charon", "informative", "male"),
    ("Despina", "smooth", "female"), ("Enceladus", "breathy", "male"), ("Erinome", "clear", "female"),
    ("Fenrir", "excitable", "male"), ("Gacrux", "mature", "female"), ("Iapetus", "clear", "male"),
    ("Kore", "firm", "female"), ("Laomedeia", "upbeat", "female"), ("Leda", "youthful", "female"),
    ("Orus", "firm", "male"), ("Pulcherrima", "forward", "female"), ("Puck", "upbeat", "male"),
    ("Rasalgethi", "informative", "male"), ("Sadachbia", "lively", "male"), ("Sadaltager", "knowledgeable", "male"),
    ("Schedar", "even", "male"), ("Sulafat", "warm", "female"), ("Umbriel", "easy-going", "male"),
    ("Vindemiatrix", "gentle", "female"), ("Zephyr", "bright", "female"), ("Zubenelgenubi", "casual", "male"),
]

# id -> (language code, label, adjective for the style prompt)
ACCENTS: dict[str, tuple[str, str, str]] = {
    "us": ("en-US", "American", "an American"),
    "gb": ("en-GB", "British", "a British"),
    "au": ("en-AU", "Australian", "an Australian"),
    "in": ("en-IN", "Indian", "an Indian"),
}

DEFAULT_VOICE, DEFAULT_ACCENT = "Puck", "us"
_BY_KEY = {v[0].lower(): v[0] for v in VOICES}


def resolve(voice: str | None, accent: str | None) -> tuple[str, str]:
    """Validated (voice, accent); raises KeyError for anything not offered."""
    v = _BY_KEY[(voice or DEFAULT_VOICE).lower()]
    a = (accent or DEFAULT_ACCENT).lower()
    if a not in ACCENTS:
        raise KeyError(accent)
    return v, a


def folder(voice: str, accent: str) -> str:
    """Audio folder for one voice and accent, e.g. "puck-us"."""
    return f"{voice.lower()}-{accent}"


def options() -> dict:
    return {
        "voices": [{"id": v, "character": c, "gender": g} for v, c, g in VOICES],
        "accents": [{"id": k, "label": label, "lang": lang} for k, (lang, label, _) in ACCENTS.items()],
        "default": {"voice": DEFAULT_VOICE, "accent": DEFAULT_ACCENT},
    }
