from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import date, timedelta

from .config import ARCHIVE_MANIFEST_PATH, ROOT
from .logging import DecisionLog
from .nutrition_agent import NutritionAgent
from .proposal_agent import ProposalAgent
from .recipe_agent import RecipeAgent
from .renderer import HtmlRenderer
from .review_agent import ReviewAgent
from .trend_agent import TrendAgent


class ChallengeOrchestrator:
    def __init__(self, log_path: Path | None = None):
        self.root = ROOT
        self.log = DecisionLog(log_path or (self.root / "logs" / "decisions.jsonl"))
        self.trend = TrendAgent(
            self.root / "data" / "trends" / "google-trends"
        )
        archive_path = ARCHIVE_MANIFEST_PATH if ARCHIVE_MANIFEST_PATH.exists() else None
        self.proposals = ProposalAgent(archive_path)
        self.recipe = RecipeAgent()
        self.review = ReviewAgent()
        self.nutrition = NutritionAgent(
            self.root
            / "data"
            / "nutrition"
            / "Schweizer_Nahrwertdatenbank(Generische Lebensmittel).csv"
        )
        self.renderer = HtmlRenderer()

    def generate_proposals(self, limit: int = 5) -> dict[str, list[dict]]:
        signals = self.trend.propose_from_local_signals(limit=12)
        end = date(2026, 11, 18)
        start = end - timedelta(days=29)
        for signal in signals:
            signal = self.trend.enrich_with_brave(signal)
            signal = self.trend.enrich_with_wikimedia(signal, start, end)
        accepted, rejected = self.proposals.build(signals, limit=limit)
        payload = {
            "proposals": accepted,
            "rejected_topics": rejected,
        }
        self.log.write("proposal_pipeline", "proposals_generated", payload)
        return payload

    def generate_recipes(
        self,
        selected_proposal: dict,
        steering_notes: str = "",
        render_output: bool = True,
    ) -> dict[str, Any]:
        bundle = self.recipe.generate(selected_proposal, steering_notes)
        review_report = self.review.review(bundle, steering_notes)
        loops = 0
        while not review_report["passed"] and loops < 2:
            loops += 1
            review_report["loops_used"] = loops
            review_report["corrections_made"].append(
                "The recipe draft was regenerated according to the structured review report."
            )
            bundle = self.recipe.generate(selected_proposal, steering_notes)
            review_report = self.review.review(bundle, steering_notes)
            review_report["loops_used"] = loops

        nutrition_results = []
        for recipe in bundle["recipes"]:
            nutrition_results.append({
                "recipe_title": recipe["title"],
                "nutrition": self.nutrition.calculate(
                    recipe["ingredients"],
                    recipe["servings"],
                ),
            })

        result = {
            "proposal": selected_proposal,
            "recipes": bundle,
            "review": review_report,
            "nutrition": nutrition_results,
        }
        self.log.write("orchestrator", "recipe_review_complete", result)

        if render_output:
            combined_nutrition = nutrition_results[0]["nutrition"] if nutrition_results else {
                "per_serving": {}
            }
            output_path = self.root / "output" / "recipes.html"
            self.renderer.render(bundle, combined_nutrition, output_path)
            result["output_html"] = str(output_path)
        return result
