"""Export approved recipes as A4 HTML cards in the supplied "das schmeckt!" template (A4-v5).

Reuses the template's CSS, header (logo), print script and element classes; lays out the body in code.
Rules from templates/Das-schmeckt-Requirements-HTML.txt (and the dataset README):
- Content fidelity: ingredients, amounts, units, times and steps are copied verbatim (text is only wrapped, never
  shortened, converted or summed; prep and cook time are shown separately, not added up).
- Variable length: ingredient/step counts and text lengths vary; content continues on follow-up pages with header,
  footer, recipe name and "Seite i von n".
- Nutrition is shown only when the nutrition agent delivered values (status "ok"), never as 0 for "missing".
- Every card carries a clear "AI-generated recipe draft" label; soft review warnings are printed if approved with them.
Line wrapping uses a conservative character-width estimate (no font metrics available): see tests and the PDF check.
"""
from __future__ import annotations

import base64
import html
import mimetypes
import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "Das-schmeckt-Recipe-Preview-A4.html"
LEFT_X, LEFT_W = 34.02, 158.0
RIGHT_X, RIGHT_W = 215.02, 346.236
FULL_W = 527.236
BOTTOM = 790.0            # content must end above the footer line (801pt)
CHAR_EM = 0.56            # average glyph width in em for Helvetica/Arial text (template itself packs ~0.53)
INK, MUTED, GREEN = "#28332d", "#647169", "#183e30"

_cache: dict = {}


def _template_parts() -> dict:
    if not _cache:
        s = TEMPLATE.read_text(encoding="utf-8")
        _cache["style"] = re.search(r"<style>.*?</style>", s, re.S).group(0)
        _cache["header"] = re.search(r'<header class="page-header">.*?</header>', s, re.S).group(0)
        _cache["script"] = re.findall(r"<script>.*?</script>", s, re.S)[-1]
        _cache["help"] = re.search(r'<p class="print-help">.*?</p>', s, re.S).group(0)
    return _cache


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def wrap(text: str, width_pt: float, font_pt: float) -> list[str]:
    """Greedy word wrap; words longer than a line are split so that no character is ever dropped."""
    limit = max(6, int(width_pt / (font_pt * CHAR_EM)))
    lines: list[str] = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split():
            while len(word) > limit:                       # hard split overlong words
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:limit])
                word = word[limit:]
            if not cur:
                cur = word
            elif len(cur) + 1 + len(word) <= limit:
                cur += " " + word
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines or [""]


def fmt_amount(amount) -> str:
    if amount is None or amount == "":
        return ""
    if isinstance(amount, float) and amount.is_integer():
        amount = int(amount)
    return str(amount).replace(".", ",") if isinstance(amount, float) else str(amount)


def ingredient_text(ing: dict) -> str:
    return " ".join(p for p in (fmt_amount(ing.get("amount")), str(ing.get("unit") or "").strip(),
                                str(ing.get("name", "")).strip()) if p)


def text_el(x, y, w, font, lh, lines, *, weight=400, color=INK, tag="p", extra=""):
    spans = "".join(f'<span class="line">{esc(l)}</span>' for l in lines)
    return (f'<{tag} class="element text" style="left:{x:.3f}pt;top:{y:.3f}pt;width:{w:.3f}pt;height:{lh * len(lines):.3f}pt;'
            f'font-size:{font}pt;line-height:{lh}pt;font-weight:{weight};color:{color};"{extra}>{spans}</{tag}>')


def box(x, y, w, h, color):
    return (f'<div class="element" style="left:{x:.3f}pt;top:{y:.3f}pt;width:{w:.3f}pt;height:{h:.3f}pt;'
            f'background:{color}" aria-hidden="true"></div>')


def image_src(recipe: dict) -> str | None:
    path, url = recipe.get("image_path"), str(recipe.get("image_url") or "")
    if path and Path(path).is_file():
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()
    if url.startswith(("https://", "http://", "data:image/")):
        return url
    return None


def nutrition_lines(nut: dict | None) -> list[str]:
    if not nut or nut.get("status") != "ok" or not nut.get("per_serving"):
        return []
    labels = (("kcal", "Energie", "kcal"), ("fat_g", "Fett", "g"), ("carbs_g", "Kohlenhydrate", "g"),
              ("protein_g", "Eiweiß", "g"))
    ps = nut["per_serving"]
    lines = [f"{label}: {fmt_amount(ps[key])} {unit}" for key, label, unit in labels if ps.get(key) is not None]
    return lines


def _column_pages(items: list[tuple[list[str], float, float]], first_top: float, later_top: float, gap: float,
                  min_h: float = 0.0):
    """items: (lines, font, lh). Returns pages: list of [(y_offset_from_page_top, chunk_lines, is_continuation)]."""
    pages: list[list] = [[]]
    y = first_top
    for lines, _font, lh in items:
        remaining, cont = list(lines), False
        while remaining:
            cap = int((BOTTOM - y) // lh)
            if cap < min(2, len(remaining)):                # not even two lines fit: new page
                pages.append([])
                y = later_top
                continue
            take, remaining = remaining[:cap], remaining[cap:]
            pages[-1].append((y, take, cont))
            y += max(lh * len(take), min_h) + gap
            cont = True
            if remaining:
                pages.append([])
                y = later_top
    return pages


AI_LABEL = "KI-generierter Rezeptentwurf"
MOCK_LABEL = "MOCK-Entwurf · kein echtes Rezept"


def render_recipe(recipe: dict, nutrition: dict | None, warnings: list[dict]) -> str:
    parts = _template_parts()
    title = str(recipe.get("title", "Rezept"))
    label = MOCK_LABEL if recipe.get("mock") else AI_LABEL

    # ---------- page 1 title block
    t_lines = wrap(title, 331.236, 29)
    y = 86.0 + 31 * len(t_lines)
    blocks = [text_el(LEFT_X, 86, 331.236, 29, 31, t_lines, weight=700, color=GREEN, tag="h1")]
    y += 12
    times = []
    if recipe.get("prep_time_minutes"):
        times.append(f"Vorbereitung: {recipe['prep_time_minutes']} Min.")
    if recipe.get("cook_time_minutes"):
        times.append(f"Garen: {recipe['cook_time_minutes']} Min.")
    if recipe.get("servings"):
        times.append(f"{recipe['servings']} Portionen")
    if times:
        m = wrap(" · ".join(times), 331.236, 9.2)
        blocks.append(text_el(LEFT_X, y, 331.236, 9.2, 13, m, weight=700, color=GREEN))
        y += 13 * len(m) + 6
    if recipe.get("subtitle"):
        sub = wrap(recipe["subtitle"], 331.236, 9.5)
        blocks.append(text_el(LEFT_X, y, 331.236, 9.5, 13, sub, color="#526057"))
        y += 13 * len(sub) + 8
    blocks.append(f'<div class="element" style="left:{LEFT_X}pt;top:{y:.3f}pt;width:190pt;height:17pt;background:#fff04b;'
                  f'color:{GREEN};font:700 8.5pt/17pt Helvetica,Arial,sans-serif;text-align:center">'
                  f'{esc(label)}</div>')
    y += 17 + 6
    if warnings:
        wl = [f"Redaktionell freigegeben mit offenen Prüfhinweisen:"]
        for w in warnings:
            wl += wrap(f"– {w['message']}" + (f" (Hinweis Redaktion: {w['dismiss_reason']})" if w.get("dismiss_reason") else ""),
                       331.236, 7.7)
        blocks.append(text_el(LEFT_X, y, 331.236, 7.7, 10.3, wl, color=MUTED))
        y += 10.3 * len(wl) + 4

    src = image_src(recipe)
    alt = f"Bild zu {title}"
    if src:
        blocks.append(f'<img class="element image" style="left:387.256pt;top:86pt;width:174pt;height:174pt;" '
                      f'src="{esc(src)}" alt="{esc(alt)}" data-recipe-image>')
        blocks.append(text_el(387.256, 265, 174, 7, 9, ["KI-generiertes Bild · kein Originalfoto", "aus dem Archiv"], color=MUTED))
    else:
        blocks.append('<div class="element placeholder" style="left:387.256pt;top:86pt;width:174pt;height:174pt;">'
                      'Noch kein Bild vorhanden.</div>')
    sep_y = max(292.0, y + 4)
    blocks.append(box(LEFT_X, sep_y, FULL_W, 0.6, "#d8ded5"))
    top1 = sep_y + 7
    later_top = 112.0

    # ---------- columns (paginated independently, then zipped page by page)
    ing_items = [(wrap(ingredient_text(i), LEFT_W - 12 - 16, 9.7), 9.7, 13.5) for i in recipe.get("ingredients", [])]
    left_pages = _column_pages(ing_items, top1 + 64, later_top + 52, 6.0)
    step_items = [(wrap(s, 316.236, 10.2), 10.2, 14.2) for s in recipe.get("steps", [])]
    right_pages = _column_pages(step_items, top1 + 33, later_top + 33, 8.0, min_h=22.0)

    tip = str(recipe.get("serving_tip") or recipe.get("tip") or "").strip()
    tip_lines = wrap(tip, 330, 9.4) if tip else []
    tip_at = None                                           # (page index, y) of the tip box
    if tip_lines:
        need = 26 + 13.3 * len(tip_lines) + 10
        last = right_pages[-1]
        end = max((yy + max(14.2 * len(lines), 22.0) for (yy, lines, _c) in last),
                  default=(top1 if len(right_pages) == 1 else later_top) + 33)
        if end + 8 + need <= BOTTOM:
            tip_at = (len(right_pages) - 1, end + 8, need)
        else:
            right_pages.append([])
            tip_at = (len(right_pages) - 1, later_top + 33, need)

    nut_lines = nutrition_lines(nutrition)
    assumptions = []
    if nut_lines:
        for a in nutrition.get("assumptions", []):
            assumptions += wrap(f"Annahme: {a.get('original')} → {a.get('used')} (Sicherheit: {a.get('confidence')})", 134, 7.5)
    n_pages = max(len(left_pages), len(right_pages), 1)

    pages_html = []
    for p in range(n_pages):
        first = p == 0
        top = top1 if first else later_top
        out = [parts["header"]]
        if first:
            out += blocks
        else:
            out.append(text_el(LEFT_X, 84, 527.236, 11, 14, [f"{title} (Fortsetzung)"], weight=700, color=GREEN))
            out.append(box(LEFT_X, 104, FULL_W, 0.6, "#d8ded5"))

        # left column: ingredients (+ nutrition on the page where the list ends)
        labels, end_left = [], (top + 64) if first else (top + 52)
        for (yy, lines, _cont) in (left_pages[p] if p < len(left_pages) else []):
            spans = "".join(f'<span class="line">{esc(l)}</span>' for l in lines)
            labels.append(f'<label class="element text ingredient" style="left:46.020pt;top:{yy:.3f}pt;width:134pt;'
                          f'height:{13.5 * len(lines):.3f}pt;font-size:9.7pt;line-height:13.5pt;font-weight:400;color:{INK};">'
                          f'<input type="checkbox"><span class="ingredient-copy">{spans}</span></label>')
            end_left = max(end_left, yy + 13.5 * len(lines))
        extra, y2 = [], end_left + 16
        if nut_lines and p == len(left_pages) - 1:
            h = 18 + 12 * len(nut_lines) + (10 * len(assumptions) + 6 if assumptions else 0)
            if y2 + h <= BOTTOM:
                extra.append(text_el(46.02, y2, 134, 11, 14, ["Nährwerte pro Portion"], weight=700, color=GREEN, tag="h2"))
                extra.append(text_el(46.02, y2 + 18, 134, 8.7, 12, nut_lines))
                if assumptions:
                    extra.append(text_el(46.02, y2 + 18 + 12 * len(nut_lines) + 6, 134, 7.5, 10, assumptions, color=MUTED))
                end_left = y2 + h
        panel_end = min(BOTTOM, end_left + 14)
        out.append(box(LEFT_X, top, LEFT_W, panel_end - top, "#edf2e9"))
        out.append(box(LEFT_X, top, LEFT_W, 2.2, "#006642"))
        out.append(text_el(46.02, top + 13, 134, 16, 20, ["Zutaten"],
                           weight=700, color=GREEN, tag="h2"))
        if first and recipe.get("servings"):
            out.append(text_el(46.02, top + 42, 134, 9.2, 12.5, [f"Für {recipe['servings']} Portionen"], color=MUTED))
        out += labels + extra

        # right column: numbered steps (+ tip)
        out.append(text_el(RIGHT_X, top, RIGHT_W, 16, 20, ["Zubereitung" if first else "Zubereitung (Fortsetzung)"],
                           weight=700, color=GREEN, tag="h2"))
        number = sum(1 for pg in right_pages[:p] for (_y, _l, cont) in pg if not cont)
        for (yy, lines, cont) in (right_pages[p] if p < len(right_pages) else []):
            if not cont:
                number += 1
                out.append(f'<div class="element number" style="left:215.02pt;top:{yy:.3f}pt;width:22pt;height:22pt;'
                           f'font-size:10pt" aria-label="Schritt {number}">{number}</div>')
            out.append(text_el(245.02, yy, 316.236, 10.2, 14.2, lines))
        if tip_at and tip_at[0] == p:
            _pg, ty, need = tip_at
            out += [box(RIGHT_X, ty, RIGHT_W, need, "#edf2e9"), box(RIGHT_X, ty, 2, need, "#006642"),
                    text_el(227.02, ty + 10, 334.236, 9.2, 12, ["Unser Tipp"], weight=700, color=GREEN, tag="h3"),
                    text_el(227.02, ty + 26, 330, 9.4, 13.3, tip_lines)]

        out.append('<footer class="page-footer">' + box(34.02, 801, 527.236, 0.6, "#d8ded5") +
                   text_el(34.02, 810, 427.236, 7.5, 10, [f"das schmeckt! · Mit Freude kochen. · {label}"], color=MUTED) +
                   text_el(469.256, 810, 92, 7.5, 10, [f"Seite {p + 1} von {{N}}"], color=MUTED) + "</footer>")
        pages_html.append("".join(out))

    n = len(pages_html)
    wrapped = "".join(f'<div class="page-wrap"><article class="page" aria-label="Rezeptseite {i + 1} von {n}">'
                      f'{h.replace("{N}", str(n))}</article></div>' for i, h in enumerate(pages_html))
    return (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta name="recipe-template-version" content="A4-v5"><title>{esc(title)} · das schmeckt!</title>{parts["style"]}</head><body>'
            f'<div class="toolbar"><div><h1>{esc(title)}</h1><p>DIN A4 · {n} Seite{"n" if n > 1 else ""} · Druckfassung A4-v5 · '
            f'{esc(label)}</p></div><button id="print" type="button">Drucken / PDF</button></div>'
            f'{parts["help"]}<main class="pages" aria-label="Rezept auf DIN-A4-Seiten">{wrapped}</main>'
            f'<noscript><p class="noscript">Die Rezeptseiten sind auch ohne JavaScript sichtbar.</p></noscript>{parts["script"]}</body></html>')


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).casefold().translate(str.maketrans("äöüß", "aous"))).strip("-") or "rezept"


def render_cards(recipes: list[dict], nutritions: list[dict | None], warnings: list[dict], topic: str, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i, recipe in enumerate(recipes):
        nut = nutritions[i] if i < len(nutritions) else None
        mine = [w for w in warnings if w.get("recipe_index") in (None, i)]
        path = out_dir / f"{slug(topic)}-{i + 1}.html"
        path.write_text(render_recipe(recipe, nut, mine), encoding="utf-8")
        files.append(path)
    return files
