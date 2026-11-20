from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# To run live web research, paste the key here.
# It is ignored by git only if the value is kept in .env/secrets_local.py.
BRAVE_SEARCH_API_KEY = ""
BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def get_brave_api_key() -> str:
    environment_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if environment_key:
        return environment_key

    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                if name.strip() == "BRAVE_SEARCH_API_KEY":
                    return value.strip().strip('"').strip("'")

    try:
        from .secrets_local import BRAVE_SEARCH_API_KEY as local_key
    except ImportError:
        local_key = ""
    return (local_key or BRAVE_SEARCH_API_KEY).strip()

