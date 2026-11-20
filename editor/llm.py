"""Minimal OpenAI-compatible chat client for the Tesseracted gateway (stdlib only).

Config (environment variables, or the git-ignored .env in the repo root):
  TESSERACTED_BASE_URL, TESSERACTED_API_KEY, EDITOR_LLM_MODEL (model ids need the 'tesseracted-labs-gmbh/' prefix)
The key is only ever sent as the Authorization header and never logged or put into error messages.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_MODEL = "tesseracted-labs-gmbh/deepseek-ai/DeepSeek-V4.1-Flash"


class LLMError(RuntimeError):
    pass


def _env(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return ""


def configured() -> bool:
    return bool(_env("TESSERACTED_BASE_URL") and _env("TESSERACTED_API_KEY"))


def _http_post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise LLMError(f"gateway returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f"gateway not reachable: {type(exc).__name__}") from None


def parse_json(text: str):
    """Extract the first JSON object/array from a model reply (tolerates ```json fences and chatter)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise LLMError("model reply contains no JSON")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise LLMError(f"model reply is not valid JSON: {exc.msg}") from None
    return obj


def chat_json(system: str, user: str, *, model: str | None = None, timeout: float = 90, post=_http_post):
    if not configured():
        raise LLMError("LLM is not configured (TESSERACTED_BASE_URL / TESSERACTED_API_KEY)")
    body = {"model": model or _env("EDITOR_LLM_MODEL") or DEFAULT_MODEL, "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    headers = {"Authorization": "Bearer " + _env("TESSERACTED_API_KEY"), "Content-Type": "application/json"}
    data = post(_env("TESSERACTED_BASE_URL").rstrip("/") + "/v1/chat/completions", headers, body, timeout)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("unexpected gateway response shape") from None
    return parse_json(content)
