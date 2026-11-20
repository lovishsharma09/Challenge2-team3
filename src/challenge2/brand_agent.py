from __future__ import annotations


BRAND_RULES = (
    "Alltagstauglich und nachkochbar",
    "Saisonaler oder regionaler Bezug",
    "Fleisch und klassische Gerichte werden bevorzugt",
    "Hoher Kochanspruch passend zur Marke",
    "Kurze Zutatenlisten und klare Zubereitung",
    "Veggie-Angebot optional",
)
POSITIVE_TERMS = (
    "saisonal", "regional", "heimisch", "fleisch", "klassisch",
    "gemüse", "rosenkohl", "kartoffel", "apfel", "kürbis",
)
NEGATIVE_TERMS = (
    "gesundheits", "detox", "exotisch", "komplex", "molekular",
)


class BrandAgent:
    def score(self, topic: str) -> dict:
        normalized = topic.casefold()
        score = 78
        positive = [term for term in POSITIVE_TERMS if term in normalized]
        negative = [term for term in NEGATIVE_TERMS if term in normalized]
        score += min(12, len(positive) * 4)
        score -= min(20, len(negative) * 10)
        familiar_terms = ("cookie", "bread", "pasta", "potato", "cake", "stollen")
        if any(term in normalized for term in familiar_terms):
            score -= 4
        score = max(0, min(100, score))
        reasons = [
            f"{topic} kann zum Claim 'Der Alltagsbegleiter mit gehobenem Anspruch' passen.",
        ]
        if positive:
            reasons.append("Positive Marken-Signale: " + ", ".join(sorted(set(positive))) + ".")
        if negative:
            reasons.append("Negative Marken-Signale: " + ", ".join(sorted(set(negative))) + ".")
        reasons.append("Bewertung: alltagstauglich, klar formuliert und ohne unnötig lange Zutatenliste.")
        return {
            "score": score,
            "fit": "high" if score >= 80 else "medium" if score >= 60 else "low",
            "rules": list(BRAND_RULES),
            "reasoning": " ".join(reasons),
            "positive_signals": sorted(set(positive)),
            "negative_signals": sorted(set(negative)),
        }

