# Challenge 2 – From Food Trends to New “das schmeckt!” Recipes

Turn food trends into two recipe drafts for *das schmeckt!*.

| Folder | What it contains |
|---|---|
| [`briefing/`](briefing/) | [Full challenge brief](briefing/Case%20Burda%20Media.docx). |
| [`references/`](references/) | [Brand guidelines](references/MarkenCI_das%20schmeckt.pdf), [recipe review checklist](references/Recipe%20Review%20Criteria.docx), and [four sample magazine issues (ZIP)](references/Das-Schmeckt-Sample-Issues.zip) with examples of editorial style and recipe layouts. |
| [`data/`](data/) | Inputs for [trend research](data/trends/), archive comparison, and nutrition calculations. |
| [`data/trends/google-trends/`](data/trends/google-trends/) | Search data for Germany. Top Searches for [queries](data/trends/google-trends/searched_with_top-searches_queries_DE_20261018-1818_20261118-1818.csv) and [topics](data/trends/google-trends/searched_with_top-searches_topics_DE_20261018-1818_20261118-1818.csv), and Rising Searches for [queries](data/trends/google-trends/searched_with_rising-searches_queries_DE_20261018-1818_20261118-1818.csv) and [topics](data/trends/google-trends/searched_with_rising-searches_topics_DE_20261018-1818_20261118-1818.csv). |
| [`data/trends/wikimedia/`](data/trends/wikimedia/) | [Pageviews API guide](data/trends/wikimedia/Food%20Trends%20Wikimedia%20API.docx) and [fallback spreadsheet](data/trends/wikimedia/Wikimedia_Pageviews_Fallback_2026-11-18.xlsx) with daily views and week-over-week changes. |
| [`data/recipe-archive/`](data/recipe-archive/) | [SQL export](data/recipe-archive/rezepte_export_topicmap.sql.zip) with ingredient names, units, and recipe categories. |
| [`data/nutrition/`](data/nutrition/) | [Swiss Food Composition Database extract](data/nutrition/Schweizer_Nahrwertdatenbank%28Generische%20Lebensmittel%29.csv) for calculating nutrition per serving. |
| [`templates/`](templates/) | [A4 recipe card example](templates/Das-schmeckt-Recipe-Preview-A4.html) and [HTML output requirements](templates/Das-schmeckt-Requirements-HTML.txt). |

The recipe export is available on SharePoint, and you can get the Black Forest Labs API key by scanning the QR code in the presentation.

## Runnable implementation

This repository includes a mock-first implementation of Person A, Person B and Person C.

### Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Brave Search API

The key is optional for the demo. Local Google Trends data is used as a fallback.

Set the key either in the environment:

```powershell
$env:BRAVE_SEARCH_API_KEY="YOUR_KEY"
```

or create a local `.env` file by copying `.env.example` and replacing the value:

```dotenv
BRAVE_SEARCH_API_KEY=YOUR_KEY
```

The `.env` file is gitignored. Do not paste the key into `.env.example` or source files.

The key is sent only as the Brave `x-subscription-token` header.

### Run

```powershell
streamlit run app.py
```

The test run is:

```powershell
python -m unittest discover -s tests -v
```

Generated proposals, review reports and assumptions are written to
`logs/decisions.jsonl`. Generated HTML is written to `output/recipes.html`.
