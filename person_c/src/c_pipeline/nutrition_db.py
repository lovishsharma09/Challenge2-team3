"""Loader for the Swiss Food Composition Database extract (Schweizer Nährwertdatenbank, V 7.1).

Verified file format (from the repo file header): UTF-8, ';' delimited, 144 columns, header in
row 3, decimal comma, 'k.A.' = no value, reference column 'Bezugseinheit' (e.g. 'pro 100g
essbarer Anteil'). Each nutrient column is followed by 'Herleitung des Wertes' and 'Quelle'.
"""
from __future__ import annotations
import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# nutrient key -> header prefix in the CSV
NUTRIENT_COLUMNS = {
    "kj": "Energie, Kilojoule",
    "kcal": "Energie, Kilokalorien",
    "fat_g": "Fett, total",
    "sat_fat_g": "Fettsäuren, gesättigt",
    "carbs_g": "Kohlenhydrate, verfügbar",
    "sugar_g": "Zucker (g)",
    "fiber_g": "Nahrungsfasern",
    "protein_g": "Protein (g)",
    "salt_g": "Salz (NaCl)",
}
_BASIS_RE = re.compile(r"pro\s*(\d+(?:[.,]\d+)?)\s*(g|ml)", re.I)


def parse_de_number(s: str | None) -> tuple[float | None, bool]:
    """'0,2' -> (0.2, False); '<0,1' -> (0.1, True=approx); 'k.A.'/'' -> (None, False)."""
    if s is None:
        return None, False
    t = s.strip()
    if not t or t.lower() in ("k.a.", "k. a.", "-", "n.a.", "na"):
        return None, False
    approx = False
    if t[0] in "<>~≈":
        approx, t = True, t[1:].strip()
    t = t.replace(".", "").replace(",", ".") if ("," in t) else t
    try:
        return float(t), approx
    except ValueError:
        return None, False


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("ß", "ss")
    s = re.sub(r"[()\[\]{}\"'„“”‚‘’]", " ", s)
    s = re.sub(r"[^a-z0-9äöüéèàç ,/-]", " ", s)
    s = s.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class FoodEntry:
    db_id: str
    name: str
    synonyms: list[str]
    category: str
    density: float | None
    basis_amount: float          # 100
    basis_unit: str              # 'g' or 'ml'
    basis_text: str
    nutrients: dict[str, float | None]
    approx: set[str] = field(default_factory=set)
    norm_name: str = ""
    norm_synonyms: list[str] = field(default_factory=list)


class NutritionDB:
    def __init__(self, entries: list[FoodEntry], source: str, version: str, is_fixture: bool = False):
        self.entries = entries
        self.source = source
        self.version = version
        self.is_fixture = is_fixture
        self.by_id = {e.db_id: e for e in entries}

    @classmethod
    def load(cls, path: str | Path) -> "NutritionDB":
        p = Path(path)
        text = p.read_text(encoding="utf-8-sig")
        is_fixture = text.lstrip().startswith("#SYNTHETIC")
        lines = [l for l in text.splitlines() if not l.startswith("#SYNTHETIC")]
        rows = list(csv.reader(lines, delimiter=";"))
        version = "unknown"
        if rows and rows[0] and "V " in rows[0][0]:
            m = re.search(r"V\s*([\d.]+)", rows[0][0])
            version = m.group(1) if m else version
        hdr_i = next((i for i, r in enumerate(rows[:10]) if r and r[0].strip() == "ID" and "Name" in r), None)
        if hdr_i is None:
            raise ValueError("nutrition CSV: header row (ID;...;Name;...) not found in first 10 rows")
        H = [h.strip() for h in rows[hdr_i]]

        def col(prefix: str) -> int | None:
            for i, h in enumerate(H):
                if h.startswith(prefix):
                    return i
            return None

        ci = {k: col(v) for k, v in NUTRIENT_COLUMNS.items()}
        missing = [k for k in ("kcal", "fat_g", "carbs_g", "protein_g") if ci[k] is None]
        if missing:
            raise ValueError(f"nutrition CSV: required columns not found: {missing}")
        i_id, i_name = H.index("ID"), H.index("Name")
        i_syn, i_cat = col("Synonyme"), col("Kategorie")
        i_den, i_bas = col("Dichte"), col("Bezugseinheit")
        entries: list[FoodEntry] = []
        for r in rows[hdr_i + 1:]:
            if len(r) <= i_name or not r[i_name].strip():
                continue
            basis_text = r[i_bas].strip() if i_bas is not None and i_bas < len(r) else ""
            m = _BASIS_RE.search(basis_text)
            b_amt = float(m.group(1).replace(",", ".")) if m else 100.0
            b_unit = m.group(2).lower() if m else "g"
            dens, _ = parse_de_number(r[i_den]) if i_den is not None and i_den < len(r) else (None, False)
            nutrients, approx = {}, set()
            for k, idx in ci.items():
                v, ap = parse_de_number(r[idx]) if idx is not None and idx < len(r) else (None, False)
                nutrients[k] = v
                if ap:
                    approx.add(k)
            syn_raw = r[i_syn].strip() if i_syn is not None and i_syn < len(r) else ""
            syns = [s.strip() for s in re.split(r"[;|]", syn_raw) if s.strip()] if syn_raw else []
            if len(syns) <= 1 and "," in syn_raw and syn_raw.count(",") >= 1 and ";" not in syn_raw:
                syns = [s.strip() for s in syn_raw.split(",") if s.strip()]
            e = FoodEntry(db_id=r[i_id].strip(), name=r[i_name].strip(), synonyms=syns,
                          category=(r[i_cat].strip() if i_cat is not None and i_cat < len(r) else ""),
                          density=dens, basis_amount=b_amt, basis_unit=b_unit, basis_text=basis_text,
                          nutrients=nutrients, approx=approx)
            e.norm_name = normalize(e.name)
            e.norm_synonyms = [normalize(s) for s in e.synonyms]
            entries.append(e)
        return cls(entries, source=p.name, version=version, is_fixture=is_fixture)
