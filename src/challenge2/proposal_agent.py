from __future__ import annotations

import re

from .brand_agent import BrandAgent
from .archive_agent import ArchiveAgent


class ProposalAgent:
    def __init__(self):
        self.brand = BrandAgent()
        self.archive = ArchiveAgent()

    def build(self, trend_signals: list[dict], limit: int = 5) -> tuple[list[dict], list[dict]]:
        accepted: list[dict] = []
        rejected: list[dict] = []
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
                    "why_relevant": signal["why_relevant"],
                    "sources": signal["sources"],
                },
                "brand_fit": brand,
                "archive": archive,
                "recipe_ideas": [
                    f"Einfache {topic}-Variante in einem 30-Minuten-Format",
                    f"Saisonale {topic}-Version zum Vorbereiten",
                ],
            }
            combined = (signal["trend_score"] + brand["score"]) / 2
            if archive["repetition_risk"] == "high":
                combined -= 8
            proposal["rank_score"] = round(combined, 1)
            if len(accepted) < limit:
                accepted.append(proposal)
            else:
                rejected.append({
                    "id": proposal["id"],
                    "topic": topic,
                    "reason": "Not included in the top-ranked shortlist.",
                })
        accepted.sort(key=lambda item: item["rank_score"], reverse=True)
        for rank, proposal in enumerate(accepted, start=1):
            proposal["rank"] = rank
        return accepted, rejected
