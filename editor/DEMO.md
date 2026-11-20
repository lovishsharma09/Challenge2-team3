# Demo runbook (5 minutes) · das schmeckt! Editor Desk

## 0. Before you go on (10 min earlier)

```
cd /Users/user/Challenge2-team3
.venv/bin/python -m editor.preflight --live        # all lines OK and "READY"
.venv/bin/streamlit run editor/app.py              # opens http://localhost:8501
```

The batch path is preloaded from `.env`: the screen should say **"Team draft for Deyan's review · Not approved by Person A"**.
In the sidebar choose **Recipe engine → Person C pipeline · live text gateway**, then press **Load the five pitches** (this stays on the first screen until you start).
Keep `data/local/demo-backup/` open in Finder: it holds screenshots and the cards of a successful live run (Rinderroulade).

## 1. The story in one sentence

AI does the research and the first drafts; **the editor stays in control**: every number is traceable, every correction is visible, nothing is exported before the editor approves.

## 2. Script

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00 | Pitches | Point at the notice | "Five pitches from the Google Trends and Wikipedia data, the brand guide and the 5,000-recipe archive. This is a team draft: Person A's batch, improved, not yet approved by Person A. The screen says so." |
| 0:30 | Pitches | Scroll the five choices, open **View evidence** on #5 | "Each choice is one angle, one reason, one button. Behind it: the trend numbers (Google +30%, Wikipedia +15%), the brand-guide quotes, and what the archive holds (6 comparable recipes). We show coverage only: the export has no publication dates, so we never claim a 'last published' or a 'repetition risk'." |
| 1:30 | Pitches | Click **Choose this pitch** on #5, type a steering note ("alltagstauglich, nicht mehr als 12 Zutaten"), click **Generate two recipes** | "The editor picks one pitch and steers it. Now Person C's pipeline writes two different recipes." |
| 1:45 | Progress box (~60–90 s) | Narrate while it runs | "It generates two recipes, then reviews each against the 8 criteria of the checklist: code checks for quantities, units and ingredient use, plus an LLM for culinary logic and brand fit." |
| 2:45 | Review | Point at the green **Ready to approve** and open **Review history** | "Round 1 found hard problems; the system corrected them; round 2 is clean. Problems that code can prove block approval and cannot be dismissed. Judgment remarks stay visible but never block." |
| 3:15 | Review | Point at **Latest correction** next to the buttons | "This is what changed: the removed words in red, the added words in green. The editor decides with the evidence in front of them." |
| 3:45 | Review | Click **Approve both recipes** | "Only now are the cards exported." |
| 4:00 | Approved | Show card 1, scroll to nutrition, open **Nutrition assumptions and gaps** | "A4 card in the magazine template, AI label on every card. Nutrition per serving from the Swiss database; every assumption is listed. If an ingredient can't be matched, nothing is invented: the card says so." |
| 4:30 | — | Close | "Next: images (needs the FLUX key), Person A's review of the pitches, more recipes per pitch." |

## 3. If something goes wrong (decide in 5 seconds)

| Problem | Do |
|---|---|
| Live generation takes > 2 min or errors | Say "gateway is slow, here is the same run recorded earlier", open `data/local/demo-backup/live_review.png` and `live_approved.png`, or open the two `.html` cards in the browser. |
| You want the full flow without the network | Sidebar → **Person C pipeline · offline mock** → Load → Choose any → Generate (instant, labelled **MOCK**; tell the audience). |
| App crashed | `Ctrl+C`, run the `streamlit` command again, reload the page (30 s). |
| Batch not found | Sidebar → type `data/local/proposals-review-draft.json` in the batch field → **Reload batch file**. |
| The review says **Blocked** | Good story: "hard problems cannot be dismissed". Click **Send back** with a comment ("bitte Mengen prüfen") or **Discard** and pick another pitch. |

## 4. Numbers you can state (all measured in our live runs)

- One live run, one pitch: about **3 minutes** end to end (generation ~55 s, review ~30 s, correction ~13 s, nutrition ~20 s per recipe).
- Live run 2: round 1 found **4 hard and 8 soft** findings; the automatic correction fixed **all hard ones** (12 findings fixed overall); round 2 had **0 hard**.
- Nutrition from the **real Swiss database (1,216 entries)**: 9 of 10 and 8 of 8 ingredients calculated, quality "mittel"; assumptions listed, nothing invented.
- Tests: **213** (editor, offline) + **40** (Person C). No network in any test.
- Archive: 5,000 of 81,798 recipes (a selection, not representative), read locally and never sent anywhere.

## 5. Questions you will get

- **Why can't the editor dismiss a hard issue?** A proven error (missing quantity, ingredient never used) must not reach print. The editor can send back with a comment or discard and choose another pitch.
- **Why no publication dates or repetition risk?** The export documents no publication date. Creation/import timestamps are not publication dates, and match counts do not show repetition. We show coverage and say so.
- **Is this real or mock?** Mock drafts are labelled MOCK on screen and on the card. The live engine's drafts are labelled AI-generated draft.
- **Where does data go?** The archive and the batch stay on this machine. In live mode only the pitch text and the recipe text go to the hackathon text gateway. No archive titles, no images.
- **Why are there no pictures?** Image generation needs the FLUX key; the card shows "kein Bild" instead of inventing one.
- **What is not finished?** Pitches are a team draft awaiting Person A's review; one unmatched ingredient leaves a recipe's nutrition "pending"; images.

## 6. Honest limits to say out loud (builds trust)

The trend scores are heuristics, the brand-fit text is our reading of the brand guide, the review loop can disagree with a human cook, and a live run varies from run to run.
