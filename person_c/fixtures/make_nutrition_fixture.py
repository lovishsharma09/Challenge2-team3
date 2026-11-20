"""Generates fixtures/nutrition_mini_SYNTHETIC.csv in the REAL file layout (title row, empty row,
header row with the real 144 column names, ';' delimiter, decimal comma, 'k.A.').

!!! ALL NUMBERS ARE SYNTHETIC APPROXIMATIONS FOR UNIT TESTS ONLY - NOT SWISS DATABASE VALUES !!!
The loader flags such a file (first line '#SYNTHETIC') and every output is marked TESTDATEN.
"""
import csv
import io
from pathlib import Path

HEADER = ("ID;ID V 4.0;ID SwissFIR;Name;Synonyme;Kategorie;Dichte;Bezugseinheit;Energie, Kilojoule (kJ);Herleitung des Wertes;Quelle;"
          "Energie, Kilokalorien (kcal);Herleitung des Wertes;Quelle;Fett, total (g);Herleitung des Wertes;Quelle;"
          "Fettsäuren, gesättigt (g);Herleitung des Wertes;Quelle;Fettsäuren, einfach ungesättigt (g);Herleitung des Wertes;Quelle;"
          "Fettsäuren, mehrfach ungesättigt (g);Herleitung des Wertes;Quelle;Linolsäure (g);Herleitung des Wertes;Quelle;"
          "Alpha-Linolensäure (g);Herleitung des Wertes;Quelle;Eicosapentaensäure (EPA) (g);Herleitung des Wertes;Quelle;"
          "Docosahexaensäure (DHA) (g);Herleitung des Wertes;Quelle;Cholesterin (mg);Herleitung des Wertes;Quelle;"
          "Kohlenhydrate, verfügbar (g);Herleitung des Wertes;Quelle;Zucker (g);Herleitung des Wertes;Quelle;"
          "Stärke (g);Herleitung des Wertes;Quelle;Nahrungsfasern (g);Herleitung des Wertes;Quelle;Protein (g);Herleitung des Wertes;Quelle;"
          "Salz (NaCl) (g);Herleitung des Wertes;Quelle;Alkohol (g);Herleitung des Wertes;Quelle;Wasser (g);Herleitung des Wertes;Quelle;"
          "Geänderter Eintrag")
COLS = HEADER.split(";")
IDX = {k: COLS.index(v) for k, v in {
    "kj": "Energie, Kilojoule (kJ)", "kcal": "Energie, Kilokalorien (kcal)", "fat": "Fett, total (g)",
    "sat": "Fettsäuren, gesättigt (g)", "carb": "Kohlenhydrate, verfügbar (g)", "sugar": "Zucker (g)",
    "fiber": "Nahrungsfasern (g)", "prot": "Protein (g)", "salt": "Salz (NaCl) (g)"}.items()}

# name; synonyms; category; density; basis; kJ; kcal; fat; sat; carb; sugar; fiber; protein; salt
ROWS = [
    ("Butter", "", "Milchprodukte/Fette", "", "pro 100g essbarer Anteil", 3050, 741, 83, 52, 0.6, 0.6, 0, 0.7, 0.02),
    ("Lachs, roh", "Atlantischer Lachs", "Fisch/Süsswasser", "", "pro 100g essbarer Anteil", 830, 200, 13, 2.5, 0, 0, 0, 20, 0.1),
    ("Weisswein, trocken", "Weißwein", "Getränke/Alkoholisch", "0,99", "pro 100ml", 290, 70, 0, 0, 1.5, 1.0, 0, 0.1, 0.0),
    ("Frühlingszwiebel", "Lauchzwiebel;Schnittzwiebel", "Gemüse", "", "pro 100g essbarer Anteil", 125, 30, 0.3, 0.1, 5, 2.3, 2.6, 1.8, 0.01),
    ("Petersilie, frisch", "Petersilienblatt", "Gewürze/Kräuter", "", "pro 100g essbarer Anteil", 190, 45, 0.8, 0.1, 6, "k.A.", 5, 4, 0.1),
    ("Grünkohl, roh", "Federkohl;Krauskohl", "Gemüse", "", "pro 100g essbarer Anteil", 155, 37, 0.9, 0.1, 2.5, 1, 4, 4.3, 0.1),
    ("Kartoffel, roh", "Erdapfel", "Gemüse", "", "pro 100g essbarer Anteil", 305, 72, 0.1, 0, 15, 0.8, 2, 2, 0.0),
    ("Zwiebel, roh", "", "Gemüse", "", "pro 100g essbarer Anteil", 120, 28, 0.2, 0, 5, 4, 1.6, 1.2, 0.01),
    ("Knoblauch, roh", "", "Gemüse", "", "pro 100g essbarer Anteil", 590, 140, 0.4, 0.1, 28, 1, 2, 6, 0.04),
    ("Olivenöl", "Öl, Olive", "Fette/Öle", "0,92", "pro 100ml", 3400, 828, 92, 13, 0, 0, 0, 0, 0),
    ("Gemüsebrühe", "Bouillon, Gemüse", "Suppen/Brühen", "1,0", "pro 100ml", 20, 5, 0.1, 0, 0.8, 0.5, 0, 0.2, 0.9),
    ("Vollrahm", "Sahne;Rahm 35%", "Milchprodukte", "1,0", "pro 100ml", 1380, 335, 35, 22, 3, 3, 0, 2.2, 0.1),
    ("Hühnerei, ganz, roh", "Ei;Vollei", "Eier", "", "pro 100g essbarer Anteil", 600, 143, 9.5, 2.8, 0.7, 0.7, 0, 12.5, 0.4),
    ("Weizenmehl, weiss", "Mehl;Weissmehl", "Getreide/Mehle", "", "pro 100g essbarer Anteil", 1450, 340, 1, 0.2, 71, 1, 3.5, 10, 0.0),
    ("Baumnuss", "Walnuss", "Nüsse", "", "pro 100g essbarer Anteil", 2800, 680, 65, 6, 3, 2.5, 6, 15, 0.0),
    ("Zitronensaft", "Saft, Zitrone", "Früchte/Säfte", "1,03", "pro 100ml", 100, 25, 0, 0, 2.5, 2.4, 0, 0.4, 0.0),
    ("Parmesan", "Parmigiano", "Käse", "", "pro 100g essbarer Anteil", 1650, 400, 28, 18, 0, 0, 0, 36, 1.8),
    ("Teigwaren, trocken", "Pasta;Spaghetti;Penne", "Getreide/Teigwaren", "", "pro 100g essbarer Anteil", 1500, 355, 1.5, 0.3, 72, 3, 3, 12, 0.02),
    ("Entenbrust, mit Haut, roh", "Entenfleisch", "Fleisch/Geflügel", "", "pro 100g essbarer Anteil", 1000, 240, 19, 5, 0, 0, 0, 18, 0.2),
    ("Zucker, weiss", "Haushaltszucker;Kristallzucker", "Zucker/Süsswaren", "", "pro 100g essbarer Anteil", 1700, 400, 0, 0, 100, 100, 0, 0, 0),
    ("Kochsalz", "Salz;Speisesalz", "Gewürze/Salz", "", "pro 100g essbarer Anteil", 0, 0, 0, 0, 0, 0, 0, 0, 100),
    ("Bratapfel-Konserve", "", "Früchte/Konserven", "", "pro 100g essbarer Anteil", 300, 70, 0.2, 0, 16, 15, 1.5, 0.3, 0.0),
]


def build() -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    buf.write("#SYNTHETIC FIXTURE - values are made-up approximations for unit tests only\n")
    w.writerow(["Schweizer Nährwertdatenbank – Generische Lebensmittel V 7.1 (SYNTHETISCHE TESTFIXTURE)"] + [""] * 143)
    w.writerow([""] * 144)
    w.writerow(COLS)
    for i, r in enumerate(ROWS, 1):
        name, syn, cat, dens, basis, kj, kcal, fat, sat, carb, sugar, fiber, prot, salt = r
        cells = ["k.A."] * len(COLS)
        cells[0] = str(90000 + i); cells[1] = ""; cells[2] = ""
        cells[3], cells[4], cells[5], cells[6], cells[7] = name, syn, cat, dens.replace(".", ","), basis
        for key, val in zip(["kj", "kcal", "fat", "sat", "carb", "sugar", "fiber", "prot", "salt"],
                            [kj, kcal, fat, sat, carb, sugar, fiber, prot, salt]):
            cells[IDX[key]] = val if isinstance(val, str) else str(val).replace(".", ",")
        cells[-1] = "Nein"
        w.writerow(cells)
    return buf.getvalue()


if __name__ == "__main__":
    out = Path(__file__).parent / "nutrition_mini_SYNTHETIC.csv"
    out.write_text(build(), encoding="utf-8")
    print("wrote", out, len(ROWS), "rows")
