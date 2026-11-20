# CLAUDE.md — Das schmeckt! Hackathon (Challenge 2)

Goal: agentic workflow that turns food trends into 2 reviewed, nutrition-calculated
recipe cards (HTML) for "Das schmeckt!". All data contracts: see CONTRACTS.md.

## Pipeline (one file per stage in /src/stages)
01_trends -> 02_brand_fit -> 03_archive_check -> 04_proposals -> 05_selection (human)
-> 06_recipes -> 07_review (max 2 loops) -> 08_nutrition -> 09_html_cards

Each stage: reads one JSON from /output, writes one JSON to /output. No hidden state.
`python main.py --stage N` runs one stage; `python main.py` runs all with the last selection.

## Hard rules (taken from the template requirements and review checklist)
1. Content fidelity: never invent, auto-convert or shorten ingredients, quantities,
   units, times or steps when rendering. Template renders exactly what recipe.json holds.
2. Nutrition: no value without a database row or a documented conversion rule.
   Log original ingredient, matched DB entry, conversion rule, confidence.
   Never label a value "per portion" unless it was computed per serving.
3. Every card carries the label: AI-generated recipe draft.
4. Review loop: max 2 iterations. Review agent scores the 8 criteria in CONTRACTS.md.
5. Every claim in proposals must point to a source row (file + row), not free text.
6. Report weak evidence openly: Google "rising" queries have search interest 0-1
   (tiny base), so flag `low_base`. Do not present percentages as strong evidence alone.
7. Selection step supports 1 or 2 picks (`--picks 1|2`): briefing says 1, deck says 2.

## Data gotchas
- Google Trends CSV: "increase percent" is a German string like "1.450 %" -> parse to 1450.
  "search interest" is 0-100 relative index.
- Wikimedia fallback xlsx: sheets Overview / Topic summary / Daily pageviews. Use
  columns Previous 7d views, Latest 7d views, Change percent, Review required.
  Rows with Review required = 1 must be checked before use.
- recipe-archive SQL (rezepte_export_topicmap) is a TOPIC MAP, not recipes: ingredient
  vocabulary, units, thesaurus (diet, region, method, season, occasion). Real recipe
  export is on SharePoint. Archive check needs that export.
- Nutrition CSV: Swiss database v7.1, header on row 3, columns incl. Name, Synonyme,
  Kategorie, Dichte (use for ml -> g), Bezugseinheit. Check the unit basis before math.
- Recipe language: German (confirm against sample issues before building prompts).

## Working rules
- Branch per person, small PRs into main, merge at least every 1-2 hours.
- Never commit keys. Use .env (see .env.example): TESSERACTED_API_KEY, BFL_API_KEY, BRAVE_API_KEY.
- Do not change a schema in CONTRACTS.md without telling the team in chat first.
- Stage code must run on the fallback data if a live API fails (Wikimedia, Brave).
- Keep LLM prompts in /src/prompts as files, not inline strings.
