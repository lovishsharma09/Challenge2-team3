"""Honest display helpers for proposal evidence (pure functions, unit-tested).

Handles the optional fields of the Person A handoff contract (schemas/proposals.schema.json on main):
  archive: status, available, match_status (matches_found|no_match_found|archive_unavailable), assumption
  trend.wikimedia: status (available|no_article_found|no_data|unavailable), article, score, error
Missing information must never be shown as "nothing found".
"""
from __future__ import annotations


def _md(text) -> str:
    """Escape markdown so archive titles can never format or inject anything in the UI."""
    return "".join("\\" + c if c in "\\`*_{}[]()#+-.!|<>~$" else c for c in str(text))


def archive_summary(proposal: dict) -> tuple[str, str]:
    """Returns (level, markdown text); level is 'ok' | 'warn' for the UI."""
    a = proposal.get("archive") or {}
    source = {"export": "Archive (real local export)", "mock": "Archive (MOCK data)"}.get(a.get("source"), "Archive")
    similar = a.get("similar_recipes", [])
    risk = a.get("repetition_risk", "unknown")
    gap = a.get("content_gap", "")
    status = a.get("match_status")
    if status == "archive_unavailable" or a.get("available") is False:
        return "warn", (f"**{source}: not available.** Similar recipes and repetition risk could NOT be checked."
                        + (f" {_md(a['assumption'])}" if a.get("assumption") else ""))
    if status == "no_match_found" or (not similar and status is None):
        head = f"**{source}:** no credible match in this export."
    else:
        lines = []
        for r in similar:
            line = f"- {_md(r.get('title', '?'))}" + (f" ({_md(r['category'])})" if r.get("category") else "")
            if r.get("why"):
                line += f": {_md(r['why'])}"
            if "publication_date" in r:
                line += f". {_md(r.get('publication_note') or 'Publication date unavailable.')}"
            lines.append(line)
        count = a.get("match_count")
        head = f"**{source}:** similar recipes" + (f" ({count} credible match(es) in this export, top {len(similar)} shown)" if count else "") + ":\n" + "\n".join(lines)
    if risk == "not_assessed":
        tail = "\n\nRepetition risk: **not assessed** (needs a comparison with the specific pitch, matches only show topic coverage)."
    else:
        tail = f"\n\nRepetition risk: **{_md(risk)}**."
    if gap:
        tail += f" {_md(gap)}"
    if a.get("assumption"):
        tail += f"\n\n*Assumption: {_md(a['assumption'])}*"
    return ("warn" if risk == "unknown" else "ok"), head + tail


def trend_summary(proposal: dict) -> str | None:
    """How the trend score was computed (only for proposals built from the real trend data)."""
    c = (proposal.get("trend") or {}).get("components")
    if not c:
        return None
    parts = [f"Google {c['google']:.0f} (strongest rising row '{c['best_term']}': +{c['rising_increase_pct']}%, "
             f"search-interest index {c['search_interest_index']}/100, damping factor {c['interest_factor_google']})"]
    if c.get("wikipedia") is not None:
        parts.append(f"Wikipedia {c['wikipedia']:.0f} (page-views factor {c['views_factor_wikipedia']})")
    formula = "0.5×Google + 0.5×Wikipedia" if not c.get("single_source") else "0.5×Google only (single source)"
    return (f"Score {c['score']:.0f} = {formula}. " + "; ".join(parts) +
            ". The search-interest index is relative within Google's export, not a search volume. Heuristic, not a forecast.")


def wikimedia_summary(proposal: dict) -> tuple[str, str]:
    w = (proposal.get("trend") or {}).get("wikimedia")
    if not w:
        return "warn", "Wikipedia pageviews: not part of this proposal's evidence."
    status = w.get("status")
    if status == "available":
        score = w.get("score")
        extra = ""
        if w.get("views_latest_7d") is not None:
            extra = f" 7-day views {w.get('views_previous_7d')} → {w.get('views_latest_7d')} ({w.get('change_pct'):+.0f}%)."
        return "ok", f"Wikipedia pageviews ({w.get('article')}): change score {score if score is not None else 'n/a'}/100.{extra}"
    reasons = {"no_article_found": "no usable article", "no_data": "no data for the period",
               "unavailable": f"source unavailable ({w.get('error') or 'unknown error'})"}
    detail = w.get("reason") or reasons.get(status, "status unknown")
    return "warn", f"Wikipedia pageviews: {detail}. This signal could NOT be checked."
