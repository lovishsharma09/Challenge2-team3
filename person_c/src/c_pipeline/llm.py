"""LLM client. OpenAI-compatible chat completions (configurable base URL / key / model).

The Tesseracted Labs endpoint is NOT documented in the briefing deck: set LLM_BASE_URL,
LLM_API_KEY and LLM_MODEL from the key page, then run `python run_c.py --ping`.
A deterministic MockClient (LLM_PROVIDER=mock / OFFLINE=1) lets the whole stage run without network.
"""
from __future__ import annotations
import base64
import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any, Callable

import requests

from .config import Config, ROOT


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply (handles ``` fences and leading/trailing prose)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise LLMError("no JSON found in model reply")
    opener = t[start]
    closer = "}" if opener == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return json.loads(t[start:i + 1])
    raise LLMError("unterminated JSON in model reply")


class OpenAICompatClient:
    def __init__(self, cfg: Config):
        if not (cfg.llm_base_url and cfg.llm_model):
            raise LLMError("LLM_BASE_URL and LLM_MODEL must be set (see .env.example)")
        self.cfg = cfg
        self._json_mode_ok = True
        self.calls = 0
        self.total_seconds = 0.0

    def _url(self) -> str:
        """Gateway base URL -> .../v1/chat/completions (the Tesseracted base URL has no /v1 suffix)."""
        b = self.cfg.llm_base_url.rstrip("/")
        if b.endswith("/chat/completions"):
            return b
        if not b.endswith("/v1"):
            b += "/v1"
        return b + "/chat/completions"

    def list_models(self) -> list[str]:
        url = self._url().rsplit("/chat/completions", 1)[0] + "/models"
        h = {"Authorization": f"Bearer {self.cfg.llm_api_key}"} if self.cfg.llm_api_key else {}
        r = requests.get(url, headers=h, timeout=30)
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
        return sorted(m.get("id", "") for m in r.json().get("data", []))

    def chat(self, messages: list[dict], *, temperature: float = 0.4, json_mode: bool = False,
             max_tokens: int | None = None, model: str | None = None) -> str:
        payload: dict[str, Any] = {"model": model or self.cfg.llm_model, "messages": messages, "temperature": temperature}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if json_mode and self._json_mode_ok:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.cfg.llm_api_key:
            headers["Authorization"] = f"Bearer {self.cfg.llm_api_key}"
        last = None
        for attempt in range(3):
            t0 = time.time()
            try:
                r = requests.post(self._url(), headers=headers, json=payload, timeout=self.cfg.llm_timeout)
            except requests.RequestException as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
                continue
            self.total_seconds += time.time() - t0
            if r.status_code == 400 and "response_format" in payload:
                self._json_mode_ok = False          # endpoint does not support JSON mode: retry without
                payload.pop("response_format", None)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            self.calls += 1
            data = r.json()
            try:
                return data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError) as e:
                raise LLMError(f"unexpected response shape: {str(data)[:300]}") from e
        raise LLMError(f"LLM request failed after retries: {last}")

    def chat_json(self, system: str, user: str, *, validate: Callable[[Any], list[str]] | None = None,
                  retries: int = 2, temperature: float = 0.4, model: str | None = None) -> Any:
        """Ask for JSON, parse, validate; on failure send the errors back and retry."""
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        err_text = ""
        for attempt in range(retries + 1):
            reply = self.chat(msgs, temperature=temperature, json_mode=True, model=model)
            try:
                obj = extract_json(reply)
                problems = validate(obj) if validate else []
                if not problems:
                    return obj
                err_text = "; ".join(problems[:12])
            except (LLMError, json.JSONDecodeError) as e:
                err_text = f"invalid JSON: {e}"
            msgs += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": f"Your reply was rejected: {err_text}. "
                                                   "Return ONLY the corrected complete JSON object."}]
        raise LLMError(f"model did not return valid JSON after {retries + 1} attempts: {err_text}")

    def chat_vision_json(self, system: str, text: str, image_path: str | Path, *,
                         validate: Callable[[Any], list[str]] | None = None, retries: int = 1,
                         temperature: float = 0.0, model: str | None = None) -> Any:
        """Same as chat_json but with a picture attached (OpenAI-compatible content parts, base64 data URI).

        Raises LLMError when the model/endpoint cannot do vision – the caller decides whether to try another model.
        """
        p = Path(image_path)
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        uri = f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"
        content = [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": uri}}]
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        err_text = ""
        for attempt in range(retries + 1):
            reply = self.chat(msgs, temperature=temperature, json_mode=True, model=model)
            try:
                obj = extract_json(reply)
                problems = validate(obj) if validate else []
                if not problems:
                    return obj
                err_text = "; ".join(problems[:12])
            except (LLMError, json.JSONDecodeError) as e:
                err_text = f"invalid JSON: {e}"
            msgs += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": f"Your reply was rejected: {err_text}. "
                                                   "Return ONLY the corrected complete JSON object."}]
        raise LLMError(f"vision model did not return valid JSON after {retries + 1} attempts: {err_text}")

    def ping(self) -> str:
        return self.chat([{"role": "user", "content": "Antworte nur mit dem Wort: bereit"}], temperature=0, max_tokens=10)


class MockClient:
    """Deterministic offline client. Replies are read from fixtures/mock_llm/<task>.json.

    The task name is taken from a line 'TASK: <name>' in the user prompt. Fixtures may be a dict
    (returned for every call) or a list (returned in order, last one repeats) so the mock can
    demonstrate the review/revise loop.
    """
    def __init__(self, fixture_dir: Path | None = None):
        self.dir = fixture_dir or (ROOT / "fixtures" / "mock_llm")
        self._counters: dict[str, int] = {}
        self.calls = 0
        self.total_seconds = 0.0

    def chat_json(self, system: str, user: str, *, validate=None, retries: int = 2, temperature: float = 0.4) -> Any:
        m = re.search(r"^TASK:\s*([a-z_]+(?::[A-Za-z0-9_\-]+)?)", user, re.M)
        if not m:
            raise LLMError("mock: no TASK line in prompt")
        task = m.group(1)
        fname = task.replace(":", "__") + ".json"
        path = self.dir / fname
        if not path.exists():
            base = task.split(":")[0]
            path = self.dir / (base + ".json")
        if not path.exists():
            raise LLMError(f"mock: no fixture for task {task}")
        data = json.loads(path.read_text(encoding="utf-8"))
        n = self._counters.get(task, 0)
        self._counters[task] = n + 1
        self.calls += 1
        obj = data[min(n, len(data) - 1)] if isinstance(data, list) else data
        if validate:
            problems = validate(obj)
            if problems:
                raise LLMError(f"mock fixture {path.name} invalid: {problems[:5]}")
        return obj

    def chat_vision_json(self, system: str, text: str, image_path, *, validate=None, retries: int = 1,
                         temperature: float = 0.0, model: str | None = None) -> Any:
        """Offline vision: the picture is ignored, the reply comes from fixtures/mock_llm/<task>.json like chat_json."""
        return self.chat_json(system, text, validate=validate, retries=retries, temperature=temperature)

    def chat(self, messages, **kw) -> str:
        return "bereit"

    def ping(self) -> str:
        return "bereit (mock)"


def get_client(cfg: Config):
    if cfg.llm_provider == "mock" or cfg.offline:
        return MockClient()
    return OpenAICompatClient(cfg)
