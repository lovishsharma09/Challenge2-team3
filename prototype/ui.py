"""Look of the prototype page: brand CSS, stepper, logo header, small HTML components (no raw JSON on the page)."""
from __future__ import annotations

import base64
import html
from pathlib import Path

GREEN, DARK, YELLOW, BG, SOFT = "#006642", "#183e30", "#fff04b", "#fcfbf7", "#edf2e9"
LOGO = Path(__file__).resolve().parent.parent / "person_c" / "assets" / "logo_das_schmeckt.png"
STEPS = ["Signals", "Proposals", "Your decision", "Recipes", "Result"]

CSS = f"""
<style>
html, body, [class*="css"], .stApp {{ font-family: Helvetica, Arial, sans-serif; color: {DARK}; }}
.stApp {{ background: {BG}; }}
#MainMenu, footer, header[data-testid="stHeader"] {{ visibility: hidden; height: 0; }}
div[data-testid="stToolbar"], div[data-testid="stDecoration"], div[data-testid="stStatusWidget"] {{ display: none; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 4rem; max-width: 1280px; }}
h1, h2, h3 {{ color: {DARK}; font-weight: 700; letter-spacing: -0.01em; }}
h1 {{ font-size: 1.9rem; margin-bottom: .2rem; }}
h2 {{ font-size: 1.35rem; margin-top: .6rem; }}
h3 {{ font-size: 1.05rem; }}
.ds-top {{ display:flex; align-items:center; gap:18px; padding: 6px 0 10px 0; border-bottom: 3px solid {GREEN}; margin-bottom: 14px; }}
.ds-top img {{ height: 44px; }}
.ds-top .title {{ font-size: 1.35rem; font-weight: 700; color: {DARK}; }}
.ds-top .sub {{ color: #5a6b62; font-size: .9rem; }}
.ds-pill {{ display:inline-block; background:{YELLOW}; color:{DARK}; font-weight:700; font-size:.72rem; padding:2px 9px; border-radius: 999px; letter-spacing:.04em; text-transform: uppercase; }}
.ds-stepper {{ display:flex; gap: 8px; margin: 4px 0 18px 0; }}
.ds-step {{ flex:1; padding: 9px 12px; border-radius: 10px; background: {SOFT}; color: {DARK}; font-size: .85rem; }}
.ds-step .n {{ display:inline-block; width:22px; height:22px; line-height:22px; text-align:center; border-radius:50%; background:#c9d6c6; color:{DARK}; font-weight:700; margin-right:8px; font-size:.78rem; }}
.ds-step.done {{ background: #dfeadc; }}
.ds-step.done .n {{ background: {GREEN}; color: white; }}
.ds-step.current {{ background: {GREEN}; color: white; font-weight: 700; }}
.ds-step.current .n {{ background: {YELLOW}; color: {DARK}; }}
.ds-card {{ background: white; border-radius: 12px; padding: 18px 22px; margin-bottom: 18px; }}
.ds-card.soft {{ background: {SOFT}; }}
.ds-card h3 {{ margin: 0 0 6px 0; }}
.ds-kicker {{ color:{GREEN}; font-weight:700; font-size:.78rem; text-transform:uppercase; letter-spacing:.06em; }}
.ds-muted {{ color:#5a6b62; font-size:.86rem; }}
.ds-metric {{ background:white; border-radius:12px; padding:12px 14px; }}
.ds-metric .v {{ font-size:1.6rem; font-weight:700; color:{GREEN}; line-height:1.1; }}
.ds-metric .l {{ color:#5a6b62; font-size:.8rem; margin-top:2px; }}
.ds-badge {{ display:inline-block; padding:2px 8px; border-radius:6px; font-size:.75rem; font-weight:700; margin-right:4px; }}
.ds-ok {{ background:#dff1e4; color:#0b5d3a; }}
.ds-warn {{ background:#fff3c4; color:#6b5300; }}
.ds-bad {{ background:#fde2e1; color:#8a1f1a; }}
.ds-neutral {{ background:{SOFT}; color:{DARK}; }}
.ds-table {{ width:100%; border-collapse: collapse; font-size:.84rem; }}
.ds-table th {{ text-align:left; color:#5a6b62; font-weight:600; border-bottom: 2px solid #e4e9e2; padding: 6px 8px; }}
.ds-table td {{ border-bottom: 1px solid #eef1ec; padding: 6px 8px; vertical-align: top; }}
.ds-table tr:last-child td {{ border-bottom: none; }}
.ds-spark {{ vertical-align: middle; }}
div[data-testid="stExpander"] details {{ border-radius: 10px; border: none; background: white; }}
div.stButton > button[kind="primary"] {{ background: {GREEN}; border-color: {GREEN}; font-weight: 700; }}
div.stButton > button[kind="primary"]:hover {{ background: {DARK}; border-color: {DARK}; }}
section[data-testid="stSidebar"] {{ background: {SOFT}; }}
section[data-testid="stSidebar"] .block-container {{ padding-top: 1rem; }}
.stProgress > div > div > div {{ background: {GREEN}; }}
</style>
"""


def esc(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def logo_uri() -> str | None:
    if LOGO.is_file():
        return "data:image/png;base64," + base64.b64encode(LOGO.read_bytes()).decode()
    return None


def top_bar(mode: str) -> str:
    img = f'<img src="{logo_uri()}" alt="das schmeckt!">' if logo_uri() else '<span class="title">das schmeckt!</span>'
    pill = '<span class="ds-pill">Demo · cached run</span>' if mode == "demo" else '<span class="ds-pill" style="background:#dfeadc">Live</span>'
    return (f'<div class="ds-top">{img}<div><div class="title">Rezept-Werkstatt</div>'
            f'<div class="sub">From trend signal to reviewed recipe card</div></div>'
            f'<div style="margin-left:auto">{pill}</div></div>')


def stepper(current: int, done: set[int]) -> str:
    cells = []
    for n, label in enumerate(STEPS, 1):
        cls = "current" if n == current else ("done" if n in done else "")
        cells.append(f'<div class="ds-step {cls}"><span class="n">{"✓" if n in done and n != current else n}</span>{esc(label)}</div>')
    return '<div class="ds-stepper">' + "".join(cells) + "</div>"


def sparkline_svg(values: list[int], width: int = 150, height: int = 36, color: str = GREEN) -> str:
    """Inline SVG line of daily values (empty series -> a dash)."""
    vals = [int(v) for v in values if isinstance(v, (int, float))]
    if len(vals) < 2:
        return f'<span class="ds-muted">— no series —</span>'
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    step = (width - 4) / (len(vals) - 1)
    pts = " ".join(f"{2 + i * step:.1f},{height - 3 - (v - lo) / span * (height - 8):.1f}" for i, v in enumerate(vals))
    last_x, last_y = 2 + (len(vals) - 1) * step, height - 3 - (vals[-1] - lo) / span * (height - 8)
    return (f'<svg class="ds-spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}"/>'
            f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="{YELLOW}" stroke="{color}"/></svg>')


def badge(text, level: str = "neutral") -> str:
    return f'<span class="ds-badge ds-{level}">{esc(text)}</span>'


def metric(value, label) -> str:
    return f'<div class="ds-metric"><div class="v">{esc(value)}</div><div class="l">{esc(label)}</div></div>'


def table(headers: list[str], rows: list[list], raw_cols: set[int] | None = None) -> str:
    """Small HTML table; cells are escaped unless their column index is in raw_cols (already safe HTML)."""
    raw_cols = raw_cols or set()
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = []
    for row in rows:
        tds = "".join(f"<td>{cell if i in raw_cols else esc(cell)}</td>" for i, cell in enumerate(row))
        trs.append(f"<tr>{tds}</tr>")
    return f'<table class="ds-table"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def card(inner_html: str, soft: bool = False) -> str:
    return f'<div class="ds-card{" soft" if soft else ""}">{inner_html}</div>'


def risk_level(risk: str | None) -> str:
    return {"low": "ok", "medium": "warn", "high": "bad"}.get(str(risk), "neutral")


def quality_level(q: str | None) -> str:
    return {"hoch": "ok", "mittel": "warn", "niedrig": "bad", "unvollständig": "bad"}.get(str(q), "neutral")


def fmt_num(v, digits: int = 0) -> str:
    if v is None:
        return "–"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return str(v)
