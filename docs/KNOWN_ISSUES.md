# Known issues (found 2026-11-20 while reviewing main @ 502f92d)

Status legend: OPEN = not fixed. Owner = who should decide/fix. Found by reading the code, tests pass anyway.

## Confirmed by code reading
| # | Area | Issue | Owner |
|---|------|-------|-------|
| 1 | orchestrator.py / renderer.py | Only `nutrition_results[0]` is passed to the renderer, so recipe 2's card shows recipe 1's nutrition. The test only checks that the HTML file exists. | renderer / nutrition owner |
| 2 | renderer.py | Missing nutrition values are printed as `0 kcal`. Brief says: never invent values, never show a missing reference as "per serving". | renderer owner |
| 3 | renderer.py | Ignores the supplied A4 template (templates/Das-schmeckt-Recipe-Preview-A4.html) and does not render images. | renderer owner |
| 4 | orchestrator.py | "Correction loop" regenerates both recipes from scratch; the review report is never passed to the recipe agent. | review / recipe owner |
| 5 | review_agent.py | Criteria differ from the 8 official ones in references/Recipe Review Criteria.docx (e.g. "all ingredients used in the steps" is missing). Steering-notes check is a plain substring match. | review owner |
| 6 | review_agent.py / orchestrator.py | One review report for both recipes; issues have no type (hard/soft) and no status (open/fixed/dismissed). | Person B (planned) |
| 7 | whole flow | No human decision after generation: no approve / send back with comment / dismiss false alarm / reject all five. | Person B (planned) |
| 8 | orchestrator.py | Fully synchronous, no progress feedback; real LLM calls will block the UI. | Person B (planned) |

## Not verified
- Streamlit UI was not opened in a browser.
- Everything is mock-first: no real LLM or image calls were exercised.
