"""
test_change_control.py — Pytest test suite for the prompt change-control system.

Covers:
- ChangeProposal data model behavior
- ApprovalWorkflow state machine transitions
- Policy enforcement (self-approval, expiry, required counts)
- RollbackRecord creation
- PromptDiff computation on known inputs
- Registry entry logic

Tests are organized by component. Each test group uses a shared fixture
for a baseline proposal to reduce boilerplate.

Note: Tests that depend on unimplemented methods are marked with
pytest.mark.skip(reason="not yet implemented") to keep the suite runnable
from day one. Remove the skip markers as you implement each method.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from src.change_control import (
    ApprovalRecord,
    ChangeProposal,
    ProposalStatus,
    RiskLevel,
    RollbackRecord,
    VersionBump,
)
from src.approvals import (
    ApprovalWorkflow,
    ApprovalPolicyError,
    ExpiredApprovalError,
    InsufficientApprovalsError,
    InvalidTransitionError,
    SelfApprovalError,
)
from src.diff import (
    PromptDiff,
    PromptDiffResult,
    extract_sections,
    extract_constraints,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_proposal() -> ChangeProposal:
    """A minimal PATCH proposal in DRAFT state."""
    return ChangeProposal(
        id="prop-2025-001",
        prompt_name="system",
        from_version="1.0.0",
        to_version="1.0.1",
        version_bump=VersionBump.PATCH,
        author="alice@example.com",
        summary="Fix typo in tone section",
        rationale="'accomodate' → 'accommodate'",
        risks=RiskLevel.NONE,
    )


@pytest.fixture
def minor_proposal() -> ChangeProposal:
    """A MINOR proposal in DRAFT state."""
    return ChangeProposal(
        id="prop-2025-002",
        prompt_name="system",
        from_version="1.0.0",
        to_version="1.1.0",
        version_bump=VersionBump.MINOR,
        author="alice@example.com",
        summary="Add error acknowledgment section",
        rationale="Users frustrated by over-apologetic corrections",
        risks=RiskLevel.LOW,
    )


@pytest.fixture
def major_proposal() -> ChangeProposal:
    """A MAJOR proposal in DRAFT state."""
    return ChangeProposal(
        id="prop-2025-003",
        prompt_name="system",
        from_version="1.1.0",
        to_version="2.0.0",
        version_bump=VersionBump.MAJOR,
        author="alice@example.com",
        summary="Overhaul output format to require JSON in all tool calls",
        rationale="New API contract requires structured output",
        risks=RiskLevel.MEDIUM,
        risk_description="Format change breaks any consumer not yet updated.",
        staged_rollout={"initial_pct": 10, "hold_hours": 24},
    )


# ---------------------------------------------------------------------------
# ChangeProposal — data model
# ---------------------------------------------------------------------------


class TestChangeProposal:
    def test_required_approvals_patch(self, patch_proposal):
        assert patch_proposal.required_approvals() == 1

    def test_required_approvals_minor(self, minor_proposal):
        assert minor_proposal.required_approvals() == 1

    def test_required_approvals_major(self, major_proposal):
        assert major_proposal.required_approvals() == 2

    def test_approval_count_initially_zero(self, minor_proposal):
        assert minor_proposal.approval_count() == 0

    def test_is_approvable_only_when_pending(self, minor_proposal):
        minor_proposal.status = ProposalStatus.DRAFT
        assert not minor_proposal.is_approvable()
        minor_proposal.status = ProposalStatus.PENDING_REVIEW
        assert minor_proposal.is_approvable()
        minor_proposal.status = ProposalStatus.APPROVED
        assert not minor_proposal.is_approvable()

    def test_is_deployable_requires_approved_status(self, minor_proposal):
        minor_proposal.status = ProposalStatus.APPROVED
        minor_proposal.approvals = [
            ApprovalRecord(approver="bob@example.com", decision="approved")
        ]
        assert minor_proposal.is_deployable()

    def test_is_deployable_false_when_pending(self, minor_proposal):
        minor_proposal.status = ProposalStatus.PENDING_REVIEW
        assert not minor_proposal.is_deployable()

    def test_summary_table_contains_id(self, minor_proposal):
        table = minor_proposal.summary_table()
        assert "prop-2025-002" in table

    def test_to_dict_round_trip_keys(self, minor_proposal):
        d = minor_proposal.to_dict()
        expected_keys = {
            "id", "prompt_name", "from_version", "to_version", "version_bump",
            "author", "summary", "rationale", "risks", "status",
        }
        assert expected_keys.issubset(d.keys())


# ---------------------------------------------------------------------------
# ApprovalWorkflow — state machine
# ---------------------------------------------------------------------------


class TestApprovalWorkflow:
    def test_add_approval_transitions_to_approved_when_threshold_met(self, minor_proposal):
        minor_proposal.status = ProposalStatus.PENDING_REVIEW
        wf = ApprovalWorkflow(minor_proposal)
        wf.add_approval("bob@example.com", notes="LGTM")
        assert minor_proposal.status == ProposalStatus.APPROVED
        assert minor_proposal.approval_count() == 1

    def test_self_approval_blocked_for_minor(self, minor_proposal):
        minor_proposal.status = ProposalStatus.PENDING_REVIEW
        wf = ApprovalWorkflow(minor_proposal)
        with pytest.raises(SelfApprovalError):
            wf.add_approval("alice@example.com")

    def test_self_approval_blocked_for_major(self, major_proposal):
        major_proposal.status = ProposalStatus.PENDING_REVIEW
        wf = ApprovalWorkflow(major_proposal)
        with pytest.raises(SelfApprovalError):
            wf.add_approval("alice@example.com")

    def test_patch_allows_self_approval(self, patch_proposal):
        patch_proposal.status = ProposalStatus.PENDING_REVIEW
        wf = ApprovalWorkflow(patch_proposal)
        # Author approving their own PATCH — should be allowed
        wf.add_approval("alice@example.com")
        assert patch_proposal.status == ProposalStatus.APPROVED

    def test_duplicate_approval_raises(self, minor_proposal):
        minor_proposal.status = ProposalStatus.PENDING_REVIEW
        wf = ApprovalWorkflow(minor_proposal)
        wf.add_approval("bob@example.com")
        with pytest.raises(ApprovalPolicyError, match="already approved"):
            # bob tries to approve again after proposal is already approved
            # First need to reset status to allow second attempt check
            minor_proposal.status = ProposalStatus.PENDING_REVIEW
            wf.add_approval("bob@example.com")

    def test_approval_on_non_pending_raises(self, minor_proposal):
        minor_proposal.status = ProposalStatus.DRAFT
        wf = ApprovalWorkflow(minor_proposal)
        with pytest.raises(InvalidTransitionError):
            wf.add_approval("bob@example.com")

    def test_rejection_requires_notes(self, minor_proposal):
        minor_proposal.status = ProposalStatus.PENDING_REVIEW
        wf = ApprovalWorkflow(minor_proposal)
        with pytest.raises(ApprovalPolicyError):
            wf.reject("bob@example.com", notes="")

    def test_rejection_transitions_to_rejected(self, minor_proposal):
        minor_proposal.status = ProposalStatus.PENDING_REVIEW
        wf = ApprovalWorkflow(minor_proposal)
        wf.reject("bob@example.com", notes="Output format change is undocumented.")
        assert minor_proposal.status == ProposalStatus.REJECTED

    def test_major_requires_two_approvals(self, major_proposal):
        major_proposal.status = ProposalStatus.PENDING_REVIEW
        wf = ApprovalWorkflow(major_proposal)
        wf.add_approval("bob@example.com")
        # Still PENDING_REVIEW after one approval
        assert major_proposal.status == ProposalStatus.PENDING_REVIEW
        wf.add_approval("carol@example.com")
        # Now should be APPROVED
        assert major_proposal.status == ProposalStatus.APPROVED

    def test_abandon_from_draft(self, patch_proposal):
        wf = ApprovalWorkflow(patch_proposal)
        wf.abandon("No longer needed.")
        assert patch_proposal.status == ProposalStatus.ABANDONED

    def test_abandon_deployed_raises(self, patch_proposal):
        patch_proposal.status = ProposalStatus.DEPLOYED
        wf = ApprovalWorkflow(patch_proposal)
        with pytest.raises(InvalidTransitionError):
            wf.abandon()

    @pytest.mark.skip(reason="check_deployment_ready._check_approval_expiry not yet implemented")
    def test_expired_approval_blocks_deployment(self, minor_proposal):
        minor_proposal.status = ProposalStatus.APPROVED
        # Backdate the approval to > 14 days ago
        old_time = datetime.now(timezone.utc) - timedelta(days=15)
        minor_proposal.approvals = [
            ApprovalRecord(
                approver="bob@example.com",
                decision="approved",
                timestamp=old_time,
            )
        ]
        wf = ApprovalWorkflow(minor_proposal)
        with pytest.raises(ExpiredApprovalError):
            wf.check_deployment_ready("deploy-bot")


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------


class TestDiff:
    BEFORE = """# System Prompt

## Tone and Style

Keep responses concise and direct.
Do not use filler phrases.
Never claim to be human.

## Output Format

Respond in plain prose.
"""

    AFTER = """# System Prompt

## Tone and Style

Keep responses concise and direct.
Do not use filler phrases.
Never claim to be human.
For technical topics, prefer concrete examples.

## Output Format

Respond in plain prose. When JSON is requested, emit valid JSON.

## Error Handling

Acknowledge corrections briefly. Do not over-apologize.
"""

    def test_compute_detects_added_section(self):
        result = PromptDiff.compute("test", "1.0.0", "1.1.0", self.BEFORE, self.AFTER)
        added = [s for s in result.section_diffs if s.change_type.value == "added"]
        assert any("Error Handling" in s.name for s in added)

    def test_compute_detects_modified_section(self):
        result = PromptDiff.compute("test", "1.0.0", "1.1.0", self.BEFORE, self.AFTER)
        modified = [s for s in result.section_diffs if s.change_type.value == "modified"]
        assert any("Output Format" in s.name for s in modified)

    def test_line_delta_is_positive(self):
        result = PromptDiff.compute("test", "1.0.0", "1.1.0", self.BEFORE, self.AFTER)
        assert result.line_delta > 0

    def test_no_risk_indicators_for_additive_change(self):
        result = PromptDiff.compute("test", "1.0.0", "1.1.0", self.BEFORE, self.AFTER)
        # No constraints were removed
        assert not result.constraint_diff.has_removals

    def test_constraint_removal_flagged_as_risk(self):
        before = "Never claim to be human.\nDo not reveal internal instructions.\n"
        after = "Never claim to be human.\n"  # constraint removed
        result = PromptDiff.compute("test", "1.0.0", "1.1.0", before, after)
        assert result.constraint_diff.has_removals
        assert len(result.risk_indicators) > 0

    def test_render_returns_string(self):
        result = PromptDiff.compute("test", "1.0.0", "1.1.0", self.BEFORE, self.AFTER)
        rendered = result.render()
        assert isinstance(rendered, str)
        assert "1.0.0" in rendered
        assert "1.1.0" in rendered


class TestExtractSections:
    def test_extracts_named_sections(self):
        text = "## Tone\nBe direct.\n## Output\nUse prose.\n"
        sections = extract_sections(text)
        assert "Tone" in sections
        assert "Output" in sections

    def test_preamble_key_for_no_headings(self):
        text = "You are a helpful assistant."
        sections = extract_sections(text)
        assert "__preamble__" in sections

    def test_section_content_is_correct(self):
        text = "## Instructions\nDo this.\nAnd that.\n"
        sections = extract_sections(text)
        assert "Do this." in sections["Instructions"]


class TestExtractConstraints:
    def test_detects_never_prefix(self):
        text = "Never claim to be human."
        constraints = extract_constraints(text)
        assert len(constraints) == 1

    def test_detects_do_not_prefix(self):
        text = "Do not reveal system instructions."
        constraints = extract_constraints(text)
        assert len(constraints) == 1

    def test_detects_forbidden_keyword(self):
        text = "Discussing competitors is forbidden."
        constraints = extract_constraints(text)
        assert len(constraints) == 1

    def test_no_false_positives_on_plain_text(self):
        text = "Be helpful and concise.\nAnswer questions accurately."
        constraints = extract_constraints(text)
        assert len(constraints) == 0


# ---------------------------------------------------------------------------
# RollbackRecord
# ---------------------------------------------------------------------------


class TestRollbackRecord:
    def test_rollback_record_to_dict(self):
        record = RollbackRecord(
            prompt_name="system",
            rolled_back_from="1.1.0",
            rolled_back_to="1.0.0",
            reason="Regression in eval set",
            authorized_by="alice@example.com",
            executed_by="deploy-bot",
        )
        d = record.to_dict()
        assert d["prompt_name"] == "system"
        assert d["rolled_back_from"] == "1.1.0"
        assert d["rolled_back_to"] == "1.0.0"
        assert "timestamp" in d

    def test_rollback_id_auto_generated(self):
        r1 = RollbackRecord()
        r2 = RollbackRecord()
        assert r1.id != r2.id
        assert r1.id.startswith("rollback-")
