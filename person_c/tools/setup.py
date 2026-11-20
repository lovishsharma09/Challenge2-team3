#!/usr/bin/env python3
"""ONE-COMMAND SETUP + FIRST REAL RUN.   Run from the person_c folder:   python3 tools/setup.py

Does: venv + requests, unpacks the bundled recipe archive, downloads the nutrition CSV from the public repo,
reads the Tesseracted URL/key from the one-pager Word file in ~/Downloads (keys stay on your Mac),
asks (hidden input) for the BFL image key (optional), picks working models, runs the checks and one full run,
opens the result and writes setup_report.txt (contains NO keys - send it to your helper).
"""
import getpass, glob, os, re, subprocess, sys, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "bin" / "python"
REPORT = ROOT / "setup_report.txt"
REPO_RAW = ("https://raw.githubusercontent.com/alex83803/Hackathon-OMMAX-x-Burda/main/"
            "Challenge%202%3A%20From%20Food%20Trends%20to%20New%20%E2%80%9CDas%20schmeckt!%E2%80%9D%20Recipes%E2%80%8B/")
NUTRI_URL = REPO_RAW + "data/nutrition/Schweizer_Nahrwertdatenbank(Generische%20Lebensmittel).csv"
MODEL_FALLBACKS = ["zai-org/GLM-5.3", "zai-org/GLM-5.3-Flash", "deepseek-ai/DeepSeek-V4-Pro-0813", "moonshotai/Kimi-K3.1-Pro",
                   "Qwen/Qwen3.6-35B-A3B-FP8", "deepseek-ai/DeepSeek-V4-Flash-0731"]
log_lines: list[str] = []


def say(msg: str):
    print(msg)
    log_lines.append(re.sub(r"sk-[0-9a-zA-Z]{12,}|access_[0-9a-f-]{20,}|[A-Za-z0-9]{28,}", "[REDACTED]", msg))
    REPORT.write_text("\n".join(log_lines), encoding="utf-8")


def ensure_venv():
    if sys.prefix != sys.base_prefix or os.environ.get("SETUP_NO_VENV"):
        return
    if not VENV_PY.exists():
        say("1/7 creating virtual environment ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    subprocess.check_call([str(VENV_PY), "-m", "pip", "install", "-q", "requests"])
    os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve())] + sys.argv[1:])


def docx_text(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    return re.sub(r"<[^>]+>", " ", xml)


def find_gateway() -> tuple[str, str]:
    cands = []
    for d in (Path.home() / "Downloads", Path.home() / "Desktop", ROOT, ROOT.parent):
        cands += glob.glob(str(d / "*Tesseracted*.docx"))
    for c in cands:
        t = docx_text(c)
        u = re.search(r"https://tesseracted\.com/\S+?/ai_gateway", t)
        k = re.search(r"sk-[0-9a-zA-Z]{20,}", t)
        if u and k:
            say(f"   gateway data read from: {Path(c).name}")
            return u.group(0), k.group(0)
    return "", ""


def set_env(updates: dict):
    p = ROOT / ".env"
    if not p.exists():
        p.write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    lines, seen = p.read_text(encoding="utf-8").splitlines(), set()
    for i, l in enumerate(lines):
        k = l.split("=", 1)[0].strip()
        if k in updates and not l.lstrip().startswith("#"):
            lines[i] = f"{k}={updates[k]}"; seen.add(k)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ensure_venv()
    import requests  # noqa: F401
    os.chdir(ROOT)
    say("2/7 recipe archive ...")
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    if not (data / "rezepte_export").is_dir():
        with zipfile.ZipFile(data / "recipe_export_5000_hackathon.zip") as z:
            z.extractall(data)
    say(f"   {len(list((data / 'rezepte_export').glob('*.xml')))} recipe files ready")

    say("3/7 nutrition database ...")
    nutri = data / "nutrition.csv"
    if not nutri.exists():
        try:
            urllib.request.urlretrieve(NUTRI_URL, nutri)
        except Exception as e:
            say(f"   DOWNLOAD FAILED: {e}\n   -> open the repo, folder 'data/nutrition', download the CSV, save it as data/nutrition.csv, then run this script again.")
            return 1
    say(f"   nutrition.csv: {nutri.stat().st_size // 1024} KB")

    say("4/7 keys ...")
    url, key = find_gateway()
    if not (url and key):
        say("   Tesseracted one-pager (.docx) not found in ~/Downloads or ~/Desktop.\n   -> copy it there (name must contain 'Tesseracted') and run again.")
        return 1
    bfl = getpass.getpass("   Paste the BFL image key (hidden), or just press Enter to skip images for now: ").strip()
    upd = {"LLM_BASE_URL": url, "LLM_API_KEY": key, "NUTRITION_CSV": "data/nutrition.csv", "ARCHIVE_DIR": "data/rezepte_export"}
    if bfl:
        upd["BFL_API_KEY"] = bfl
    set_env(upd)

    say("5/7 testing the language models ...")
    sys.path.insert(0, str(ROOT / "src"))
    from dataclasses import replace
    from c_pipeline.config import Config
    from c_pipeline.llm import OpenAICompatClient
    cfg = Config.from_env()
    try:
        avail = OpenAICompatClient(replace(cfg, llm_model="x")).list_models()
        say(f"   gateway reachable, {len(avail)} models")
    except Exception as e:
        say(f"   cannot reach the gateway: {str(e)[:200]}")
        return 1
    working = []
    for m in [m for m in MODEL_FALLBACKS if m in avail] + [m for m in avail if m not in MODEL_FALLBACKS][:3]:
        try:
            out = OpenAICompatClient(replace(cfg, llm_model=m)).ping()
            say(f"   OK  {m}: {out.strip()[:30]!r}")
            working.append(m)
        except Exception as e:
            say(f"   --  {m}: {str(e)[:80]}")
        if len(working) == 2:
            break
    if not working:
        say("   no model answered -> send setup_report.txt")
        return 1
    set_env({"LLM_MODEL": working[0], "REVIEW_MODEL": working[-1]})

    say("6/7 nutrition check ...")
    r = subprocess.run([sys.executable, "run_c.py", "--check-nutrition"], capture_output=True, text=True, cwd=ROOT)
    say(r.stdout.strip() or r.stderr.strip()[-600:])

    say("7/7 full run with the mock proposal (1-3 minutes) ...")
    cmd = [sys.executable, "run_c.py", "--selection", "fixtures/mock_selection.json", "--proposals", "fixtures/mock_proposals.json"]
    if not bfl:
        cmd.append("--no-image")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    say((r.stdout.strip()[-2500:]) or "")
    if r.returncode != 0:
        say("RUN FAILED:\n" + r.stderr.strip()[-1500:])
        return 1
    card = ROOT / "output" / "cards" / "das_schmeckt_rezepte.html"
    say(f"\nDONE. Opening {card}")
    subprocess.run(["open", str(card)])
    say("Send setup_report.txt (no keys inside) and a screenshot of the opened page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
