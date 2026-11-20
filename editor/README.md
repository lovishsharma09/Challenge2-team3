# Editor desk (Person B)

The human-in-the-loop part of the workflow: the editor compares five pitches, chooses one, reviews two drafts, and approves them.
Only then are two A4 HTML recipe cards exported. The package is standard-library Python plus Streamlit and does not import the
legacy `src/challenge2` pipeline.

## Run

```
pip install -r requirements.txt
streamlit run editor/app.py            # from the repo root
python -m unittest discover -s editor/tests -t .
python -m editor.batch path/to/batch.json    # validate a proposal batch before sending it
```

## What it expects (all local, nothing is uploaded)

Configure through environment variables or an untracked `.env` in the repo root:

| Variable | Purpose |
|---|---|
| `EDITOR_PROPOSALS_JSON` | Saved proposal batch (Person A's `proposals` / `rejected_topics` format). Can also be typed in the sidebar. |
| `EDITOR_ARCHIVE_ZIP` | The 5,000-recipe export ZIP, used only by the offline fallback ranking. |
| `EDITOR_TRENDS_DIR` | Defaults to `data/trends` (Google Trends CSVs + Wikimedia fallback snapshot). |
| `TESSERACTED_BASE_URL`, `TESSERACTED_API_KEY`, `EDITOR_LLM_MODEL` | Optional: real LLM review/revision (sidebar checkbox, off by default). |

**Keep local, never commit:** `.env`, the recipe export, and any proposal batch. Put batches in `data/local/` (git-ignored).

## Recipe engines (sidebar)

| Engine | What it does |
|---|---|
| Built-in mock samples (default) | Fixed lentil-soup samples with a planted flaw: rehearses the review and export flow. Flagged MOCK. |
| Person C pipeline · offline mock | Person C's own fixtures and synthetic nutrition data, no network. Flagged MOCK; nutrition says "TESTDATEN". |
| Person C pipeline · live text gateway | Real recipes, review, revision and nutrition (real Swiss database) through the hackathon text gateway. Sends the pitch text and the recipe text, never archive titles. No images. |

Live mode needs `TESSERACTED_BASE_URL`, `TESSERACTED_API_KEY` and `EDITOR_LLM_MODEL` in the untracked `.env`
(`tesseracted-labs-gmbh/zai-org/GLM-5.3-Flash` is the fastest tested model). A whole live run takes about 3 minutes.
Our workflow stays the controller: Person C only supplies generate / review / revise / nutrition (`editor/c_agents.py`).

## Flow and rules

1. **Proposals.** Either a saved batch (`editor/batch.py`: strict validation, shown in the supplied rank order, never recalculated;
   a batch with a `source.kind = "team_draft"` block is labelled as a draft) or the explicit, labelled offline candidate ranking.
2. **Two drafts** from the chosen pitch (stubs are labelled MOCK until a real generator is wired in: `editor/agents.py`).
3. **Review loop.** Code-verifiable (hard) issues block approval and cannot be dismissed; judgment (soft) issues never block.
   A new draft replaces the shown one only after its own review succeeded. Each revision records a concrete before/after diff.
4. **Approval** exports two cards in the supplied template (`editor/render.py`); nothing is exported earlier.

## Where to plug in the real services

`editor/agents.py` defines the agent signatures (`propose`, `generate`, `review`, `revise`, `nutrition`); `editor/contract.py` documents
the data shapes. Replace a stub by passing your function to `Agents(...)`. Person C's generation, nutrition and image output goes here.

## Not covered yet

Real recipe generation, nutrition per serving and images (nutrition shows "pending", never 0); publication dates and repetition risk
are intentionally not inferred from the archive export.
