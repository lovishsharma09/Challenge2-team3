"""Honest display helpers for proposal evidence (pure functions, unit-tested).

Handles the optional fields of the Person A handoff contract (schemas/proposals.schema.json on main):
  archive: status, available, match_status (matches_found|no_match_found|archive_unavailable), assumption
  trend.wikimedia: status (available|no_article_found|no_data|unavailable), article, score, error
Missing information must never be shown as "nothing found".
"""
from __future__ import annotations


def archive_summary(proposal: dict) -> tuple[str, str]:
    """Returns (level, text); level is 'ok' | 'warn' for the UI."""
    a = proposal.get("archive") or {}
    similar = [r.get("title", "?") for r in a.get("similar_recipes", [])]
    risk = a.get("repetition_risk", "unknown")
    gap = a.get("content_gap", "")
    status = a.get("match_status")
    if status == "archive_unavailable" or a.get("available") is False:
        return "warn", ("Archive not available: similar recipes and repetition risk could NOT be checked."
                        + (f" Note: {a['assumption']}" if a.get("assumption") else ""))
    if status == "no_match_found" or (not similar and status is None):
        head = "No similar recipe found in the archive."
    else:
        head = f"Similar archive recipes: {', '.join(similar)}."
    tail = f" Repetition risk: {risk}." + (f" Gap: {gap}" if gap else "")
    if a.get("assumption"):
        tail += f" Assumption: {a['assumption']}"
    return ("warn" if risk == "unknown" else "ok"), head + tail


def wikimedia_summary(proposal: dict) -> tuple[str, str]:
    w = (proposal.get("trend") or {}).get("wikimedia")
    if not w:
        return "warn", "Wikipedia pageviews: not part of this proposal's evidence."
    status = w.get("status")
    if status == "available":
        score = w.get("score")
        return "ok", f"Wikipedia pageviews ({w.get('article')}): change score {score if score is not None else 'n/a'}/100."
    reasons = {"no_article_found": "no matching article found", "no_data": "no data for the period",
               "unavailable": f"source unavailable ({w.get('error') or 'unknown error'})"}
    return "warn", f"Wikipedia pageviews: {reasons.get(status, 'status unknown')}: this signal could NOT be checked."
