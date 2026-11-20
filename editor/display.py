"""Honest display helpers for proposal evidence (pure functions, unit-tested).

Handles the optional fields of the Person A handoff contract (schemas/proposals.schema.json on main):
  archive: status, available, match_status (matches_found|no_match_found|archive_unavailable), assumption
  trend.wikimedia: status (available|no_article_found|no_data|unavailable), article, score, error
Missing information must never be shown as "nothing found".
"""
from __future__ import annotations

import difflib
import math
import re


def _md(text) -> str:
    """Escape markdown so archive titles can never format or inject anything in the UI."""
    return "".join("\\" + c if c in "\\`*_{}[]()#+-.!|<>~$" else c for c in str(text))


md = _md      # public name: escape any supplied text before it goes into a markdown element


def _num(x) -> float | None:
    """A finite number or None. Bools, strings, NaN and infinity are not numbers for display purposes."""
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


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
            if not isinstance(r, dict):
                continue
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


def coverage_summary(proposal: dict) -> tuple[str, str]:
    """Prior coverage in the archive, as COVERAGE ONLY: never a repetition judgement, never a publication date.
    Distinguishes archive unavailable / no credible match / matches found. Returns (level, markdown)."""
    a = proposal.get("archive") or {}
    status, similar = a.get("match_status"), a.get("similar_recipes") or []
    if status == "archive_unavailable" or a.get("available") is False:
        return "warn", ("**Prior coverage: archive not available.** Comparable recipes could NOT be checked, so this is not "
                        "the same as 'no match'." + (f" {_md(a['assumption'])}" if a.get("assumption") else ""))
    if status == "no_match_found" or (not similar and status is None):
        head = ("**Prior coverage:** no credible comparable recipe found in the archive export "
                "(the export is a selection, so this is not proof that the topic was never published).")
    else:
        n = int(_num(a.get("match_count"))) if _num(a.get("match_count")) else len(similar)
        lines = []
        for r in similar:
            if not isinstance(r, dict):
                continue
            line = f"- {_md(r.get('title', '?'))}" + (f" ({_md(r['category'])})" if r.get("category") else "")
            if r.get("why"):
                line += f": {_md(r['why'])}"
            lines.append(line)
        head = (f"**Prior coverage:** {n} comparable recipe(s) in the archive export" +
                (f", {len(similar)} listed" if n != len(similar) else "") + ":\n" + "\n".join(lines))
    tail = ("\n\nCoverage only, not a repetition judgement: repetition risk is **not assessed**. Publication dates are not shown, "
            "because the export documents none (CMS and import dates are not publication dates).")
    if a.get("assumption"):
        tail += f"\n\n*{_md(a['assumption'])}*"
    return "ok", head + tail


def short(text, limit: int = 140) -> str:
    """First sentence, cut at a word boundary. A text that is already one short sentence comes back unchanged (final period
    included); the full text of anything shortened stays available in the evidence expander."""
    t = " ".join(str(text or "").split())
    if not t:
        return ""
    first = re.split(r"(?<=[.!?])\s+", t, maxsplit=1)[0]   # the first sentence keeps its own punctuation
    if len(first) <= limit:
        return first
    window = first[:limit]
    for sep in ("; ", ", ", " – "):                    # prefer ending at a clause boundary over ending mid-phrase
        i = window.rfind(sep)
        if i >= limit * 0.5:
            return window[:i].rstrip(",;:") + "…"
    return window.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def coverage_short(proposal: dict) -> tuple[str, str]:
    """One-line prior-coverage summary for the comparison view. The full list and the caveats live in the evidence expander."""
    a = proposal.get("archive") or {}
    status, similar = a.get("match_status"), [r for r in (a.get("similar_recipes") or []) if isinstance(r, dict)]
    if status == "archive_unavailable" or a.get("available") is False:
        return "warn", "Prior coverage: archive not available, so comparable recipes could NOT be checked."
    if status == "no_match_found" or (not similar and status is None):
        return "ok", "Prior coverage: no credible comparable recipe found in the archive export."
    n = int(_num(a.get("match_count"))) if _num(a.get("match_count")) else len(similar)
    return "ok", f"Prior coverage: {n} comparable recipe(s) in the archive export (coverage only)."


def pitch_fields(proposal: dict) -> dict:
    """The four comparable blocks of a pitch, with the original (possibly German) texts kept as supplied."""
    ideas = [i for i in proposal.get("recipe_ideas") or [] if isinstance(i, str) and i.strip()]
    brand = proposal.get("brand_fit") or {}
    return {"angle": ideas[0] if ideas else None, "more_angles": ideas[1:],
            "why_now": (proposal.get("trend") or {}).get("why_relevant") or None,
            "brand_reason": brand.get("reasoning") if isinstance(brand.get("reasoning"), str) and brand.get("reasoning") else None}


def trend_summary(proposal: dict) -> str | None:
    """How the trend score was computed. Only for components in the shape our own trend module produces; anything else is ignored."""
    c = (proposal.get("trend") or {}).get("components")
    if not isinstance(c, dict):
        return None
    need = ("score", "google", "rising_increase_pct", "search_interest_index", "interest_factor_google")
    if any(_num(c.get(k)) is None for k in need) or not isinstance(c.get("best_term"), str):
        return None
    parts = [f"Google {_num(c['google']):.0f} (strongest rising row '{_md(c['best_term'])}': +{_num(c['rising_increase_pct']):.0f}%, "
             f"search-interest index {_num(c['search_interest_index']):.0f}/100, damping factor {_num(c['interest_factor_google'])})"]
    if _num(c.get("wikipedia")) is not None:
        parts.append(f"Wikipedia {_num(c['wikipedia']):.0f} (page-views factor {_num(c.get('views_factor_wikipedia'))})")
    formula = "0.5×Google + 0.5×Wikipedia" if not c.get("single_source") else "0.5×Google only (single source)"
    return (f"Score {_num(c['score']):.0f} = {formula}. " + "; ".join(parts) +
            ". The search-interest index is relative within Google's export, not a search volume. Heuristic, not a forecast.")


def wikimedia_summary(proposal: dict) -> tuple[str, str]:
    """Wikipedia evidence line. Shows exactly the values that exist; a missing number is never formatted or invented."""
    w = (proposal.get("trend") or {}).get("wikimedia")
    if not isinstance(w, dict):
        return "warn", "Wikipedia pageviews: not part of this proposal's evidence."
    status = w.get("status")
    if status == "available":
        article = _md(w.get("article")) if w.get("article") else "article not named"
        parts = []
        if _num(w.get("score")) is not None:
            parts.append(f"change score {_num(w['score']):.0f}/100")
        prev, latest, pct = _num(w.get("views_previous_7d")), _num(w.get("views_latest_7d")), _num(w.get("change_pct"))
        if prev is not None and latest is not None:
            parts.append(f"7-day views {prev:,.0f} → {latest:,.0f}")
        elif latest is not None:
            parts.append(f"latest 7-day views {latest:,.0f}")
        elif prev is not None:
            parts.append(f"previous 7-day views {prev:,.0f}")
        if pct is not None:
            parts.append(f"change {pct:+.0f}%")
        return "ok", f"Wikipedia pageviews ({article}): " + (", ".join(parts) if parts else "reported as available, but without any numbers") + "."
    reasons = {"no_article_found": "no usable article", "no_data": "no data for the period",
               "unavailable": f"source unavailable ({_md(w.get('error') or 'unknown error')})"}
    detail = _md(w["reason"]) if isinstance(w.get("reason"), str) and w.get("reason") else reasons.get(status, "status unknown")
    return "warn", f"Wikipedia pageviews: {detail}. This signal could NOT be checked."


def evidence_details(proposal: dict) -> dict:
    """Everything the 'evidence and original labels' expander shows, tolerant of missing or odd optional fields."""
    t, a = proposal.get("trend") or {}, proposal.get("archive") or {}
    pts = t.get("points")
    sources = [str(x) for x in (t.get("sources") or []) if isinstance(x, str)]
    ranked = f"Original topic: **{_md(proposal.get('topic'))}** · supplied rank {_md(proposal.get('rank'))}"
    if "rank_score" in proposal:
        ranked += f" · supplied rank_score {_md(proposal['rank_score'])} (shown as supplied, not recalculated here)"
    dated = []
    for r in a.get("similar_recipes") or []:
        if isinstance(r, dict):          # only dates that really exist: a None/empty value is missing data, not a date found
            dated += [(r.get("title"), k, r[k]) for k in ("published", "publication_date", "date_source", "created", "date_created")
                      if r.get(k) not in (None, "", [], {})]
    fields = pitch_fields(proposal)
    terms = []
    for t_ in (t.get("google_terms") or []) if isinstance(t.get("google_terms"), list) else []:
        if isinstance(t_, dict) and isinstance(t_.get("term"), str):
            inc, idx = _num(t_.get("increase_pct")), _num(t_.get("search_interest_index"))
            terms.append(f"'{_md(t_['term'])}' ({_md(t_.get('kind', '?'))}, {_md(t_.get('signal', '?'))}"
                         + (f", {inc:+.0f}%" if inc is not None else "") + (f", index {idx:.0f}/100" if idx is not None else "") + ")")
    notes = proposal.get("review_notes") if isinstance(proposal.get("review_notes"), dict) else {}
    original = notes.get("original") if isinstance(notes.get("original"), dict) else {}
    return {
        "source_terms": ("Original German source terms: " + "; ".join(terms)) if terms else None,
        "rank_method": (f"Ranking method as supplied: {_md(proposal['rank_method'])}"
                        if isinstance(proposal.get("rank_method"), str) and proposal["rank_method"] else None),
        "team_changes": [_md(c) for c in notes.get("changes", []) if isinstance(c, str)] if isinstance(notes.get("changes"), list) else [],
        "original": {k: _md(v) for k, v in original.items() if isinstance(v, str) and v},
        "why_full": fields["why_now"], "brand_full": fields["brand_reason"], "more_angles": fields["more_angles"],
        "coverage_full": coverage_summary(proposal)[1],
        "ranked": ranked,
        "sources": "Trend sources: " + "; ".join(_md(x) for x in sources),
        "trend_summary": trend_summary(proposal),
        "wikipedia": wikimedia_summary(proposal)[1],
        "trend_line": f"Trend score {_md(t.get('score'))} · points in series: {len(pts) if isinstance(pts, list) else 0}",
        "archive_line": (f"Archive as supplied: match_status={_md(a.get('match_status'))}, repetition_risk label={_md(a.get('repetition_risk'))} "
                         "(a label from the source; not verified and not used by the editor desk)."),
        "dates_line": ("Dates found in the supplied archive records (CMS/import dates, NOT publication dates): " +
                       "; ".join(f"{_md(t)}: {_md(k)}={_md(v)}" for t, k, v in dated[:12])) if dated else None,
    }


def highlight_change(before: str, after: str) -> tuple[str, str]:
    """Markdown for a before/after pair with the difference marked at word level: removed words red and struck through in the
    'before' line, added words green and bold in the 'after' line. All text is escaped first (it comes from drafts)."""
    bw, aw = str(before).split(), str(after).split()
    b_out, a_out = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=bw, b=aw, autojunk=False).get_opcodes():
        old, new = " ".join(bw[i1:i2]), " ".join(aw[j1:j2])
        if tag == "equal":
            b_out.append(_md(old))
            a_out.append(_md(new))
            continue
        if old:
            b_out.append(f":red[~~{_md(old)}~~]")
        if new:
            a_out.append(f":green[**{_md(new)}**]")
    return " ".join(b_out), " ".join(a_out)


def trail_label(item: dict) -> str:
    """One readable line for the decision trail (markdown, escaped). Unknown events fall back to the raw event name."""
    e = item.get("event", "")
    def g(k, default=""):
        return item.get(k, default)
    labels = {
        "proposals_ready": lambda: f"Proposals loaded ({g('n')})",
        "editor_selected": lambda: f"You chose: {_md(g('topic'))}" + (f" · notes: {_md(g('notes'))}" if g("notes") else ""),
        "editor_rejected_all": lambda: "You asked for other topics" + (f": {_md(g('note'))}" if g("note") else ""),
        "recipes_generated": lambda: "Two drafts created",
        "review": lambda: f"Review round {g('round')}: {g('hard_open', 0)} hard and {g('soft_open', 0)} soft open, {g('fixed', 0)} fixed",
        "revised": lambda: "Drafts revised" + (f" with your comment: {_md(g('comment'))}" if g("comment") else ""),
        "editor_sent_back": lambda: f"You sent the drafts back: {_md(g('comment'))}",
        "editor_acknowledged_soft": lambda: "You acknowledged a warning" + (f": {_md(g('reason'))}" if g("reason") else ""),
        "editor_discarded_recipes": lambda: "You discarded the drafts" + (f": {_md(g('reason'))}" if g("reason") else ""),
        "agent_error": lambda: f"Problem in step '{_md(g('step'))}' (attempt {g('attempt')})",
        "revision_discarded": lambda: "A revision failed and was discarded; the last reviewed draft stays",
        "approved": lambda: f"Approved: {len(g('cards', []))} cards exported" + (f", {len(g('warnings', []))} warning(s) noted" if g("warnings") else ""),
        "render_error": lambda: "Exporting the cards failed",
    }
    try:
        return labels[e]() if e in labels else _md(e)
    except Exception:  # noqa: BLE001 - a log line must never break the page
        return _md(e)
