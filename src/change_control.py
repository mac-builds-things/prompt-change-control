"""
change_control.py — Core prompt change-control system.

Provides the primary data model and orchestration layer for managing
versioned prompts, proposals, approvals, and deployments.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VersionBump(str, Enum):
    """Semantic version bump type, with prompt-specific semantics."""

    PATCH = "patch"
    """Typographic / formatting fix; no behavioral change expected."""

    MINOR = "minor"
    """Additive or clarifying change; backward-compatible behavior."""

    MAJOR = "major"
    """Breaking change: constraint removal, persona shift, format change."""


class ProposalStatus(str, Enum):
    """Lifecycle states for a change proposal."""

    DRAFT = "draft"
    """Proposal is being authored; not yet submitted for review."""

    PENDING_REVIEW = "pending_review"
    """Submitted; awaiting required approvals."""

    APPROVED = "approved"
    """All required approvals collected; eligible for deployment."""

    DEPLOYED = "deployed"
    """Active in production."""

    REJECTED = "rejected"
    """Declined by reviewer(s); cannot be deployed."""

    ABANDONED = "abandoned"
    """Withdrawn by proposer or expired without deployment."""


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# Core data classes
# ---------------------------------------------------------------------------


@dataclass
class PromptVersion:
    """
    An immutable snapshot of a prompt at a specific semantic version.

    Once a PromptVersion is deployed, its content must not change.
    Create a new PromptVersion with an incremented version string instead.
    """

    name: str
    """Prompt identifier, e.g. 'system' or 'tool-search'."""

    version: str
    """Semantic version string, e.g. '1.2.0'."""

    content: str
    """Full text of the prompt."""

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    """When this version was authored."""

    deployed_at: datetime | None = None
    """When this version was promoted to active; None if never deployed."""

    deprecated_at: datetime | None = None
    """When this version was superseded; None if still active or never deployed."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Arbitrary metadata: author, ticket references, eval result URLs, etc."""

    @property
    def file_stem(self) -> str:
        """Expected filename stem: '{name}-v{version}'."""
        return f"{self.name}-v{self.version}"

    @property
    def is_deployed(self) -> bool:
        return self.deployed_at is not None

    def summary(self) -> str:
        status = "deployed" if self.is_deployed else "draft"
        return f"[{self.name} v{self.version}] ({status}) — {len(self.content)} chars"

    @classmethod
    def from_file(cls, path: Path) -> "PromptVersion":
        """
        Load a PromptVersion from a versioned prompt file.

        Expects the file stem to match the pattern '{name}-v{version}'.

        TODO: implement
        """
        raise NotImplementedError


@dataclass
class ApprovalRecord:
    """
    A single approval (or rejection) on a change proposal.
    """

    approver: str
    """Approver identity: email or handle."""

    decision: str
    """'approved' or 'rejected'."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str = ""
    """Freeform review notes; required for rejections."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "approver": self.approver,
            "decision": self.decision,
            "timestamp": self.timestamp.isoformat(),
            "notes": self.notes,
        }


@dataclass
class EvalResult:
    """
    Snapshot of an evaluation run attached to a change proposal.
    """

    eval_suite: str
    """Name of the evaluation suite run."""

    pass_rate: float
    """Pass rate as a fraction (0.0–1.0)."""

    baseline_pass_rate: float
    """Pass rate of the version being replaced, for comparison."""

    run_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    run_by: str = ""
    report_url: str = ""
    notes: str = ""

    @property
    def delta(self) -> float:
        """Signed pass-rate change relative to baseline."""
        return self.pass_rate - self.baseline_pass_rate

    @property
    def passed_policy(self, bump: VersionBump = VersionBump.MINOR) -> bool:
        """
        Check whether this eval result satisfies policy thresholds.

        Policy:
          MINOR: delta >= -0.02 (no more than 2% regression)
          MAJOR: delta >= -0.005 (no more than 0.5% regression)

        TODO: wire bump type into evaluation
        """
        raise NotImplementedError


@dataclass
class ChangeProposal:
    """
    A formal proposal to change a prompt from one version to the next.

    A ChangeProposal is the central unit of the change-control workflow.
    It carries the intent (rationale), the risk assessment, the approval
    records, and the final disposition.
    """

    id: str
    """Unique proposal ID, format: prop-YYYY-NNN."""

    prompt_name: str
    """Name of the prompt being changed."""

    from_version: str
    """Version currently active in the registry."""

    to_version: str
    """Proposed new version."""

    version_bump: VersionBump
    """Claimed bump type. Reviewers may escalate this."""

    author: str
    """Proposer identity."""

    summary: str
    """≤140 char change summary."""

    rationale: str
    """Why this change is needed."""

    risks: RiskLevel
    risk_description: str = ""

    status: ProposalStatus = ProposalStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    approvals: list[ApprovalRecord] = field(default_factory=list)
    eval_results: list[EvalResult] = field(default_factory=list)

    related_issues: list[str] = field(default_factory=list)
    staged_rollout: dict[str, Any] | None = None
    """Staged rollout config (required for MAJOR bumps)."""

    def required_approvals(self) -> int:
        """Return the minimum number of approvals required by policy."""
        match self.version_bump:
            case VersionBump.PATCH:
                return 1  # self-approval
            case VersionBump.MINOR:
                return 1
            case VersionBump.MAJOR:
                return 2

    def approval_count(self) -> int:
        return sum(1 for a in self.approvals if a.decision == "approved")

    def is_approvable(self) -> bool:
        return self.status == ProposalStatus.PENDING_REVIEW

    def is_deployable(self) -> bool:
        return (
            self.status == ProposalStatus.APPROVED
            and self.approval_count() >= self.required_approvals()
        )

    def summary_table(self) -> str:
        """Render a single-line summary for CLI display."""
        approvals_display = f"{self.approval_count()}/{self.required_approvals()}"
        return (
            f"{self.id:20} | {self.prompt_name:20} | "
            f"{self.from_version} → {self.to_version} | "
            f"{self.version_bump.value:7} | {self.status.value:15} | "
            f"approvals: {approvals_display} | {self.summary[:60]}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for YAML roundtrip."""
        return {
            "id": self.id,
            "prompt_name": self.prompt_name,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "version_bump": self.version_bump.value,
            "author": self.author,
            "summary": self.summary,
            "rationale": self.rationale,
            "risks": self.risks.value,
            "risk_description": self.risk_description,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "approvals": [a.to_dict() for a in self.approvals],
            "related_issues": self.related_issues,
            "staged_rollout": self.staged_rollout,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChangeProposal":
        """Deserialize from a YAML-parsed dict.

        TODO: implement
        """
        raise NotImplementedError

    @classmethod
    def from_yaml(cls, path: Path) -> "ChangeProposal":
        """Load a proposal from a .proposal.yaml file.

        TODO: implement using PyYAML
        """
        raise NotImplementedError


@dataclass
class RollbackRecord:
    """
    Audit record for a rollback operation.

    Rollbacks are forward-changes that restore a prior version.
    This record preserves the audit trail — the history is never rewritten.
    """

    id: str = field(default_factory=lambda: f"rollback-{uuid.uuid4().hex[:8]}")
    prompt_name: str = ""
    rolled_back_from: str = ""
    """Version that was active before the rollback."""

    rolled_back_to: str = ""
    """Version that became active after the rollback."""

    reason: str = ""
    authorized_by: str = ""
    executed_by: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    related_proposal_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt_name": self.prompt_name,
            "rolled_back_from": self.rolled_back_from,
            "rolled_back_to": self.rolled_back_to,
            "reason": self.reason,
            "authorized_by": self.authorized_by,
            "executed_by": self.executed_by,
            "timestamp": self.timestamp.isoformat(),
            "related_proposal_id": self.related_proposal_id,
        }


# ---------------------------------------------------------------------------
# Registry entry
# ---------------------------------------------------------------------------


@dataclass
class RegistryEntry:
    """
    Metadata for a single named prompt in the registry.

    The registry is the source of truth for which version of each prompt
    is currently active.
    """

    name: str
    active_version: str
    owner: str
    description: str
    versions: list[str] = field(default_factory=list)
    """All known version strings, in order."""

    rollback_history: list[RollbackRecord] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def latest_version(self) -> str | None:
        return self.versions[-1] if self.versions else None


# ---------------------------------------------------------------------------
# Change control system
# ---------------------------------------------------------------------------


class ChangeControlSystem:
    """
    Orchestrates the full prompt change-control lifecycle:
    proposals → approvals → deployment → rollback.

    In production, this would be backed by a durable store (e.g. a database
    or a git-tracked YAML file). This implementation uses in-memory state
    with YAML serialization hooks for the file-backed workflow.
    """

    def __init__(
        self,
        registry: dict[str, RegistryEntry],
        versions_dir: Path,
    ) -> None:
        self.registry = registry
        self.versions_dir = versions_dir
        self._proposals: dict[str, ChangeProposal] = {}

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_registry(cls, registry_path: str | Path) -> "ChangeControlSystem":
        """
        Bootstrap a ChangeControlSystem from a registry.yaml file.

        Loads all registered prompts and discovers proposal files
        alongside version files in the versions directory.

        TODO: implement YAML loading
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Proposal management
    # ------------------------------------------------------------------

    def submit_proposal(self, proposal: ChangeProposal) -> ChangeProposal:
        """
        Validate and register a change proposal.

        Validation checks:
        - prompt_name exists in registry
        - from_version matches the currently-active version
        - to_version file exists on disk
        - Required fields are populated
        - version_bump classification is plausible (warns on MAJOR-looking diffs
          submitted as MINOR)

        Transitions proposal status: DRAFT → PENDING_REVIEW

        TODO: implement
        """
        raise NotImplementedError

    def pending_proposals(self) -> list[ChangeProposal]:
        """Return all proposals in PENDING_REVIEW status."""
        return [
            p for p in self._proposals.values()
            if p.status == ProposalStatus.PENDING_REVIEW
        ]

    def get_proposal(self, proposal_id: str) -> ChangeProposal:
        """Retrieve a proposal by ID; raises KeyError if not found."""
        if proposal_id not in self._proposals:
            raise KeyError(f"No proposal found with id={proposal_id!r}")
        return self._proposals[proposal_id]

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    def approve(
        self,
        proposal_id: str,
        approver: str,
        notes: str = "",
    ) -> ChangeProposal:
        """
        Record an approval on a proposal.

        Policy enforcement:
        - Proposal must be in PENDING_REVIEW
        - For MINOR/MAJOR: approver must not be the proposal author
        - Deduplicates: same approver cannot approve twice
        - Transitions to APPROVED when required_approvals threshold is met

        TODO: implement policy enforcement
        TODO: persist approval record to .proposal.yaml
        """
        raise NotImplementedError

    def reject(
        self,
        proposal_id: str,
        approver: str,
        notes: str,
    ) -> ChangeProposal:
        """
        Reject a proposal, providing mandatory notes.

        Transitions proposal status: PENDING_REVIEW → REJECTED

        TODO: implement
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Deployment
    # ------------------------------------------------------------------

    def deploy(
        self,
        proposal_id: str,
        deployed_by: str,
    ) -> ChangeProposal:
        """
        Deploy an approved proposal: updates the registry's active_version.

        Policy enforcement:
        - Proposal must be in APPROVED status
        - For MAJOR bumps: deployer must differ from final approver
        - Approval expiry: last approval must be < 14 days old

        Side effects:
        - Updates registry.yaml: sets active_version for the affected prompt
        - Marks the previous PromptVersion as deprecated
        - Sets PromptVersion.deployed_at on the new version
        - Appends a deployment event to the audit log

        TODO: implement
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(
        self,
        prompt_name: str,
        to_version: str,
        reason: str,
        authorized_by: str,
        executed_by: str | None = None,
    ) -> RollbackRecord:
        """
        Roll back a prompt to a prior version.

        Creates a RollbackRecord, updates active_version in the registry,
        and persists the rollback to the audit log.

        Rollbacks do not modify or delete any proposal or version file.
        The audit trail is append-only.

        TODO: implement
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def audit_log(self, prompt_name: str | None = None) -> list[dict[str, Any]]:
        """
        Return the audit log for a prompt (or all prompts if name is None).

        Each entry contains: event_type, timestamp, actor, version_from,
        version_to, and any relevant metadata.

        TODO: implement
        """
        raise NotImplementedError
