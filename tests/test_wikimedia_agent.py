import unittest
from datetime import date
from unittest.mock import Mock, patch

from src.challenge2.wikimedia_agent import WikimediaAgent


class WikimediaAgentTest(unittest.TestCase):
    def test_fetches_and_scores_pageviews(self):
        items = [
            {
                "timestamp": f"202610{i:02d}00",
                "views": 1000 + i,
            }
            for i in range(1, 16)
        ] + [
            {
                "timestamp": f"202611{i:02d}00",
                "views": 2000 + i,
            }
            for i in range(1, 16)
        ]
        response = Mock(
            status_code=200,
            ok=True,
        )
        response.json.return_value = {"items": items}

        with patch("src.challenge2.wikimedia_agent.requests.get", return_value=response) as get:
            result = WikimediaAgent().fetch_pageviews(
                "Vanillekipferl (Food)",
                date(2026, 10, 18),
                date(2026, 11, 18),
            )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["article"], "Vanillekipferl")
        self.assertEqual(len(result["points"]), 30)
        self.assertIsInstance(result["score"], int)
        request_url = get.call_args.args[0]
        self.assertIn("/de.wikipedia.org/", request_url)
        self.assertIn("Vanillekipferl", request_url)
        self.assertEqual(
            get.call_args.kwargs["headers"]["User-Agent"].startswith("Challenge2-Team3"),
            True,
        )

    def test_distinguishes_missing_article(self):
        response = Mock(status_code=404, ok=False)
        with patch("src.challenge2.wikimedia_agent.requests.get", return_value=response):
            result = WikimediaAgent().fetch_pageviews(
                "Imaginary Recipe Topic",
                date(2026, 10, 18),
                date(2026, 11, 18),
            )

        self.assertEqual(result["status"], "no_article_found")
        self.assertEqual(result["points"], [])


if __name__ == "__main__":
    unittest.main()
