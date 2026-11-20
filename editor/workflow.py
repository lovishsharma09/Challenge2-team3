"""Stepwise human-in-the-loop workflow. Stages: idle -> proposals -> review -> approved.

The editor decides between steps: select / reject_all / send_back / dismiss / approve.
Approval is blocked while a HARD issue is open. Every action is written to an audit log (JSONL).
Nutrition is requested per recipe on approval; HTML rendering is a separate step (not here).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .agents import Agents
from .contract import check_bundle, check_proposals
from .review_issues import review_all

AUTO_ROUNDS = 2      # automatic review/revise rounds after generation
EDITOR_ROUNDS = 2    # extra rounds the editor may request with a comment
MAX_RETRIES = 1
DEFAULT_LOG = Path(__file__).resolve().parent.parent / "logs" / "editor_audit.jsonl"


class WorkflowError(ValueError):
    """User-facing error: the action is not allowed, or an agent failed."""


class EditorWorkflow:
    def __init__(self, agents: Agents | None = None, log_path: Path | None = None):
        self.agents = agents or Agents()
        self.log_path = Path(log_path) if log_path else DEFAULT_LOG
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
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

    def start(self):
        self.reset()
        self._load_proposals(set())

    def reject_all(self, note: str = ""):
        """None of the five fit: log the decision and note, then propose other topics."""
        self._need("proposals")
        self._log("editor_rejected_all", note=note, topics=sorted(self.shown_topics))
        self._load_proposals(set(self.shown_topics))

    # ---- generation + review loop
    def select(self, proposal_id: str, notes: str = ""):
        self._need("proposals")
        prop = next((p for p in self.proposals if p["id"] == proposal_id), None)
        if prop is None:
            raise WorkflowError(f"Unknown proposal: {proposal_id}")
        self._log("editor_selected", proposal=proposal_id, topic=prop["topic"], notes=notes)
        bundle = self._call("recipes", self.agents.generate, prop, notes, check=check_bundle)
        self.selected, self.notes, self.bundle = prop, notes, bundle
        self._log("recipes_generated", titles=[r["title"] for r in bundle["recipes"]])
        self._review_round()
        for _ in range(AUTO_ROUNDS - 1):
            if not self._open("hard"):
                break
            self._revise_and_review("")
        self.stage = "review"

    def _review_round(self):
        new = self._call("review", review_all, self.agents, self.bundle, self.notes)
        old = {i["key"]: i for i in self.issues}
        for issue in new:                                  # keep dismissals across rounds
            prev = old.get(issue["key"])
            if prev and prev["status"] == "dismissed":
                issue["status"], issue["dismiss_reason"] = "dismissed", prev["dismiss_reason"]
        new_keys = {i["key"] for i in new}
        fixed = [i for k, i in old.items() if i["status"] == "open" and k not in new_keys]
        for i in fixed:
            i["status"] = "fixed"
        self.issues = new
        self.rounds.append({"round": len(self.rounds) + 1, "issues": [dict(i) for i in new],
                            "fixed": [dict(i) for i in fixed]})
        self._log("review", round=len(self.rounds), hard_open=len(self._open("hard")),
                  soft_open=len(self._open("soft")), fixed=len(fixed))

    def _revise_and_review(self, comment: str):
        todo = [i for i in self.issues if i["status"] == "open"]
        self.bundle = self._call("revise", self.agents.revise, self.selected, self.notes, self.bundle, todo,
                                 comment, check=check_bundle)
        self._log("revised", comment=comment, issues_sent=len(todo))
        self._review_round()

    # ---- editor decisions
    def _open(self, kind: str) -> list[dict]:
        return [i for i in self.issues if i["kind"] == kind and i["status"] == "open"]

    def can_approve(self) -> tuple[bool, str]:
        if self.stage != "review":
            return False, "Nothing to approve yet."
        blocking = self._open("hard")
        if blocking:
            return False, f"{len(blocking)} hard issue(s) open: send back with a comment or dismiss as false alarm."
        return True, ""

    def editor_rounds_left(self) -> int:
        return EDITOR_ROUNDS - self.editor_rounds_used

    def send_back(self, comment: str):
        self._need("review")
        if not comment.strip():
            raise WorkflowError("A comment is required to send the recipes back.")
        if self.editor_rounds_left() <= 0:
            raise WorkflowError("The editor revision limit is reached: approve, dismiss issues, or reject.")
        self.editor_rounds_used += 1
        self._log("editor_sent_back", comment=comment)
        self._revise_and_review(comment)

    def dismiss(self, issue_key: str, reason: str):
        self._need("review")
        issue = next((i for i in self.issues if i["key"] == issue_key), None)
        if issue is None or issue["status"] != "open":
            raise WorkflowError("This issue is not open.")
        if not reason.strip():
            raise WorkflowError("A reason is required to dismiss an issue.")
        issue["status"], issue["dismiss_reason"] = "dismissed", reason.strip()
        self._log("editor_dismissed", issue=issue["key"], kind=issue["kind"], reason=reason.strip())

    def approve(self):
        ok, why = self.can_approve()
        if not ok:
            raise WorkflowError(why)
        warnings = [i for i in self.issues if i["status"] in ("open", "dismissed")]
        nutrition = [{"recipe_title": r["title"], "nutrition": self._call("nutrition", self.agents.nutrition, r)}
                     for r in self.bundle["recipes"]]
        self.result = {"proposal": self.selected, "recipes": self.bundle, "nutrition": nutrition,
                       "approved_with_warnings": warnings}
        self.stage = "approved"
        self._log("approved", warnings=[{"message": w["message"], "status": w["status"],
                                         "reason": w["dismiss_reason"]} for w in warnings])
