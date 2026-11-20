"""Stage 09 – HTML renderer: fills the "das schmeckt!" A4 card layout in code.

The official template (A4-v5) is a fixed layout for ONE recipe: every element is absolutely positioned and
every line pre-broken. The requirements ask for a template that takes ANY recipe (variable number of
ingredients/steps/text lengths), ideally 1 A4 page, up to 2-3 pages, each follow-up page with header,
recipe reference, footer and correct page count; steps kept together, over-long steps split sensibly.

This module reproduces the template's design (same coordinates, colours, type sizes, element classes) and adds
the missing piece: real pagination. Lines are broken by us (textmetrics) exactly like the template does, so
printing is deterministic. Content fidelity: nothing is invented, converted or shortened.
"""
from __future__ import annotations
import base64
import html
import mimetypes
import re
from pathlib import Path

from .textmetrics import wrap_text

# ----------------------------------------------------------------------------- geometry (pt)
PAGE_W, PAGE_H = 595.28, 841.89
ML, CW = 34.02, 527.236
RIGHT = ML + CW
LEFT_X, LEFT_W = ML, 158.0
LEFT_IN_X, LEFT_IN_W = 46.02, 134.0
RIGHT_X, RIGHT_W = 215.02, 346.236
BOTTOM = 790.0
COL_TOP_1 = 299.0           # first page, below the title block
COL_TOP_N = 120.0           # follow-up pages
GREEN, DARK, YELLOW = "#006642", "#183e30", "#fff04b"
TEXT, MUTED, RULE, SOFT = "#28332d", "#647169", "#d8ded5", "#edf2e9"
TAGLINE = "Gut einkaufen. Mit Freude kochen."
AI_LABEL = "KI-generierter Rezeptentwurf"
AI_CAPTION = "KI-generierte Illustration · kein Originalfoto aus dem Archiv"

_LEADING_PREFIX = re.compile(r"^(ca\.|etwa|etwas|evtl\.|nach belieben|.*\bvon)$", re.I)
_NOTE_BARE = re.compile(r"^(zum|zur|zu|für|nach|evtl|optional|oder|und|ca\.|frisch|am besten)\b", re.I)


# ----------------------------------------------------------------------------- formatting
def fmt_amount(q: float | None) -> str:
    if q is None or q == "":
        return ""
    try:
        q = float(q)
    except (TypeError, ValueError):
        return str(q).strip()          # archive free text such as "etwas" – kept as stored
    whole, frac = int(q // 1), round(q - int(q // 1), 3)
    glyph = {0.25: "¼", 0.5: "½", 0.75: "¾"}.get(frac)
    if frac == 0:
        return f"{whole:d}"
    if glyph:
        return f"{whole} {glyph}" if whole else glyph
    return f"{q:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def ingredient_line(ing: dict) -> str:
    """'40 g Butter', '2 Eier (Größe M)', 'ca. 100 g Feta', '1 EL Öl zum Braten'. Content as stored."""
    parts = []
    prefix = (ing.get("prefix") or "").strip()
    lead = bool(prefix) and bool(_LEADING_PREFIX.match(prefix))
    if lead:
        parts.append(prefix)
    q = fmt_amount(ing.get("quantity"))
    if q:
        qt = fmt_amount(ing.get("quantity_to"))
        parts.append(f"{q}–{qt}" if qt else q)
    if ing.get("unit"):
        parts.append(ing["unit"])
    if prefix and not lead:
        parts.append(prefix)
    parts.append(ing["name"])
    line = " ".join(parts)
    note = (ing.get("note") or "").strip()
    if note:
        line += " " + (note if note.startswith("(") or _NOTE_BARE.match(note) else f"({note})")
    return line


def wrap_items(items: list[str], width: float, size: float, sep: str = "  ·  ") -> list[str]:
    """Pack whole items (e.g. 'Fett: 12 g') into lines so a value is never split from its unit."""
    from .textmetrics import text_width
    lines, cur = [], ""
    for it in items:
        cand = it if not cur else cur + sep + it
        if cur and text_width(cand, size) > width * 0.985:
            lines.append(cur)
            cur = it
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def meta_line(r: dict) -> str:
    parts = []
    if r.get("times_list"):
        parts += [f"{t['name']}: {int(t['duration'])} Min." for t in r["times_list"] if t.get("duration")]
    else:
        t = r.get("times") or {}
        for key, label in (("prep_min", "Zubereitung"), ("cook_min", "Garzeit"), ("rest_min", "Ruhezeit")):
            if t.get(key):
                parts.append(f"{label}: {int(t[key])} Min.")
    sv = r.get("servings") or {}
    if sv.get("amount"):
        parts.append(f"{fmt_amount(sv['amount'])} {sv.get('unit') or 'Portionen'}")
    return " · ".join(parts)


NUTRI_ROWS = [  # the five values shown on the official template (all values stay in nutrition.json)
    ("kcal", "Energie", "kcal"), ("kj", "Energie", "kJ"), ("fat_g", "Fett", "g"),
    ("carbs_g", "Kohlenhydrate", "g"), ("protein_g", "Eiweiß", "g"),
]
ARCHIVE_NUTRI = [("calories", "Energie", "kcal"), ("kilojoule", "Energie", "kJ"), ("fat", "Fett", "g"),
                 ("carbonhydrates", "Kohlenhydrate", "g"), ("protein", "Eiweiß", "g")]


def nutrition_block(r: dict, nutrition: dict | None) -> tuple[list[str], list[str]]:
    """-> (note lines text, value lines text). Never labels a value 'pro Portion' without a reference."""
    if nutrition and nutrition.get("incomplete"):
        names = ", ".join(u["original"] for u in nutrition.get("unmatched", []))
        return [f"Nährwerte pro Portion nicht angegeben: für {names} liegt kein Datenbanktreffer vor."], []
    if nutrition and nutrition.get("per_serving"):
        ps = nutrition["per_serving"]
        vals = []
        for k, label, unit in NUTRI_ROWS:
            v = ps.get(k)
            if v is not None:
                vals.append(f"{label}: {fmt_amount(v) if isinstance(v, int) else str(v).replace('.', ',')} {unit}")
        cov = nutrition.get("coverage", {})
        note = (f"Pro Portion, berechnet (Schweizer Nährwertdatenbank), Näherungswerte. "
                f"{cov.get('ingredients_calculated', '?')} von {cov.get('ingredients_needing_calc', '?')} Zutaten "
                f"berücksichtigt (Qualität: {cov.get('quality', '?')}).")
        approx = [r["original"] for r in nutrition.get("ingredients", []) if r.get("match") == "closest_category"]
        if approx:
            note += " Nur näherungsweise zugeordnet (nächstliegender Eintrag, Annahme): " + ", ".join(approx) + "."
        if nutrition.get("db", {}).get("synthetic_fixture"):
            note = "TESTDATEN – keine echten Datenbankwerte. " + note
        return [note], vals
    an = r.get("archive_nutrition")
    if an:
        vals = [f"{label}: {an[k]:g} {unit}".replace(".", ",") for k, label, unit in ARCHIVE_NUTRI if an.get(k) is not None]
        return ["Angaben aus dem Archiv; Bezugsmenge nicht angegeben."], vals
    return [], []


# ----------------------------------------------------------------------------- element builders
def _px(v: float) -> str:
    return f"{v:.3f}pt"


def _style(x, y, w, h, extra="") -> str:
    return f"left:{_px(x)};top:{_px(y)};width:{_px(w)};height:{_px(h)};{extra}"


def _lines(lines: list[str]) -> str:
    return "".join(f'<span class="line">{html.escape(l)}</span>' for l in lines)


def el_box(x, y, w, h, bg) -> str:
    return f'<div class="element" style="{_style(x, y, w, h, f"background:{bg}")}"></div>'


def el_text(tag, x, y, w, lines, size, lh, weight=400, color=TEXT, align=None, extra_cls="") -> str:
    h = lh * max(len(lines), 1)
    al = f"text-align:{align};" if align else ""
    return (f'<{tag} class="element text{extra_cls}" style="{_style(x, y, w, h, f"font-size:{size}pt;line-height:{lh}pt;font-weight:{weight};color:{color};{al}")}">'
            f"{_lines(lines)}</{tag}>")


# ----------------------------------------------------------------------------- blocks + pagination
class Block:
    def __init__(self, h, render, kind="item", keep_next=False, cont_header=None):
        self.h, self.render, self.kind, self.keep_next, self.cont_header = h, render, kind, keep_next, cont_header


def _flow(blocks: list[Block], top1: float, cont_header_h: float, make_cont_header) -> list[list[tuple[float, Block]]]:
    """Place blocks top-to-bottom into pages. Returns pages -> [(y, block)]. y absolute."""
    pages: list[list[tuple[float, Block]]] = [[]]
    y = top1
    i = 0
    while i < len(blocks):
        b = blocks[i]
        need = b.h + (blocks[i + 1].h if b.keep_next and i + 1 < len(blocks) else 0)
        top = top1 if len(pages) == 1 else COL_TOP_N
        if y + need > BOTTOM and pages[-1]:
            pages.append([])
            y = COL_TOP_N
            if b.cont_header and make_cont_header:
                hb = make_cont_header(b.cont_header)
                pages[-1].append((y, hb))
                y += hb.h
        pages[-1].append((y, b))
        y += b.h
        i += 1
    return pages


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9])", text.strip())
    return [p for p in parts if p]


# ----------------------------------------------------------------------------- recipe -> pages
def _layout(r: dict, nutrition: dict | None, image_uri: str | None, logo_uri: str | None, ai_generated: bool, D: dict) -> list[str]:
    """One layout attempt with density parameters D. Returns page HTML strings."""
    title = r["title"].strip()
    # ---------------- title block (page 1)
    t_size, t_lh = 29.0, 31.0
    t_lines = wrap_text(title, 331.236, t_size, True)
    if len(t_lines) > 2:
        t_size, t_lh = 23.0, 25.0
        t_lines = wrap_text(title, 331.236, t_size, True)
    left_bottom = 86 + t_lh * len(t_lines)
    meta_y = left_bottom + 12
    m_lines = wrap_text(meta_line(r), 331.236, 9.2, True)
    left_bottom = meta_y + 13 * len(m_lines)
    badge_y = left_bottom + 8
    if ai_generated:
        left_bottom = badge_y + 17
    intro = (r.get("intro") or "").strip()
    intro_lines = wrap_text(intro, 331.236, D["intro_size"]) if intro else []
    intro_y = left_bottom + 12
    if intro_lines:
        left_bottom = intro_y + D["intro_lh"] * len(intro_lines)
    IMG = D["img"]
    IX, CAP_Y = RIGHT - IMG, 86 + IMG + 5
    cap_lines = wrap_text(AI_CAPTION if ai_generated else "Abbildung aus dem Archiv", IMG, 7.0)
    cap_bottom = CAP_Y + 9 * len(cap_lines)
    col_top = max(COL_TOP_1 - (174 - IMG), left_bottom + 14, cap_bottom + 16)

    # ---------------- left column blocks (ingredients, nutrition)
    ing_w = LEFT_IN_W - 16
    left_blocks: list[Block] = []
    sv = r.get("servings") or {}
    head_h = D["head_h"]
    left_blocks.append(Block(head_h, lambda y, sv=sv: (
        el_text("h2", LEFT_IN_X, y + D["head_a"], LEFT_IN_W, ["Zutaten"], 16, 20, 700, DARK) +
        el_text("p", LEFT_IN_X, y + D["head_b"], LEFT_IN_W, [f"Für {fmt_amount(sv.get('amount'))} {sv.get('unit') or 'Portionen'}"], 9.2, 12.5, 400, MUTED)),
        "head", keep_next=True))
    last_group = object()
    for ing in r["ingredients"]:
        grp = ing.get("group")
        if grp != last_group and grp:
            g_lines = wrap_text(grp, LEFT_IN_W, 9.2, True)
            left_blocks.append(Block(13.5 * len(g_lines) + D["grp_pad"], lambda y, gl=g_lines: el_text("h3", LEFT_IN_X, y + 4, LEFT_IN_W, gl, 9.2, 13.5, 700, DARK),
                                     "group", keep_next=True, cont_header="Zutaten"))
        last_group = grp
        lines = wrap_text(ingredient_line(ing), ing_w, D["ing_size"])
        h = D["ing_lh"] * len(lines) + D["ing_gap"]
        left_blocks.append(Block(h, lambda y, ls=lines: (
            f'<label class="element text ingredient" style="{_style(LEFT_IN_X, y, LEFT_IN_W, D["ing_lh"] * len(ls), f"font-size:{D['ing_size']}pt;line-height:{D['ing_lh']}pt;font-weight:400;color:{TEXT};")}">'
            f'<input type="checkbox" aria-label="Zutat abhaken"><span class="ingredient-copy">{_lines(ls)}</span></label>'),
            "ing", cont_header="Zutaten"))
    notes, vals = nutrition_block(r, nutrition)
    source_lines = (wrap_text("Quelle: KI-generierter Rezeptentwurf, redaktionell zu prüfen.", LEFT_IN_W, 7.5)
                    if ai_generated else
                    wrap_text(f"Rezeptquelle: XML-Archivexport „{title}“.", LEFT_IN_W, 7.5))
    nutri_left = nutri_right = None
    if vals or notes:
        n_lines = [l for n in notes for l in wrap_text(n, LEFT_IN_W, 7.7)]
        nb_h = 20 + 10 * len(n_lines) + 8 + D["nut_lh"] * len(vals) + 8 + 10 * len(source_lines) + 14

        def draw_nutri(y, nl=n_lines, vs=vals, sl=source_lines):
            out = el_text("h2", LEFT_IN_X, y, LEFT_IN_W, ["Nährwerte"], 11, 14, 700, DARK)
            yy = y + 20
            if nl:
                out += el_text("p", LEFT_IN_X, yy, LEFT_IN_W, nl, 7.7, 10, 400, MUTED)
                yy += 10 * len(nl) + 8.6
            if vs:
                out += el_text("p", LEFT_IN_X, yy, LEFT_IN_W, vs, 8.7, D["nut_lh"], 400, TEXT)
                yy += D["nut_lh"] * len(vs) + 8
            return out + el_text("p", LEFT_IN_X, yy, LEFT_IN_W, sl, 7.5, 10, 400, MUTED)
        nutri_left = Block(nb_h + 14, draw_nutri, "nutri")
        # compact horizontal band for the (usually emptier) right column
        band_vals = wrap_items(vals, RIGHT_W - 24, 8.7)
        band_note = [l for n in notes for l in wrap_text(n, RIGHT_W - 24, 7.7)]
        band_src = wrap_text(" ".join(["Quelle: KI-generierter Rezeptentwurf, redaktionell zu prüfen."
                                       if ai_generated else f"Rezeptquelle: XML-Archivexport „{title}“."]), RIGHT_W - 24, 7.5)
        band_h = 10 + 15 + 12 * len(band_note) + 4 + 13 * len(band_vals) + 6 + 10 * len(band_src) + 10

        def draw_band(y, bv=band_vals, bn=band_note, bs=band_src, bh=band_h):
            out = el_box(RIGHT_X, y + 12, RIGHT_W, bh, "#f4f6f1") + el_box(RIGHT_X, y + 12, RIGHT_W, 0.8, RULE)
            yy = y + 22
            out += el_text("h3", RIGHT_X + 12, yy, RIGHT_W - 24, ["Nährwerte"], 11, 14, 700, DARK)
            yy += 19
            out += el_text("p", RIGHT_X + 12, yy, RIGHT_W - 24, bn, 7.7, 12, 400, MUTED)
            yy += 12 * len(bn) + 4
            out += el_text("p", RIGHT_X + 12, yy, RIGHT_W - 24, bv, 8.7, 13, 400, TEXT)
            yy += 13 * len(bv) + 6
            return out + el_text("p", RIGHT_X + 12, yy, RIGHT_W - 24, bs, 7.5, 10, 400, MUTED)
        nutri_right = Block(band_h + 14, draw_band, "nutri")
    else:
        nutri_left = Block(10 * len(source_lines) + 24, lambda y, sl=source_lines: el_text("p", LEFT_IN_X, y + 14, LEFT_IN_W, sl, 7.5, 10, 400, MUTED), "nutri")

    # ---------------- right column blocks (steps, tip)
    st_w = RIGHT_X + RIGHT_W - 245.02
    st_size, st_lh, st_gap = D["st_size"], D["st_lh"], D["st_gap"]
    right_blocks: list[Block] = [Block(33, lambda y: el_text("h2", RIGHT_X, y, RIGHT_W, ["Zubereitung"], 16, 20, 700, DARK), "head", keep_next=True)]
    num = 0
    last_sg = object()
    page_cap = BOTTOM - COL_TOP_N - 36          # usable height on a follow-up page
    for st in r["steps"]:
        sg = st.get("group")
        if sg and sg != last_sg:
            right_blocks.append(Block(20, lambda y, g=sg: el_text("h3", RIGHT_X, y + 2, RIGHT_W, [g], 10.2, 14, 700, DARK), "group", keep_next=True, cont_header="Zubereitung"))
        last_sg = sg
        num += 1
        lines = wrap_text(st["text"].strip(), st_w, st_size)
        if st_lh * len(lines) + st_gap > page_cap * 0.9:
            # over-long step: split at sentence boundaries into chunks that fit a page
            chunks, cur = [], ""
            for sent in _split_sentences(st["text"]):
                cand = (cur + " " + sent).strip()
                if cur and st_lh * len(wrap_text(cand, st_w, st_size)) > page_cap * 0.6:
                    chunks.append(cur); cur = sent
                else:
                    cur = cand
            chunks.append(cur)
            for ci, ch in enumerate(chunks):
                cl = wrap_text(ch, st_w, st_size)
                right_blocks.append(_step_block(num if ci == 0 else None, cl, st_lh, st_gap, st_size))
            continue
        right_blocks.append(_step_block(num, lines, st_lh, st_gap, st_size))
    tips = r.get("tips") or ([{"headline": "Unser Tipp", "content": r["serving_tip"]}] if r.get("serving_tip") else [])
    for tip in tips:
        tip = dict(tip, content=re.sub(r"^\s*Unser Tipp\s*:\s*", "", tip["content"]))     # heading is already printed
        tl = wrap_text(tip["content"], 334.236, D["tip_size"])
        head = tip.get("headline") or "Unser Tipp"
        hl = wrap_text(head, 326.0, 9.2, True)
        h_box = 10 + 13 * len(hl) + 3 + D["tip_lh"] * len(tl) + 12
        right_blocks.append(Block(h_box + D["tip_after"], lambda y, hl=hl, tl=tl, hb=h_box: (
            el_box(RIGHT_X, y, RIGHT_W, hb, SOFT) + el_box(RIGHT_X, y, 2.0, hb, GREEN) +
            el_text("h3", RIGHT_X + 12, y + 10, 334.236, hl, 9.2, 13, 700, DARK) +
            el_text("p", RIGHT_X + 12, y + 10 + 13 * len(hl) + 3, 334.236, tl, D["tip_size"], D["tip_lh"], 400, TEXT)), "tip"))

    # ---------------- flow both columns
    def cont_header_builder(label):
        return Block(32, lambda y, lb=label: el_text("h3", LEFT_IN_X if lb == "Zutaten" else RIGHT_X, y + 11, 134 if lb == "Zutaten" else RIGHT_W,
                                                      [f"{lb} (Fortsetzung)"], 9.2, 13, 700, DARK), "cont")
    # nutrition: left column by default; move to the right column when that saves a page
    variant_a = (_flow(left_blocks + [nutri_left], col_top, 22, cont_header_builder),
                 _flow(right_blocks, col_top, 22, cont_header_builder))
    left_pages, right_pages = variant_a
    if nutri_right is not None:
        variant_b = (_flow(left_blocks, col_top, 22, cont_header_builder),
                     _flow(right_blocks + [nutri_right], col_top, 22, cont_header_builder))
        if max(map(len, variant_b)) < max(map(len, variant_a)):
            left_pages, right_pages = variant_b
    n_pages = max(len(left_pages), len(right_pages))

    # ---------------- assemble pages
    out = []
    for p in range(n_pages):
        first = p == 0
        top = col_top if first else COL_TOP_N
        parts = [header_html(logo_uri)]
        if first:
            parts.append(el_text("h1", ML, 86, 331.236, t_lines, t_size, t_lh, 700, DARK))
            parts.append(el_text("p", ML, meta_y, 331.236, m_lines, 9.2, 13, 700, DARK))
            if ai_generated:
                parts.append(f'<div class="element text badge" style="{_style(ML, badge_y, 170, 15, f"font-size:8pt;line-height:15pt;font-weight:700;color:{DARK};background:{YELLOW};text-align:center")}">{AI_LABEL}</div>')
            if intro_lines:
                parts.append(el_text("p", ML, intro_y, 331.236, intro_lines, D["intro_size"], D["intro_lh"], 400, TEXT))
            if image_uri:
                parts.append(f'<img class="element image" alt="{html.escape(r.get("image_alt") or title)}" src="{image_uri}" style="{_style(IX, 86, IMG, IMG, "object-fit:cover")}">')
            else:
                parts.append(f'<div class="element placeholder" style="{_style(IX, 86, IMG, IMG)}">Bild folgt</div>')
            parts.append(el_text("p", IX, CAP_Y, IMG, cap_lines, 7.0, 9, 400, MUTED))
            parts.append(el_box(ML, col_top - 7, CW, 0.6, RULE))
        else:
            ref = wrap_text(f"{title} · Fortsetzung", CW, 11.0, True)[:1]
            parts.append(el_text("p", ML, 86, CW, ref, 11.0, 15, 700, DARK))
            parts.append(el_box(ML, 106, CW, 0.6, RULE))
        # left column
        if p < len(left_pages) and left_pages[p]:
            ybot = max(y + b.h for y, b in left_pages[p])
            parts.append(el_box(LEFT_X, top, LEFT_W, ybot - top + 4, SOFT))
            parts.append(el_box(LEFT_X, top, LEFT_W, 2.2, GREEN))
            parts += [b.render(y) for y, b in left_pages[p]]
        # right column
        if p < len(right_pages) and right_pages[p]:
            parts += [b.render(y) for y, b in right_pages[p]]
        parts.append(footer_html(p + 1, n_pages, ai_generated))
        out.append(f'<div class="page-wrap"><article class="page" aria-label="Seite {p + 1} von {n_pages}">{"".join(parts)}</article></div>')
    return out


DENSITIES = [   # readable at every level (>= 9.2 pt body); tried in order, the first single-page result wins
    dict(img=174, intro_size=10.0, intro_lh=14.5, head_h=64.5, head_a=13, head_b=42, ing_size=9.7, ing_lh=13.5, ing_gap=6.0, grp_pad=8,
         nut_lh=12.8, st_size=10.2, st_lh=14.2, st_gap=8.0, tip_size=9.4, tip_lh=13.0, tip_after=14),
    dict(img=160, intro_size=9.8, intro_lh=14.0, head_h=58.0, head_a=11, head_b=37, ing_size=9.5, ing_lh=12.9, ing_gap=4.6, grp_pad=6,
         nut_lh=12.4, st_size=10.0, st_lh=13.7, st_gap=6.5, tip_size=9.3, tip_lh=12.6, tip_after=10),
    dict(img=146, intro_size=9.6, intro_lh=13.4, head_h=54.0, head_a=10, head_b=34, ing_size=9.4, ing_lh=12.4, ing_gap=3.8, grp_pad=5,
         nut_lh=12.0, st_size=9.8, st_lh=13.2, st_gap=5.5, tip_size=9.2, tip_lh=12.2, tip_after=8),
    dict(img=132, intro_size=9.4, intro_lh=13.0, head_h=52.0, head_a=9, head_b=32, ing_size=9.3, ing_lh=12.0, ing_gap=3.2, grp_pad=4,
         nut_lh=11.6, st_size=9.6, st_lh=12.8, st_gap=4.8, tip_size=9.1, tip_lh=11.8, tip_after=6),
]


def render_recipe_pages(r: dict, nutrition: dict | None = None, image_uri: str | None = None,
                        logo_uri: str | None = None, ai_generated: bool = True) -> list[str]:
    """Return page HTML strings. Tries increasingly compact (still readable) layouts to keep the recipe on ONE A4 page;
    if it cannot fit, the layout with the fewest pages (least dense on ties) is used and runs onto page 2/3."""
    best = None
    for D in DENSITIES:
        pages = _layout(r, nutrition, image_uri, logo_uri, ai_generated, D)
        if len(pages) == 1:
            return pages
        if best is None or len(pages) < len(best):
            best = pages
    return best


def _step_block(number, lines, lh, gap, size):
    h = lh * len(lines) + gap

    def draw(y, n=number, ls=lines):
        s = ""
        if n is not None:
            s += (f'<div class="element number" style="{_style(RIGHT_X, y, 22, 22, "font-size:10pt")}">{n}</div>')
        return s + el_text("p", 245.02, y, RIGHT_X + RIGHT_W - 245.02, ls, size, lh, 400, TEXT)
    return Block(max(h, 26), draw, "step", cont_header="Zubereitung")


def header_html(logo_uri: str | None) -> str:
    logo = (f'<img class="element image" alt="das schmeckt!" src="{logo_uri}" style="{_style(ML, 34, 137, 30.9)}">' if logo_uri else
            f'<div class="element text" style="{_style(ML, 34, 137, 30.9, f"font:700 22pt/30.9pt Georgia,serif;color:{GREEN}")}">das schmeckt!</div>')
    return ('<header class="page-header">' + el_box(ML, 24, CW, 2.2, GREEN) + logo +
            el_text("p", 264.02, 42, 297.236, [TAGLINE], 8.3, 11, 400, MUTED) +
            el_box(ML, 73, CW, 0.6, RULE) + "</header>")


def footer_html(page: int, total: int, ai: bool) -> str:
    left = f"das schmeckt! · Mit Freude kochen.{' · ' + AI_LABEL if ai else ''}"
    return ('<footer class="page-footer">' + el_box(ML, 801, CW, 0.6, RULE) +
            el_text("p", ML, 810, 427.236, [left], 7.5, 10, 400, MUTED) +
            el_text("p", 469.256, 810, 92, [f"Seite {page} von {total}"], 7.5, 10, 400, MUTED) + "</footer>")


# ----------------------------------------------------------------------------- document
CSS = f"""
*{{box-sizing:border-box}}body{{margin:0;background:#e7ebe5;color:{TEXT};font-family:Helvetica,Arial,"Liberation Sans",sans-serif;-webkit-font-smoothing:antialiased}}
.toolbar{{max-width:210mm;margin:22px auto 16px;display:flex;justify-content:space-between;align-items:center;gap:20px}}
.toolbar h1{{font-size:16px;font-weight:500;margin:0;color:{DARK}}}.toolbar p{{font-size:12px;color:#526057;margin:4px 0 0}}
.toolbar button{{font:700 13px Helvetica,Arial,sans-serif;background:{GREEN};color:#fff;padding:10px 17px;border:0;cursor:pointer;white-space:nowrap}}
.print-help{{max-width:210mm;margin:0 auto 18px;font-size:12px;line-height:1.5;color:#526057}}
.pages{{padding:0 12px 25px}}.page-wrap{{margin:0 auto 22px;position:relative;width:210mm;height:297mm}}
.page{{position:absolute;top:0;left:0;width:210mm;height:297mm;background:#fcfbf7;box-shadow:0 3px 24px #183e3020;transform-origin:top left;overflow:hidden}}
.element{{position:absolute;box-sizing:border-box;margin:0;padding:0}}
.text{{font-kerning:none;font-variant-ligatures:none;font-feature-settings:"kern" 0,"liga" 0}}
.line{{display:block;white-space:pre;line-height:inherit}}.image{{display:block;object-fit:contain}}
.placeholder{{display:flex;align-items:center;justify-content:center;text-align:center;font-size:9pt;line-height:13pt;padding:15pt;color:{MUTED};background:{SOFT}}}
.badge{{border-radius:2pt}}
.ingredient{{cursor:pointer;display:block}}.ingredient input{{position:absolute;top:2pt;left:0;width:9pt;height:9pt;margin:0;accent-color:{GREEN}}}
.ingredient input:checked~span{{text-decoration:line-through;color:#768176}}.ingredient-copy{{display:block;margin-left:16pt}}
.number{{border-radius:50%;background:{YELLOW};color:{DARK};text-align:center;font-weight:700;display:flex;align-items:center;justify-content:center}}
.page-header,.page-footer{{position:static}}h1,h2,h3,p{{margin:0;font-weight:inherit}}
button:focus-visible,input:focus-visible{{outline:2px solid {GREEN};outline-offset:4px}}
@page{{size:A4 portrait;margin:0}}
@media print{{html,body{{margin:0!important;padding:0!important;width:210mm!important;background:#fff!important}}
.toolbar,.print-help{{display:none!important}}.pages{{display:block!important;padding:0!important;margin:0!important;width:210mm!important}}
.page-wrap{{display:block!important;position:relative!important;width:210mm!important;height:296.4mm!important;margin:0!important;overflow:hidden;break-after:page;page-break-after:always}}
.page-wrap:last-child{{break-after:auto;page-break-after:auto}}.page{{box-shadow:none!important;transform:none!important}}}}
"""

JS = """(()=>{const W=210*96/25.4,H=297*96/25.4,wraps=[...document.querySelectorAll('.page-wrap')];
function fit(){const avail=(document.querySelector('.pages').clientWidth||W)-24,s=Math.min(1,avail/W);
wraps.forEach(w=>{const p=w.firstElementChild;p.style.transform=s<1?'scale('+s+')':'';w.style.width=(W*s)+'px';w.style.height=(H*s)+'px';});}
addEventListener('resize',fit);addEventListener('beforeprint',()=>wraps.forEach(w=>{w.firstElementChild.style.transform='';w.style.width='';w.style.height='';}));
addEventListener('afterprint',fit);document.getElementById('print').addEventListener('click',()=>print());fit();})();"""


SHIPPED_LOGO = Path(__file__).resolve().parents[2] / "assets" / "logo_das_schmeckt.png"


def extract_template_logo(template_html: str | Path | None = None) -> str | None:
    """Official logo: taken from the template file if given, otherwise the copy shipped in assets/ (extracted from that same template)."""
    if template_html and Path(template_html).is_file():
        txt = Path(template_html).read_text(encoding="utf-8", errors="replace")
        m = re.search(r'<header[^>]*>.*?<img[^>]*src="(data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+)"', txt, re.S)
        if m:
            return m.group(1)
    return image_to_uri(SHIPPED_LOGO)


def image_to_uri(path: str | Path | None) -> str | None:
    if not path or not Path(path).is_file():
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode()}"


def build_document(recipe_pages: list[tuple[str, list[str]]], title: str = "das schmeckt! · Rezeptentwürfe") -> str:
    """recipe_pages: [(recipe title, [page html,...]), ...] -> complete standalone HTML document."""
    n = sum(len(p) for _, p in recipe_pages)
    names = " · ".join(t for t, _ in recipe_pages)
    body = "".join("".join(p) for _, p in recipe_pages)
    return (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta name="recipe-template-version" content="A4-v5-flow"><title>{html.escape(names)} · das schmeckt!</title><style>{CSS}</style></head><body>'
            f'<div class="toolbar"><div><h1>{html.escape(names)}</h1><p>DIN A4 · {n} Seite{"n" if n != 1 else ""} · {AI_LABEL}</p></div><button id="print">Drucken / PDF</button></div>'
            f'<p class="print-help">Druckeinstellung: A4, Skalierung 100 %, keine Kopf-/Fußzeilen des Browsers.</p>'
            f'<main class="pages">{body}</main><script>{JS}</script></body></html>')


def render_card_file(recipe: dict, out_path: str | Path, nutrition: dict | None = None, image_path: str | Path | None = None,
                     template_html: str | Path | None = None, ai_generated: bool = True) -> dict:
    pages = render_recipe_pages(recipe, nutrition, image_to_uri(image_path), extract_template_logo(template_html), ai_generated)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(build_document([(recipe["title"], pages)]), encoding="utf-8")
    return {"path": str(out_path), "pages": len(pages)}
