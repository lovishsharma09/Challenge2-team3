#!/usr/bin/env bash
# One command, one page: creates the venv, installs everything, starts the prototype on http://localhost:8501
# and opens the browser.  Options:  ./run_prototype.sh --server.headless true   (no browser, e.g. for screenshots)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

if [ ! -d .venv ]; then
  echo "· creating .venv"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if [ "${PROTOTYPE_PDF:-0}" = "1" ]; then                     # optional one-click PDF export + screenshots
  python -m pip install -q playwright && python -m playwright install chromium
fi

if [ ! -f person_c/.env ] && [ ! -f .env ]; then
  echo "· no .env found: live LLM/image calls are off. Copy person_c/.env.example to person_c/.env and fill in the keys,"
  echo "  or switch on 'Demo mode' in the sidebar to replay the cached run."
fi

echo "· starting http://localhost:8501"
exec python -m streamlit run prototype/app.py --server.port 8501 --server.address localhost "$@"
