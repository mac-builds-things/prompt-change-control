"""
approvals.py — Approval workflow state machine.

Encapsulates the rules for transitioning a ChangeProposal through its
lifecycle, including policy enforcement, expiry checks, and notification hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from .change_control import (
    ApprovalRecord,
    ChangeProposal,
    ProposalStatus,
    VersionBump,
)


# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------

APPROVAL_EXPIRY_DAYS = 14
"""Approvals older than this many days must be refreshed before deployment."""

MINOR_EVAL_MAX_REGRESSION = 0.02
"""Max acceptable pass-rate regression for a MINOR bump (2%)."""

MAJOR_EVAL_MAX_REGRESSION = 0.005
"""Max acceptable pass-rate regression for a MAJOR bump (0.5%)."""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ApprovalPolicyError(Exception):
    """Raised when an approval action violates policy."""


class ExpiredApprovalError(ApprovalPolicyError):
    """Raised when a deployment is attempted with expired approvals."""


class InsufficientApprovalsError(ApprovalPolicyError):
    """Raised when deployment is attempted before enough approvals are collected."""


class SelfApprovalError(ApprovalPolicyError):
    """Raised when a proposer attempts to self-approve a MINOR or MAJOR change."""


class InvalidTransitionError(ApprovalPolicyError):
    """Raised when an operation is attempted in an incompatible proposal state."""


# ---------------------------------------------------------------------------
# Notification hook type
# ---------------------------------------------------------------------------

NotifyFn = Callable[[str, ChangeProposal], None]
"""
Type alias for notification callbacks.

Receives an event name ('approved', 'rejected', 'deployed', 'rollback')
and the proposal, and is responsible for dispatching notifications
(Slack, email, webhook, etc.).

In production, wire this to your team's notification system.
"""


# ---------------------------------------------------------------------------
# Approval workflow engine
# ---------------------------------------------------------------------------


@dataclass
class ApprovalWorkflow:
    """
    Enforces the approval policy for a single ChangeProposal.

    Instantiate one per proposal to validate transitions and record approvals.
    Callers are responsible for persisting the updated proposal after each
    mutating operation.
    """

    proposal: ChangeProposal
    notify: NotifyFn | None = None

    def _notify(self, event: str) -> None:
        if self.notify:
            try:
                self.notify(event, self.proposal)
            except Exception:
                pass  # Notifications must never block workflow operations

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def submit(self) -> None:
        """
        Transition a DRAFT proposal to PENDING_REVIEW.

        Validates:
        - All required fields are populated
        - summary is ≤ 140 chars
        - MAJOR bumps include staged_rollout config
        - MINOR/MAJOR bumps include at least one eval_result

        TODO: implement field validation
        """
        if self.proposal.status != ProposalStatus.DRAFT:
            raise InvalidTransitionError(
                f"Cannot submit: proposal is in state {self.proposal.status.value!r}. "
                "Only DRAFT proposals can be submitted."
            )
        self._validate_required_fields()
        self.proposal.status = ProposalStatus.PENDING_REVIEW
        self.proposal.updated_at = datetime.now(timezone.utc)
        self._notify("submitted")

    def _validate_required_fields(self) -> None:
        """
        Check that all policy-required fields are populated.

        TODO: implement — check summary length, eval_results for MINOR/MAJOR,
        staged_rollout for MAJOR, risk_description for medium/high risks.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Approve
    # ------------------------------------------------------------------

    def add_approval(self, approver: str, notes: str = "") -> ApprovalRecord:
        """
        Record an approval on the proposal.

        Policy enforcement:
        - Proposal must be PENDING_REVIEW
        - For MINOR/MAJOR: approver != author
        - Approver may not approve twice

        Transitions to APPROVED if required_approvals threshold is met.
        """
        if not self.proposal.is_approvable():
            raise InvalidTransitionError(
                f"Cannot approve: proposal is in state {self.proposal.status.value!r}."
            )

        # Self-approval guard for MINOR and MAJOR
        if (
            self.proposal.version_bump in (VersionBump.MINOR, VersionBump.MAJOR)
            and approver == self.proposal.author
        ):
            raise SelfApprovalError(
                f"{approver!r} cannot approve their own "
                f"{self.proposal.version_bump.value} change."
            )

        # Duplicate approval guard
        existing_approvers = {a.approver for a in self.proposal.approvals if a.decision == "approved"}
        if approver in existing_approvers:
            raise ApprovalPolicyError(
                f"{approver!r} has already approved this proposal."
            )

        record = ApprovalRecord(
            approver=approver,
            decision="approved",
            notes=notes,
        )
        self.proposal.approvals.append(record)
        self.proposal.updated_at = datetime.now(timezone.utc)

        # Check if threshold reached
        if self.proposal.approval_count() >= self.proposal.required_approvals():
            self.proposal.status = ProposalStatus.APPROVED
            self._notify("approved")
        else:
            remaining = self.proposal.required_approvals() - self.proposal.approval_count()
            # Notify that an approval was recorded but more are needed
            self._notify("approval_recorded")

        return record

    # ------------------------------------------------------------------
    # Reject
    # ------------------------------------------------------------------

    def reject(self, approver: str, notes: str) -> None:
        """
        Reject a proposal, providing mandatory notes.

        Notes are required for rejections — reviewers must explain their
        reasoning so the proposer can address the concern.
        """
        if not notes.strip():
            raise ApprovalPolicyError(
                "Rejection notes are required. Explain the reason so the proposer can address it."
            )
        if not self.proposal.is_approvable():
            raise InvalidTransitionError(
                f"Cannot reject: proposal is in state {self.proposal.status.value!r}."
            )

        record = ApprovalRecord(
            approver=approver,
            decision="rejected",
            notes=notes,
        )
        self.proposal.approvals.append(record)
        self.proposal.status = ProposalStatus.REJECTED
        self.proposal.updated_at = datetime.now(timezone.utc)
        self._notify("rejected")

    # ------------------------------------------------------------------
    # Deployment readiness checks
    # ------------------------------------------------------------------

    def check_deployment_ready(self, deployer: str) -> None:
        """
        Assert that the proposal is ready to deploy.

        Raises an appropriate exception if any policy check fails.
        Checks:
        1. Status == APPROVED
        2. Required approvals collected
        3. Approvals have not expired
        4. For MAJOR: deployer != final approver
        """
        if self.proposal.status != ProposalStatus.APPROVED:
            raise InsufficientApprovalsError(
                f"Proposal {self.proposal.id!r} is not approved "
                f"(current status: {self.proposal.status.value!r})."
            )

        if self.proposal.approval_count() < self.proposal.required_approvals():
            raise InsufficientApprovalsError(
                f"Proposal requires {self.proposal.required_approvals()} approval(s); "
                f"only {self.proposal.approval_count()} collected."
            )

        self._check_approval_expiry()

        if self.proposal.version_bump == VersionBump.MAJOR:
            self._check_major_deployer_constraint(deployer)

    def _check_approval_expiry(self) -> None:
        """
        Verify that no approval has exceeded the APPROVAL_EXPIRY_DAYS window.

        TODO: implement — find the most recent approval timestamp;
        raise ExpiredApprovalError if now - last_approval > APPROVAL_EXPIRY_DAYS.
        """
        raise NotImplementedError

    def _check_major_deployer_constraint(self, deployer: str) -> None:
        """
        For MAJOR bumps: deployer must not be the final approver.

        TODO: implement — find the last approver in self.proposal.approvals;
        raise ApprovalPolicyError if deployer matches.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Abandon
    # ------------------------------------------------------------------

    def abandon(self, reason: str = "") -> None:
        """
        Mark a proposal as ABANDONED.

        Valid from DRAFT, PENDING_REVIEW, or APPROVED states.
        A deployed proposal cannot be abandoned (use rollback instead).
        """
        if self.proposal.status == ProposalStatus.DEPLOYED:
            raise InvalidTransitionError(
                "Cannot abandon a deployed proposal. Use rollback to revert the deployment."
            )
        self.proposal.status = ProposalStatus.ABANDONED
        self.proposal.updated_at = datetime.now(timezone.utc)
        self._notify("abandoned")


# ---------------------------------------------------------------------------
# Approval requirement helper
# ---------------------------------------------------------------------------


def approval_requirements(proposal: ChangeProposal) -> dict[str, object]:
    """
    Describe the approval requirements for a proposal as a human-readable dict.

    Useful for display in proposal summaries and CLI output.
    """
    bump = proposal.version_bump
    return {
        "version_bump": bump.value,
        "required_approvals": proposal.required_approvals(),
        "self_approval_allowed": bump == VersionBump.PATCH,
        "eval_required": bump in (VersionBump.MINOR, VersionBump.MAJOR),
        "staged_rollout_required": bump == VersionBump.MAJOR,
        "approval_expiry_days": APPROVAL_EXPIRY_DAYS,
        "deployment_separation_required": bump == VersionBump.MAJOR,
        "max_regression": (
            MAJOR_EVAL_MAX_REGRESSION
            if bump == VersionBump.MAJOR
            else MINOR_EVAL_MAX_REGRESSION
            if bump == VersionBump.MINOR
            else None
        ),
    }
