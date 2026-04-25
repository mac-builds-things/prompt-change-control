# Prompt Change Control Policy

**Version:** 1.0.0  
**Effective:** 2025-01-01  
**Owner:** Platform / AI Systems team  

---

## Purpose

This document defines the governance rules for managing changes to production prompt artifacts. It applies to any prompt used in a deployed AI system: system prompts, few-shot examples, tool descriptions, evaluation rubrics, and structured instruction blocks.

The core principle: **a prompt in production is a production artifact**. It carries the same change-management obligations as a database schema, an API contract, or a feature flag. Silent mutation is prohibited.

---

## Scope

This policy applies to:
- All prompts registered in `prompts/registry.yaml`
- Any prompt file under `prompts/versions/`
- Prompt fragments embedded in application configs that affect model behavior

It does not apply to:
- Ephemeral, user-supplied, or per-session dynamic content
- Evaluation harness prompts used only in offline test runs (though those are encouraged to follow the same process voluntarily)
- Prompts used exclusively in local development with no production pathway

---

## Versioning Scheme

All prompts use **semantic versioning**: `MAJOR.MINOR.PATCH`.

### PATCH bump

Criteria:
- Typographic corrections with no semantic change
- Punctuation or formatting normalization
- Reordering sections without changing content

Approval requirement: **self-approval** (proposer = approver, recorded for audit)  
Evaluation requirement: none  
Rollout: immediate

### MINOR bump

Criteria:
- Additive instructions (new capabilities, new guidelines)
- Clarifications that make existing behavior more explicit
- Tone adjustments that don't alter capability constraints
- Adding or reordering examples in a few-shot block

Approval requirement: **one peer review** from a designated prompt reviewer  
Evaluation requirement: regression check on the standard eval set (pass rate must not drop >2%)  
Rollout: immediate after approval; staged rollout recommended for high-traffic prompts

### MAJOR bump

Criteria:
- Removal or relaxation of a constraint or prohibition
- Persona or identity changes
- Output format changes that break downstream consumers
- Changes to tool-use instructions or function-calling behavior
- Any change to a safety-relevant prompt (refusal instructions, harm avoidance, content policy)

Approval requirement: **two approvers**, at least one of whom must be a designated prompt owner for the affected system  
Evaluation requirement: full eval suite run; pass rate must not drop >0.5%; safety evals must show no regression  
Rollout: mandatory staged rollout (10% → 50% → 100% with 24-hour hold periods)  
Notification: async notification to #ai-systems-changes (or equivalent) on deploy

---

## Proposal Requirements

Every change proposal (`*.proposal.yaml`) must include:

| Field | Required | Notes |
|-------|----------|-------|
| `id` | Yes | Format: `prop-YYYY-NNN` (e.g. `prop-2025-001`) |
| `prompt_name` | Yes | Must match a key in `registry.yaml` |
| `from_version` | Yes | The currently-active version being replaced |
| `to_version` | Yes | The proposed new version |
| `version_bump` | Yes | `patch`, `minor`, or `major` |
| `author` | Yes | Email or handle of proposer |
| `summary` | Yes | ≤ 140 characters: what changed |
| `rationale` | Yes | Why: what problem does this solve or what capability does it add? |
| `risks` | Yes | What could go wrong? `none`, `low`, `medium`, or `high` with explanation |
| `eval_results` | Conditional | Required for MINOR and MAJOR bumps |
| `related_issues` | No | Issue/ticket references |
| `staged_rollout` | Conditional | Required for MAJOR bumps |

Proposals with missing required fields will be rejected at submission time.

---

## Diff Review Standards

Reviewers are expected to evaluate:

### 1. Behavioral intent

Does the stated rationale match the actual diff? A proposal claiming "minor clarification" that removes a constraint should be escalated to a MAJOR bump.

### 2. Constraint audit

For every instruction that was **removed or weakened**, the reviewer must explicitly acknowledge it in their approval notes. The burden is on the reviewer to explain why removing a constraint is safe.

### 3. Downstream impact

Does any change affect the output format, tool invocation behavior, or structured data schema? If so, ensure downstream consumers have been notified or that the change is backward-compatible.

### 4. Regression risk

Check the eval results. For MINOR bumps, look at:
- Overall pass rate delta
- Any category-level regressions even if aggregate passes
- Edge cases specific to the changed instructions

For MAJOR bumps, additionally check:
- Safety evaluation results
- Adversarial probing results (if available)
- Refusal rate on borderline inputs

### 5. Version bump classification

Independently assess whether the proposed version bump type is correct. Downgrading a MAJOR to MINOR to avoid review overhead is a policy violation.

---

## Approval Process

### Who can approve

**Patch approvals:** The proposer themselves. Must be logged with a timestamp and the approver's identity.

**Minor approvals:** Any member of the designated Prompt Reviewer group. The proposer cannot approve their own MINOR change.

**Major approvals:** Two approvers required. Both must be from the Prompt Reviewer group. At least one must be a designated owner of the affected system. The proposer cannot be one of the two approvers.

### How to record approval

Approvals are appended to the proposal YAML under the `approvals` key:

```yaml
approvals:
  - approver: alice@example.com
    timestamp: "2025-03-15T14:22:00Z"
    notes: "Eval passed. No regression on structured output test suite."
  - approver: bob@example.com
    timestamp: "2025-03-15T16:05:00Z"
    notes: "Reviewed diff. Constraint removal is intentional and safe given new downstream handling."
```

### Approval expiry

Approvals expire **14 days** after the last approval timestamp. If a proposal is not deployed within 14 days of receiving all required approvals, it must be re-reviewed before deployment. This prevents stale approvals from authorizing deployment after the context has changed.

---

## Deployment Rules

1. **Only APPROVED proposals may be deployed.** A proposal in DRAFT or PENDING_REVIEW state cannot be deployed.

2. **The deployer must be distinct from the final approver** for MAJOR bumps. For PATCH and MINOR bumps, the proposer may deploy.

3. **Deployment is atomic**: the registry's `active_version` for the affected prompt is updated as a single write. Partial deployments (where some instances run the new version and others run the old without intent) are prohibited.

4. **Post-deploy monitoring window**: For MINOR bumps, monitor key metrics for 1 hour. For MAJOR bumps, maintain a 24-hour rollback-ready window where the previous version remains staged.

5. **Deployment creates a permanent audit record** in the registry, regardless of outcome.

---

## Rollback Procedure

Rollbacks are **not reversions** — they are forward-changes back to a prior state. This preserves the audit trail.

### When to roll back

Rollback is warranted when any of the following occur after a deployment:
- Key behavioral metric degrades >5% within the monitoring window
- Safety evaluation regression detected
- Critical bug in downstream integration traced to the prompt change
- Explicit request from a system owner with stated justification

### Rollback process

1. **Authorize**: A rollback for a MINOR or MAJOR deployment requires approval from a prompt owner (the deployer may authorize their own rollback).
2. **Record**: Create a rollback record with: `prompt_name`, `rolled_back_from`, `rolled_back_to`, `reason`, `authorized_by`, `timestamp`.
3. **Execute**: Update `active_version` in the registry to the target rollback version.
4. **Notify**: Post to #ai-systems-changes with the rollback reason.
5. **Follow up**: Within 5 business days, the original proposer must either close the original proposal as "abandoned" or submit a revised proposal that addresses the rollback reason.

### Rollback is not blame

The audit trail records what happened, not fault. The goal is operational safety, not accountability theater.

---

## Naming Conventions

### Prompt files

```
prompts/versions/{prompt-name}-v{MAJOR}.{MINOR}.{PATCH}.md
```

Examples:
- `prompts/versions/system-v1.0.0.md`
- `prompts/versions/tool-search-v2.1.0.md`
- `prompts/versions/eval-rubric-v1.0.1.md`

Rules:
- Lowercase, hyphen-separated names only.
- No spaces, underscores, or camelCase in prompt names.
- The `v` prefix on the version is mandatory.
- Files are **immutable once deployed**. Do not edit a deployed version file — create a new version.

### Proposal files

```
prompts/versions/{prompt-name}-v{MAJOR}.{MINOR}.{PATCH}.proposal.yaml
```

The proposal file lives alongside the version file it proposes. Once deployed or rejected, the proposal file is retained as-is for archival.

### Prompt names in the registry

Prompt names in `registry.yaml` must:
- Be lowercase and hyphen-separated
- Be unique within the registry
- Be stable (renaming a prompt is a MAJOR change requiring full approval)

---

## Prohibited Practices

The following are policy violations:

1. **Editing a deployed version file in-place.** Deployed versions are immutable. Create a new version.
2. **Deploying without a registered proposal.** Ad-hoc deploys bypass the audit trail.
3. **Approving your own MINOR or MAJOR proposal.** Self-approval is only permitted for PATCH changes.
4. **Backdating approvals.** All timestamps must reflect actual approval time.
5. **Deploying an expired approval.** Check the 14-day expiry before deployment.
6. **Misclassifying a MAJOR change as MINOR to avoid review overhead.** This is a serious policy violation, not just a process error.
7. **Storing prompt text anywhere other than `prompts/versions/`.** Inline prompt strings in application code are prohibited for registered prompts.

---

## Rationale: Why Prompts Are Production Artifacts

A prompt encodes the behavior contract of an AI system. It determines:
- What the model will and won't do
- How it formats responses
- What safety behaviors it exhibits
- How it interprets ambiguous inputs

These are not aesthetic choices — they have real consequences for users, for downstream systems, and for the safety posture of the AI. A prompt change that removes a constraint is functionally equivalent to removing a guard clause from production code. It should receive at least the same scrutiny.

The cost of this process is real: it adds friction to prompt iteration. That friction is intentional. Fast iteration on prompts is valuable during development. Undisciplined changes to production prompts are a reliability and safety risk. This policy is designed to protect production without blocking development — by requiring rigor in the deployment pathway, not in the development process.

---

## Amendments to This Policy

Changes to this policy document follow the same MAJOR bump approval requirement as changes to safety-relevant prompts: two approvers, both from the Prompt Reviewer group. Policy changes take effect 5 business days after approval to allow the team to absorb the change.
