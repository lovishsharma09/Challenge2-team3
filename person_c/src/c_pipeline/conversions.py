"""Unit -> gram conversion with DOCUMENTED ASSUMPTIONS.

Rule of the briefing: nutritional values must not be invented without a database reference or a
documented conversion rule. Everything that is not a plain g/kg value is therefore returned
together with a rule text and a confidence factor, and is written to nutrition.json.

The tables below are common kitchen conversion approximations (assumptions, not database values).
Team can tune them in assets/conversion_assumptions.json (overrides these defaults).
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .nutrition_db import FoodEntry, normalize

ASSET = Path(__file__).resolve().parents[2] / "assets" / "conversion_assumptions.json"

# Volume of spoons in ml (DE kitchen standard)
ML_PER = {"EL": 15.0, "TL": 5.0, "cl": 10.0, "dl": 100.0, "l": 1000.0, "ml": 1.0}

# grams per spoon for common dry/viscous staples: key = normalized head word (substring match)
SPOON_G = {
    "mehl": (10, 3), "zucker": (15, 5), "salz": (18, 6), "backpulver": (12, 3), "honig": (20, 7),
    "olivenol": (12, 4), "rapsol": (12, 4), "sonnenblumenol": (12, 4), "ol": (12, 4),
    "butter": (15, 5), "kakao": (8, 2.5), "starke": (10, 3), "zimt": (6, 2), "paprika": (7, 2.5),
    "senf": (15, 5), "tomatenmark": (15, 5), "essig": (15, 5), "sojasauce": (15, 5), "sesam": (10, 3),
    "haferflocken": (7, 2), "semmelbrosel": (8, 3), "parmesan": (7, 2.5), "walnuss": (8, 3),
}
# average edible weight per piece (g): key = normalized stem
PIECE_G = {
    "ei": 55, "eier": 55, "eigelb": 18, "eiweiss": 33, "zwiebel": 80, "lauchzwiebel": 20,
    "fruhlingszwiebel": 20, "knoblauchzehe": 4, "knoblauch": 4, "schalotte": 25, "karotte": 80,
    "mohre": 80, "kartoffel": 90, "tomate": 100, "zitrone": 100, "orange": 150, "apfel": 160,
    "birne": 160, "paprika": 170, "chilischote": 10, "ingwer": 10, "lorbeerblatt": 0.3,
    "nelke": 0.1, "wacholderbeere": 0.1, "pfefferkorn": 0.05,
}
UNIT_FIXED_G = {   # unit without ingredient -> grams (tiny amounts / herbs)
    "Prise": (0.4, "Prise ≈ 0,4 g (Annahme)"),
    "Msp.": (0.6, "Messerspitze ≈ 0,6 g (Annahme)"),
    "Handvoll": (15.0, "Handvoll ≈ 15 g (Annahme)"),
    "Stiel": (1.5, "Stiel Kräuter ≈ 1,5 g (Annahme)"),
    "Zweig": (1.0, "Zweig Kräuter ≈ 1 g (Annahme)"),
    "Bund": (40.0, "Bund Kräuter ≈ 40 g (Annahme)"),
    "Zehe": (4.0, "Knoblauchzehe ≈ 4 g (Annahme)"),
}
PACK_G = {  # unit Pck./Dose without stated size -> ingredient specific
    "backpulver": 15, "vanillezucker": 8, "hefe": 42, "tomaten": 400, "kokosmilch": 400,
    "kidneybohnen": 250, "mais": 285, "kichererbsen": 265,
}
_WEIGHT_IN_TEXT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\b", re.I)


def _overrides() -> dict:
    if ASSET.exists():
        try:
            return json.loads(ASSET.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


@dataclass
class Conversion:
    grams: float | None
    rule: str
    factor: float          # confidence multiplier 0..1 (1.0 = exact, no assumption)
    assumption: bool
    basis_amount: float | None = None   # amount in the DB's basis unit (g or ml)
    basis_unit: str = "g"


def _stem(name: str) -> str:
    n = normalize(name)
    return n


def _lookup_contains(table: dict, name_norm: str):
    # longest key first so "olivenol" beats "ol"
    for k in sorted(table, key=len, reverse=True):
        if k in name_norm:
            return table[k]
    return None


def to_basis_amount(qty: float, unit: str | None, ingredient_name: str, note: str | None,
                    entry: FoodEntry) -> Conversion:
    """Convert a recipe quantity into the DB basis unit of `entry` (g or ml)."""
    ov = _overrides()
    name_n = _stem(ingredient_name)
    unit = unit or ""
    want_ml = entry.basis_unit == "ml"
    density = entry.density

    def finish(grams: float | None, rule: str, factor: float, assump: bool, ml: float | None = None) -> Conversion:
        if grams is None and ml is None:
            return Conversion(None, rule, 0.0, True)
        if want_ml:
            if ml is None:
                if density:
                    ml = grams / density
                    rule += f"; g→ml mit Dichte {density} (Datenbank)"
                else:
                    return Conversion(None, rule + "; Datenbank in ml, keine Dichte vorhanden", 0.0, True)
            elif grams is None and density:
                grams = ml * density
            return Conversion(grams, rule, factor, assump, basis_amount=ml, basis_unit="ml")
        if grams is None:
            if density:
                grams = ml * density
                rule += f"; ml→g mit Dichte {density} (Datenbank)"
            else:
                grams = ml
                rule += "; ml→g mit Dichte 1,0 (Annahme, keine Dichte in Datenbank)"
                factor *= 0.8
                assump = True
        return Conversion(grams, rule, factor, assump, basis_amount=grams, basis_unit="g")

    if unit == "g":
        return finish(qty, "direkte Grammangabe", 1.0, False)
    if unit == "kg":
        return finish(qty * 1000, "kg → g", 1.0, False)
    if unit in ("ml", "l", "cl", "dl"):
        ml = qty * ML_PER[unit]
        return finish(None, f"{qty:g} {unit} = {ml:g} ml", 1.0, False, ml=ml)
    if unit in ("EL", "TL"):
        key = _lookup_contains(ov.get("spoon_g", {}), name_n) or _lookup_contains(SPOON_G, name_n)
        if key:
            g = qty * (key[0] if unit == "EL" else key[1])
            return finish(g, f"{qty:g} {unit} {ingredient_name} ≈ {g:g} g (Küchenumrechnung, Annahme)", 0.75, True)
        ml = qty * ML_PER[unit]
        return finish(None, f"{qty:g} {unit} = {ml:g} ml (Löffelmaß); Dichte-Annahme", 0.7, True, ml=ml)
    # weight written in the ingredient name/note, e.g. "Dose (400 g)" / "Kokosmilch, 400-ml-Dose"
    if unit in ("Dose", "Pck.", "Glas", "Becher", "Stück", "Scheibe", "Blatt", "Kopf"):
        m = _WEIGHT_IN_TEXT.search(f"{ingredient_name} {note or ''}")
        if m:
            amt = float(m.group(1).replace(",", "."))
            u = m.group(2).lower()
            total = qty * amt
            if u == "kg":
                return finish(total * 1000, f"{qty:g} × {amt:g} kg laut Zutatentext", 0.95, False)
            if u == "g":
                return finish(total, f"{qty:g} × {amt:g} g laut Zutatentext", 0.95, False)
            ml = total * (1000 if u == "l" else 1)
            return finish(None, f"{qty:g} × {amt:g} {u} laut Zutatentext", 0.95, False, ml=ml)
        pk = _lookup_contains(ov.get("pack_g", {}), name_n) or _lookup_contains(PACK_G, name_n)
        if pk and unit in ("Dose", "Pck.", "Glas", "Becher"):
            return finish(qty * pk, f"{qty:g} {unit} {ingredient_name} ≈ {qty * pk:g} g (Packungsgröße, Annahme)", 0.6, True)
    if unit in UNIT_FIXED_G and not (unit == "Zehe" and "knoblauch" not in name_n):
        g, rule = UNIT_FIXED_G[unit]
        return finish(qty * g, f"{qty:g} × {rule}", 0.5, True)
    if unit in ("", "Stück", "Scheibe", "Blatt", "Kopf", "Zehe"):
        pg = _lookup_contains(ov.get("piece_g", {}), name_n) or _lookup_contains(PIECE_G, name_n)
        if pg is not None:
            return finish(qty * pg, f"{qty:g} Stück × {pg:g} g (Durchschnittsgewicht, Annahme)", 0.6, True)
    return Conversion(None, f"keine Umrechnungsregel für '{qty:g} {unit} {ingredient_name}'", 0.0, True)
