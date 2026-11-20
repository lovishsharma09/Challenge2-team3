from __future__ import annotations


BRAND_RULES = (
    "Warm, practical, family-friendly German food",
    "Clear, approachable preparation",
    "Seasonal ingredients and current food culture",
    "No luxury-only positioning",
)


class BrandAgent:
    def score(self, topic: str) -> dict:
        family_terms = {"cookie", "bread", "pasta", "potato", "cake", "stollen"}
        lowering = 12 if any(term in topic.lower() for term in family_terms) else 0
        score = 88 - lowering
        return {
            "score": max(55, score),
            "rules": list(BRAND_RULES),
            "reasoning": (
                f"{topic} is suitable for an approachable das schmeckt! recipe "
                "when framed with familiar ingredients and clear weekday preparation."
            ),
        }

