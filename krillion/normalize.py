"""Text normalization shared by the catalog pipeline and the answer matcher.

Both sides must normalize the same way, or a catalog key and a spoken answer
for the same thing will not meet.
"""

from __future__ import annotations

import re
import unicodedata

# Filler that speech recognition hands us around an answer ("um, I'll say gouda").
STOP = frozenset(
    "um uh er erm hmm uhm oh like maybe i think say guess how about what the a an "
    "is it its lets let me go with ok okay so well and of im ill my answer".split()
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm(text: str) -> str:
    """Lowercase, strip accents and punctuation, spell out + # &."""
    s = unicodedata.normalize("NFD", text.lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[’'`]", "", s)
    s = s.replace("+", " plus ").replace("#", " sharp ").replace("&", " and ")
    return _NON_ALNUM.sub(" ", s).strip()


def words(text: str) -> list[str]:
    """Normalized words with filler removed."""
    return [w for w in norm(text).split() if w and w not in STOP]


def key(text: str) -> str:
    """Spacing-insensitive lookup key: 'Blue Jay' and 'bluejay' share one."""
    return "".join(words(text))


def variants(k: str) -> list[str]:
    """The key plus naive singular forms, so 'cherries' finds 'cherry'."""
    out = [k]
    if len(k) > 3:
        if k.endswith("ies"):
            out.append(k[:-3] + "y")
        if k.endswith("es"):
            out.append(k[:-2])
        if k.endswith("s"):
            out.append(k[:-1])
    return out


def slugify(text: str) -> str:
    return "-".join(norm(text).split())
