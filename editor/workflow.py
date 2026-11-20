"""Stepwise human-in-the-loop workflow. Stages: idle -> proposals -> review -> approved.

Rules (docs/decisions.md):
- The draft shown to the editor ALWAYS has a completed review. A new draft replaces the current one only after
  its own review succeeded (atomic swap). If revising or reviewing fails, the previous reviewed draft stays.
- HARD issues (code-verifiable) block approval and can NOT be dismissed. The editor can send back with a comment,
  or discard the recipes and choose another proposal (no dead end).
- SOFT issues never block; they stay visible and are carried onto the approved result as warnings.
- Every action is written to an audit log (JSONL). Cards are exported only after approval.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .agents import Agents
from .changes import diff_bundles
from .contract import check_bundle, check_proposals
from .render import render_cards
from .review_issues import review_all

AUTO_ROUNDS = 2      # automatic review/revise rounds after generation
EDITOR_ROUNDS = 2    # extra rounds the editor may request with a comment
MAX_RETRIES = 1
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "logs" / "editor_audit.jsonl"
DEFAULT_CARDS = ROOT / "output" / "cards"
STEP_LABELS = {"proposals": "Researching trends and building proposals", "recipes": "Generating two recipes",
               "review": "Reviewing the recipes", "revise": "Revising the recipes", "nutrition": "Calculating nutrition"}


class WorkflowError(ValueError):
    """User-facing error: the action is not allowed, or an agent failed."""


class EditorWorkflow:
    def __init__(self, agents: Agents | None = None, log_path: Path | None = None, cards_dir: Path | None = None):
        self.agents = agents or Agents()
        self.log_path = Path(log_path) if log_path else DEFAULT_LOG
        self.cards_dir = Path(cards_dir) if cards_dir else DEFAULT_CARDS
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.on_progress: Callable[[str], None] = lambda message: None   # the UI sets this to show live steps
        self.reset()

    # ---- state
    def reset(self):
        self.stage = "idle"
        self.proposals: list[dict] = []
        self.rejected: list[dict] = []
        self.shown_topics: set[str] = set()
        self.selected: dict | None = None
        self.notes = ""
        self.bundle: dict | None = None
        self.issues: list[dict] = []
        self.rounds: list[dict] = []
        self.editor_rounds_used = 0
        self.result: dict | None = None
        self.notices: list[str] = []          # non-fatal problems the UI should show
        self.trail: list[dict] = []

    def _log(self, event: str, **data):
        self.trail.append({"event": event, **data})
        record = {"t": datetime.now(timezone.utc).isoformat(), "event": event, **data}
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _call(self, label: str, fn: Callable, *args, check: Callable | None = None):
        """Run an agent call, validate its output, retry once, otherwise raise a clear WorkflowError."""
        last = None
        for attempt in range(MAX_RETRIES + 1):
            suffix = f" (retry {attempt})" if attempt else ""
            self.on_progress(f"{STEP_LABELS.get(label, label)}…{suffix}")
            try:
                out = fn(*args)
                return check(out) if check else out
            except Exception as exc:  # noqa: BLE001 - boundary to unknown agents
                last = exc
                self._log("agent_error", step=label, attempt=attempt + 1, error=str(exc))
        raise WorkflowError(f"{label} failed after {MAX_RETRIES + 1} attempts: {last}")

    def _need(self, stage: str):
        if self.stage != stage:
            raise WorkflowError(f"Not allowed in stage '{self.stage}' (needs '{stage}').")

    # ---- proposals
    def _load_proposals(self, exclude: set[str]):
        accepted, rejected = self._call("proposals", self.agents.propose, set(exclude), 5, check=check_proposals)
        self.proposals, self.rejected = accepted, rejected
        self.shown_topics |= {p["topic"] for p in accepted}
        self.stage = "proposals"
        self._log("proposals_ready", n=len(accepted), topics=[p["topic"] for p in accepted])

    def can_reject_all(self) -> bool:
        return self.stage == "proposals" and getattr(self.agents.propose, "supports_rerun", True) is not False

    def start(self):
        self.reset()
        self._load_proposals(set())

    def reject_all(self, note: str = ""):
        """None of the five fit: log the decision and note, then propose other topics."""
        self._need("proposals")
        if getattr(self.agents.propose, "supports_rerun", True) is False:
            raise WorkflowError("These pitches are a fixed batch from Person A: no replacement batch or rerun is available. "
                                "Choose one of them, or load a different batch.")
        self._log("editor_rejected_all", note=note, topics=sorted(self.shown_topics))
        self._load_proposals(set(self.shown_topics))

    # ---- review core (pure: computes, never mutates the shown state)
    def _review(self, bundle: dict, notes: str, previous: list[dict]):
        new = self._call("review", review_all, self.agents, bundle, notes)
        old = {i["key"]: i for i in previous}
        for issue in new:                                  # soft acknowledgements survive the next round
            prev = old.get(issue["key"])
            if prev and prev["status"] == "dismissed" and prev["kind"] == "soft":
                issue["status"], issue["dismiss_reason"] = "dismissed", prev["dismiss_reason"]
        new_keys = {i["key"] for i in new}
        fixed = [dict(i, status="fixed") for k, i in old.items() if i["status"] == "open" and k not in new_keys]
        return new, fixed

    def _commit(self, bundle: dict, issues: list[dict], fixed: list[dict]):
        changes = diff_bundles(self.bundle, bundle)               # what this revision actually changed (empty for the first draft)
        self.bundle, self.issues = bundle, issues
        self.rounds.append({"round": len(self.rounds) + 1, "issues": [dict(i) for i in issues], "fixed": fixed, "changes": changes})
        self._log("review", round=len(self.rounds), hard_open=len(self._open("hard")),
                  soft_open=len(self._open("soft")), fixed=len(fixed))

    def _revise_and_review(self, comment: str):
        """Atomic: revise -> review the NEW draft -> only then replace draft and issues together."""
        todo = [i for i in self.issues if i["status"] == "open"]
        try:
            candidate = self._call("revise", self.agents.revise, self.selected, self.notes, self.bundle, todo,
                                   comment, check=check_bundle)
            issues, fixed = self._review(candidate, self.notes, self.issues)
        except WorkflowError as exc:
            self._log("revision_discarded", reason=str(exc))
            raise
        self._log("revised", comment=comment, issues_sent=len(todo))
        self._commit(candidate, issues, fixed)

    # ---- generation + automatic loop
    def select(self, proposal_id: str, notes: str = ""):
        self._need("proposals")
        prop = next((p for p in self.proposals if p["id"] == proposal_id), None)
        if prop is None:
            raise WorkflowError(f"Unknown proposal: {proposal_id}")
        self._log("editor_selected", proposal=proposal_id, topic=prop["topic"], notes=notes)
        bundle = self._call("recipes", self.agents.generate, prop, notes, check=check_bundle)
        issues, fixed = self._review(bundle, notes, [])       # if this fails nothing is set; editor can retry
        self.selected, self.notes, self.rounds, self.editor_rounds_used, self.notices = prop, notes, [], 0, []
        self._log("recipes_generated", titles=[r["title"] for r in bundle["recipes"]])
        self._commit(bundle, issues, fixed)
        self.stage = "review"
        for _ in range(AUTO_ROUNDS - 1):
            if not self._open("hard"):
                break
            try:
                self._revise_and_review("")
            except WorkflowError as exc:                      # keep the last reviewed draft and tell the editor
                self.notices.append(f"Automatic revision failed, showing the last reviewed draft: {exc}")
                break

    # ---- editor decisions
    def _open(self, kind: str) -> list[dict]:
        return [i for i in self.issues if i["kind"] == kind and i["status"] == "open"]

    def can_approve(self) -> tuple[bool, str]:
        if self.stage != "review":
            return False, "Nothing to approve yet."
        blocking = self._open("hard")
        if blocking:
            return False, (f"{len(blocking)} hard issue(s) open. They cannot be dismissed: send the recipes back "
                           "with a comment, or discard them and choose another proposal.")
        return True, ""

    def editor_rounds_left(self) -> int:
        return EDITOR_ROUNDS - self.editor_rounds_used

    def send_back(self, comment: str):
        self._need("review")
        if not comment.strip():
            raise WorkflowError("A comment is required to send the recipes back.")
        if self.editor_rounds_left() <= 0:
            raise WorkflowError("The editor revision limit is reached: approve (if allowed) or discard the recipes.")
        self._log("editor_sent_back", comment=comment)
        self._revise_and_review(comment)
        self.editor_rounds_used += 1                           # only counted when the new draft was reviewed

    def acknowledge(self, issue_key: str, reason: str):
        """Mark an open SOFT issue as acknowledged (with reason). Hard issues cannot be dismissed."""
        self._need("review")
        issue = next((i for i in self.issues if i["key"] == issue_key), None)
        if issue is None or issue["status"] != "open":
            raise WorkflowError("This issue is not open.")
        if issue["kind"] == "hard":
            raise WorkflowError("Hard issues cannot be dismissed. Send the recipes back with a comment instead.")
        if not reason.strip():
            raise WorkflowError("A reason is required to acknowledge an issue.")
        issue["status"], issue["dismiss_reason"] = "dismissed", reason.strip()
        self._log("editor_acknowledged_soft", issue=issue["key"], reason=reason.strip())

    dismiss = acknowledge   # backwards-compatible name

    def discard(self, reason: str = ""):
        """Throw away the current recipes and go back to the proposals (the way out of a dead end)."""
        self._need("review")
        self._log("editor_discarded_recipes", reason=reason, topic=self.selected["topic"] if self.selected else None)
        self.selected, self.bundle, self.issues, self.rounds, self.notes = None, None, [], [], ""
        self.editor_rounds_used, self.notices = 0, []
        self.stage = "proposals"

    def approve(self):
        ok, why = self.can_approve()
        if not ok:
            raise WorkflowError(why)
        warnings = [i for i in self.issues if i["status"] in ("open", "dismissed")]    # soft only, by construction
        nutrition = [{"recipe_title": r["title"], "nutrition": self._call("nutrition", self.agents.nutrition, r)}
                     for r in self.bundle["recipes"]]
        try:
            files = render_cards(self.bundle["recipes"], [n["nutrition"] for n in nutrition], warnings,
                                 self.selected["topic"], self.cards_dir)
        except Exception as exc:  # noqa: BLE001
            self._log("render_error", error=str(exc))
            raise WorkflowError(f"Exporting the recipe cards failed: {exc}") from exc
        self.result = {"proposal": self.selected, "recipes": self.bundle, "nutrition": nutrition,
                       "approved_with_warnings": warnings, "cards": [str(f) for f in files]}
        self.stage = "approved"
        self._log("approved", cards=[str(f) for f in files],
                  warnings=[{"message": w["message"], "status": w["status"], "reason": w["dismiss_reason"]}
                            for w in warnings])
