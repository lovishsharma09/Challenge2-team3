"""Configuration: paths, env loading (tiny .env reader, no extra dependency)."""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # person_c/ (or repo root after copy)


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ (existing env vars win)."""
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = re.split(r"\s+#", v, maxsplit=1)[0]            # allow trailing comments
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Config:
    # --- LLM (OpenAI-compatible chat completions; Tesseracted endpoint to be confirmed) ---
    llm_provider: str = "openai_compat"      # openai_compat | mock
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout: int = 180
    review_model: str = ""                   # independent checker model (falls back to llm_model)
    # --- Images (Black Forest Labs FLUX) ---
    bfl_api_key: str = ""
    bfl_base_url: str = "https://api.bfl.ai/v1"   # EU option: https://api.eu.bfl.ai/v1
    bfl_model: str = "flux-2-pro"                 # pinned snapshot; flux-2-pro-preview = latest
    image_size: int = 1024
    # --- Paths ---
    output_dir: Path = field(default_factory=lambda: ROOT / "output")
    nutrition_csv: Path | None = None
    template_html: Path | None = None
    brand_rules_json: Path | None = None
    archive_titles_json: Path | None = None
    # --- Workflow ---
    max_auto_revisions: int = 2
    max_editor_rounds: int = 2
    offline: bool = False                     # True = no network (mock LLM + placeholder images)

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        e = os.environ
        c = cls(
            llm_provider=e.get("LLM_PROVIDER", "openai_compat"),
            llm_base_url=e.get("LLM_BASE_URL", e.get("TESSERACTED_BASE_URL", "")),
            llm_api_key=e.get("LLM_API_KEY", e.get("TESSERACTED_API_KEY", "")),
            llm_model=e.get("LLM_MODEL", e.get("RECIPE_MODEL", "")),
            review_model=e.get("REVIEW_MODEL", ""),
            bfl_api_key=e.get("BFL_API_KEY", ""),
            bfl_base_url=e.get("BFL_BASE_URL", "https://api.bfl.ai/v1"),
            bfl_model=e.get("BFL_MODEL", "flux-2-pro"),
        )
        out = e.get("OUTPUT_DIR")
        if out:
            c.output_dir = Path(out)
        for attr, env in (("nutrition_csv", "NUTRITION_CSV"), ("template_html", "TEMPLATE_HTML"),
                          ("brand_rules_json", "BRAND_RULES_JSON"), ("archive_titles_json", "ARCHIVE_TITLES_JSON")):
            if e.get(env):
                setattr(c, attr, Path(e[env]))
        if e.get("OFFLINE", "").lower() in ("1", "true", "yes"):
            c.offline = True
            c.llm_provider = "mock"
        return c
