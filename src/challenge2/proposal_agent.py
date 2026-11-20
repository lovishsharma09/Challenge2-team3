from __future__ import annotations

import re

from .brand_agent import BrandAgent
from .archive_agent import ArchiveAgent
from pathlib import Path


class ProposalAgent:
    def __init__(self, archive_path: Path | None = None):
        self.brand = BrandAgent()
        self.archive = ArchiveAgent(archive_path)

    def build(self, trend_signals: list[dict], limit: int = 5) -> tuple[list[dict], list[dict]]:
        candidates: list[dict] = []
        for index, signal in enumerate(trend_signals, start=1):
            topic = signal["topic"]
            stable_key = re.sub(r"[^a-z0-9]+", "-", topic.casefold()).strip("-")
            brand = self.brand.score(topic)
            archive = self.archive.check(topic)
            proposal = {
                "id": f"proposal-{stable_key or index}",
                "title": f"{topic}: ein modernes das schmeckt! Rezept",
                "topic": topic,
                "trend": {
                    "score": signal["trend_score"],
                    "points": signal.get("trend_points", []),
                    "sparkline": [
                        point["value"] for point in signal.get("trend_points", [])
                    ],
                    "wikimedia": {
                        "status": signal.get("wikimedia", {}).get("status", "unavailable"),
                        "article": signal.get("wikimedia", {}).get("article"),
                        "score": signal.get("wikimedia", {}).get("score"),
                        "points": signal.get("wikimedia_points", []),
                        "error": signal.get("wikimedia", {}).get("error"),
                        "period_start": signal.get("wikimedia", {}).get("period_start"),
                        "period_end": signal.get("wikimedia", {}).get("period_end"),
                        "method": signal.get("wikimedia", {}).get("method"),
                    },
                    "why_relevant": signal["why_relevant"],
                    "sources": signal["sources"],
                },
                "brand_fit": brand,
                "archive": archive,
                "recipe_ideas": [
                    f"Einfache {topic}-Variante in einem 30-Minuten-Format",
                    f"Saisonale {topic}-Version zum Vorbereiten",
                    f"Klassische {topic}-Version mit klarer Wochenendoption",
                ],
            }
            trend_score = signal["trend_score"]
            brand_score = brand["score"]

            archive_scores = {
                "low": 100,
                "medium": 60,
                "high": 20,
                "unknown": 50,
            }
            archive_score = archive_scores[archive["repetition_risk"]]
            rank_score = (
                trend_score * 0.50
                + brand_score * 0.30
                + archive_score * 0.20
            )
            proposal["rank_components"] = {
                "google_trends": {
                    "score": trend_score,
                    "weight": 0.50,
                    "contribution": round(trend_score * 0.50, 1),
                },
                "brand_fit": {
                    "score": brand_score,
                    "weight": 0.30,
                    "contribution": round(brand_score * 0.30, 1),
                },
                "archive_novelty": {
                    "score": archive_score,
                    "risk": archive["repetition_risk"],
                    "weight": 0.20,
                    "contribution": round(archive_score * 0.20, 1),
                },
                "wikimedia": {
                    "score": signal.get("wikimedia", {}).get("score"),
                    "status": signal.get("wikimedia", {}).get("status"),
                    "used_in_numeric_rank": False,
                },
            }
            proposal["rank_method"] = (
                "50% Google Trends + 30% brand fit + 20% archive novelty "
                "(high risk=20, medium=60, low=100, unknown=50). "
                "Wikimedia is corroborating evidence and is not added to this numeric rank."
            )
            proposal["rank_score"] = round(rank_score, 1)
            candidates.append(proposal)

        candidates.sort(key=lambda item: item["rank_score"], reverse=True)
        accepted = candidates[:limit]
        rejected = []
        for proposal in candidates[limit:]:
            reason = "Not included in the top five after combined trend and brand ranking."
            if proposal["brand_fit"]["fit"] == "low":
                reason = "Low estimated das schmeckt! brand fit."
            elif proposal["archive"]["repetition_risk"] == "high":
                reason = "High repetition risk against comparable archive recipes."
            elif proposal["archive"]["match_status"] == "archive_unavailable":
                reason = "Kept outside the shortlist because the archive export is unavailable."
            rejected.append({
                "id": proposal["id"],
                "topic": proposal["topic"],
                "reason": reason,
                "rank_score": proposal["rank_score"],
            })
        for rank, proposal in enumerate(accepted, start=1):
            proposal["rank"] = rank
        return accepted, rejected
