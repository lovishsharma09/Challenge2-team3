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

### Wikimedia pageviews

The Trend Agent also queries the keyless Wikimedia REST pageviews API for
selected German Wikipedia articles. Requests use a descriptive
`Challenge2-Team3` User-Agent. Results include article name, date, daily
pageviews, availability status, and a transparent 0-100 change score.

### Run

```powershell
streamlit run app.py
```

The test run is:

```powershell
python -m unittest discover -s tests -v
```

To start the mock Person-A HTML page and JSON backend:

```powershell
python -m src.challenge2.api_server
```

Open `http://127.0.0.1:8000/mock` or request
`http://127.0.0.1:8000/api/proposals`.

### Supplied 5,000-recipe archive

The shared archive is available at
`C:\Users\User\Documents\OMMAX Hackathon\auswahl_manifest.json` with
its 5,000 XML files in the adjacent `rezepte_export` directory.

Set `DAS_SCHMECKT_ARCHIVE_MANIFEST` to the manifest path if the archive is
installed somewhere else. The Agent:

1. Loads each XML file listed by the manifest.
2. Verifies the manifest SHA-256 checksum against the original XML bytes.
3. Reads the title, ingredients, quantities, units, preparation steps,
   serving count and available dates.
4. Searches by title and ingredient-name/ID text for candidate matches.
5. Reports `matches_found` or `no_match_found`, plus repetition risk,
   recurring ingredients, methods and the most recent available date.

The XML `DateCreated` value is currently used as the publication date
proxy. It is not the same as a verified magazine publication date. The
handoff therefore includes `date_source` and should not present this value
as a confirmed issue date. Where no date is available, it remains `null`.

Generated proposals, review reports and assumptions are written to
`logs/decisions.jsonl`. Generated HTML is written to `output/recipes.html`.

## Score engine

The score engine is deliberately transparent and is based on separate
evidence. It does not turn missing evidence into a positive or negative
fact.

### 1. Google Trends score

The Trend Agent reads the supplied Rising Topics CSV for Germany.
For each topic it reads `search interest` and calculates:

```text
Google Trends score = min(100, max(0, search interest))
```

The score is stored with a dated point:

```text
date: 2026-11-18
source: Google Trends Rising Topics
period: 2026-10-18 to 2026-11-18
value: original search interest
```

Example: a topic with search interest `23` receives `23 / 100`.

### 2. Brave Search evidence

Brave Search is used as a qualitative corroboration source. It returns
recent German web results for the topic and adds their titles, URLs,
descriptions and result count to the proposal.

Brave results are **not converted into an independent numeric score**.
They improve the transparency and explanation of the topic; the currently
implemented ranking does not invent a Brave percentage.

### 3. Wikimedia pageview score

The Wikimedia agent converts a topic to a German Wikipedia article name,
removes labels such as `(Food)`, and requests all-agent daily pageviews
from `2026-10-18` through `2026-11-18`.

When at least 14 observations are available, it splits the series into
two halves:

```text
previous average = average(pageviews in first half)
recent average   = average(pageviews in second half)
percentage change = ((recent average - previous average) / previous average) x 100
Wikimedia score = min(100, max(0, round(50 + percentage change)))
```

With fewer than 14 observations, it uses the average daily pageviews:

```text
Wikimedia score = min(100, max(0, round(average daily pageviews / 1000 x 100)))
```

The score is only returned with `status: "available"`. Other states are:

| Status | Meaning |
|---|---|
| `available` | A dated pageview series was returned |
| `no_article_found` | The topic has no resolved German Wikipedia article |
| `no_data` | Wikimedia returned no pageview observations |
| `unavailable` | The API request failed or returned an invalid response |

No Wikimedia point or score is fabricated for these states.

### 4. Brand-fit score

The Brand Agent starts each topic at `78 / 100`, then applies the
brand-guide rules:

- Add `4` points for each matching positive term, up to `12` points.
- Subtract `10` points for each matching negative term, up to `20` points.
- Subtract `4` points for familiar English terms such as `cookie`, `bread`,
  `pasta`, `potato`, `cake`, or `stollen`.
- Clamp the result to `0-100`.

Positive terms include `saisonal`, `regional`, `heimisch`, `fleisch`,
`klassisch`, `gemüse`, `rosenkohl`, `kartoffel`, `apfel`, and `kürbis`.
Negative terms include `gesundheits`, `detox`, `exotisch`, `komplex`, and
`molekular`.

The category is:

```text
high   = 80-100
medium = 60-79
low    = 0-59
```

The result also contains the matched positive and negative terms and a
human-readable reasoning string.

### 5. Archive risk

When a complete archive adapter is unavailable, the proposal has:

```text
status: archive_unavailable
available: false
match_status: archive_unavailable
repetition_risk: unknown
similar_recipes: []
```

This is not the same as `no_match_found`. It means no evidence was available
to decide whether a match exists.

With a loaded JSON or CSV archive, the agent records matching recipes,
publication dates, recurring ingredients, recurring methods and one of:

```text
no_match_found
matches_found
```

Archive repetition risk is:

- `unknown` when the archive export is unavailable.
- `low` when no close match is found.
- `medium` when a nearby match exists.
- `high` when two or more close matches exist.

### 6. Combined proposal rank
The final rank is a weighted evidence score:

```text
rank_score =
  Google Trends score x 0.50
  + Brand-fit score x 0.30
  + archive novelty score x 0.20
```

Archive novelty is derived from repetition risk:

| Archive risk | Novelty score |
|---|---:|
| low | 100 |
| medium | 60 |
| high | 20 |
| unknown | 50 |

Wikimedia is kept as corroborating trend evidence. It is not added to this
numeric rank until a separate, documented Wikimedia averaging method is
approved. This avoids one changing pageview series changing the main score
through a hidden 25% multiplier.

Each proposal contains `rank_components`, which shows every raw score,
weight and contribution. The result is rounded to one decimal and sorted
by descending `rank_score`.

Rejected topics are reported with the reason that prevented them from
entering the top five, including low brand fit, high repetition risk,
archive evidence being unavailable, or simply not being in the top ranking.
