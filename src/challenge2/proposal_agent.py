from __future__ import annotations

import re

from .brand_agent import BrandAgent
from .archive_agent import ArchiveAgent


class ProposalAgent:
    def __init__(self):
        self.brand = BrandAgent()
        self.archive = ArchiveAgent()

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
            combined = (signal["trend_score"] + brand["score"]) / 2
            wikimedia_score = signal.get("wikimedia", {}).get("score")
            if isinstance(wikimedia_score, (int, float)):
                combined = combined * 0.75 + wikimedia_score * 0.25
            if archive["repetition_risk"] == "high":
                combined -= 8
            proposal["rank_score"] = round(combined, 1)
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
