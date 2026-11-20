"""Text width measurement for Helvetica/Arial (A4 card layout).

The official template pre-breaks every paragraph into <span class="line"> elements with
white-space:pre, so the renderer must wrap text itself. Widths come from Liberation Sans,
which is metric-compatible with Arial/Helvetica (the template CSS disables kerning/ligatures).
"""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path

_WIDTHS_PATH = Path(__file__).resolve().parents[2] / "assets" / "helvetica_widths.json"
_DEFAULT = 556.0


@lru_cache(maxsize=1)
def _tables() -> dict:
    return json.loads(_WIDTHS_PATH.read_text(encoding="utf-8"))


def text_width(text: str, size_pt: float, bold: bool = False) -> float:
    t = _tables()["bold" if bold else "regular"]
    return sum(t.get(ch, _DEFAULT) for ch in text) * size_pt / 1000.0


_SPLIT_RE = re.compile(r"(\s+)")


def _break_long_word(word: str, max_w: float, size: float, bold: bool) -> list[str]:
    """Hard-break an over-long word with a hyphen (last resort)."""
    parts, cur = [], ""
    for ch in word:
        if text_width(cur + ch + "-", size, bold) > max_w and cur:
            parts.append(cur + "-")
            cur = ch
        else:
            cur += ch
    parts.append(cur)
    return parts


def _soft_pieces(word: str) -> list[str]:
    """Split at natural break points (after hyphen or slash) keeping the separator."""
    pieces = re.findall(r"[^-/]+[-/]?|[-/]", word)
    return pieces or [word]


def wrap_text(text: str, max_w: float, size: float, bold: bool = False, safety: float = 0.96) -> list[str]:
    """Greedy word wrap. Preserves explicit newlines. Never drops characters."""
    limit = max_w * safety
    lines: list[str] = []
    for para in text.split("\n"):
        words = [w for w in _SPLIT_RE.split(para) if w and not w.isspace()]
        cur = ""
        for w in words:
            # expand words that cannot fit on a line by themselves
            units = [w]
            if text_width(w, size, bold) > limit:
                units = []
                for piece in _soft_pieces(w):
                    if text_width(piece, size, bold) > limit:
                        units.extend(_break_long_word(piece, limit, size, bold))
                    else:
                        units.append(piece)
            for idx, u in enumerate(units):
                joiner = "" if (idx > 0) else (" " if cur else "")
                cand = cur + joiner + u
                if cur and text_width(cand, size, bold) > limit:
                    lines.append(cur)
                    cur = u
                else:
                    cur = cand
        lines.append(cur)
    return lines if lines else [""]
