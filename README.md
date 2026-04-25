# prompt-change-control

> Version-controlled prompt management with approval gates, rollback, and audit history — because prompts are code.

---

## Why This Exists

Prompts are the most consequential configuration in an AI system, and they're routinely treated as afterthoughts.

In most teams today:
- A prompt gets tweaked in a Notion doc, a Google Sheet, or worse — directly in code as a string literal.
- Nobody knows who changed it, when, or why.
- A "small tweak" causes a production agent to start refusing valid requests, hallucinating structured data, or breaking downstream parsers.
- There's no rollback. There's no diff. There's no audit log.

This is the same class of problem that database migrations solved a decade ago. You wouldn't modify a production schema by running a raw `ALTER TABLE` without a review process, a migration file, and the ability to roll back. Prompts deserve the same discipline.

`prompt-change-control` is a lightweight system that enforces exactly that:

- **Every prompt change is a proposal**, with a stated rationale and risk assessment.
- **Changes are reviewed and approved** before deployment — by a human, by policy, or by automated evaluation gates.
- **Every deployed version is archived** with a semantic version tag.
- **Rollback is a first-class operation**, not a manual text-editing exercise.
- **The audit trail is durable** — you can always answer "what prompt was running on Tuesday at 2pm, and who approved it?"

---

## What Makes It Interesting

### Semantic Versioning for Prompts

Prompts follow `MAJOR.MINOR.PATCH` semantics with prompt-specific meaning:

| Bump | Meaning |
|------|---------|
| `PATCH` | Typo fix, whitespace, no behavioral change expected |
| `MINOR` | Additive change — new instructions, clarified behavior, backward-compatible |
| `MAJOR` | Breaking change — persona shift, constraint removal, output format change |

A `MAJOR` bump requires a heavier approval process: two approvers, mandatory evaluation run, and a staged rollout window.

### Diff Views

Diffs aren't just line-by-line text diffs. The system computes:
- **Structural diffs**: Did the prompt's section headings change?
- **Constraint diffs**: Were any explicit prohibitions added or removed?
- **Tone diffs**: Lexical analysis flagging shifts in formality, assertiveness, or hedging.
- **Length delta**: Significant length changes often signal behavioral changes.

### Approval Workflows

Proposals move through states: `DRAFT → PENDING_REVIEW → APPROVED → DEPLOYED → ARCHIVED`.

Approval requirements scale with risk level (derived from version bump type and affected prompt scope). See [POLICY.md](POLICY.md) for the full ruleset.

### Rollback

Rolling back is intentional and audited. You don't just revert a file — you create a rollback record explaining why, which version you're returning to, and who authorized it. This keeps the audit trail intact and prevents silent state.

---

## Quickstart

```bash
# Install dependencies
pip install -r requirements.txt

# Propose a change to an existing prompt
python examples/propose_change.py \
  --prompt system \
  --from-version 1.1.0 \
  --to-file prompts/versions/system-v1.2.0.md \
  --summary "Add structured output instructions" \
  --rationale "Downstream parser now expects JSON blocks" \
  --risk low

# Review pending proposals
python -c "
from src.change_control import ChangeControlSystem
ccs = ChangeControlSystem.from_registry('prompts/registry.yaml')
for p in ccs.pending_proposals():
    print(p.summary_table())
"

# Approve a proposal
python -c "
from src.change_control import ChangeControlSystem
ccs = ChangeControlSystem.from_registry('prompts/registry.yaml')
ccs.approve(proposal_id='prop-2025-001', approver='alice@example.com', notes='LGTM, tested on eval set')
"

# Deploy an approved proposal
python -c "
from src.change_control import ChangeControlSystem
ccs = ChangeControlSystem.from_registry('prompts/registry.yaml')
ccs.deploy(proposal_id='prop-2025-001', deployed_by='deploy-bot')
"

# Roll back to a previous version
python examples/rollback.py \
  --prompt system \
  --to-version 1.0.0 \
  --reason "v1.1.0 caused refusal rate to spike 12% on eval set" \
  --authorized-by alice@example.com
```

---

## Example Workflow

Here's a complete end-to-end scenario: a team needs to update their assistant's system prompt to add structured output instructions.

### 1. Propose

```bash
# Write the new prompt version
vim prompts/versions/system-v1.2.0.md

# Submit a proposal
python examples/propose_change.py --prompt system --to-version 1.2.0 \
  --summary "Add JSON output mode instructions" \
  --rationale "API consumers now expect parseable JSON in tool-call responses" \
  --risk medium
```

This creates `prompts/versions/system-v1.2.0.proposal.yaml` and registers the proposal.

### 2. Review

A reviewer runs:

```bash
python -c "
from src.diff import PromptDiff
d = PromptDiff.from_versions('system', '1.1.0', '1.2.0')
d.render()
"
```

Output:
```
──────────── system: 1.1.0 → 1.2.0 ────────────
MINOR bump | +47 lines | +2 sections

[ADDED] ## Output Format
  + When the user requests structured data, respond with valid JSON...
  + Do not wrap JSON in markdown fences unless explicitly asked...

[MODIFIED] ## Tone and Style
  - Keep responses concise and direct.
  + Keep responses concise and direct. For structured outputs, omit preamble.

Risk indicators: none flagged
────────────────────────────────────────────────
```

### 3. Approve

```bash
python -c "
from src.change_control import ChangeControlSystem
ccs = ChangeControlSystem.from_registry('prompts/registry.yaml')
ccs.approve('prop-2025-002', approver='alice@example.com', notes='Eval passed, 0% regression on refusal rate')
"
```

### 4. Deploy

```bash
python -c "
from src.change_control import ChangeControlSystem
ccs = ChangeControlSystem.from_registry('prompts/registry.yaml')
ccs.deploy('prop-2025-002', deployed_by='deploy-bot')
"
```

The registry updates `system`'s active version to `1.2.0`. Your application reads the active version from the registry at startup.

### 5. Rollback (if needed)

```bash
python examples/rollback.py \
  --prompt system \
  --to-version 1.1.0 \
  --reason "JSON mode instructions caused 8% hallucination increase on structured eval" \
  --authorized-by alice@example.com
```

The rollback is recorded as its own audit event — the history is never rewritten.

---

## Directory Structure

```
prompt-change-control/
├── src/
│   ├── change_control.py   # Core system: proposals, approvals, deployment
│   ├── diff.py             # Prompt diff computation and rendering
│   └── approvals.py        # Approval workflow state machine
├── prompts/
│   ├── registry.yaml       # Source of truth: active versions, all prompt metadata
│   └── versions/           # Immutable versioned prompt files + proposal YAMLs
├── examples/
│   ├── propose_change.py   # CLI for submitting proposals
│   └── rollback.py         # CLI for rolling back
├── tests/
│   └── test_change_control.py
├── POLICY.md               # Governance rules, approval requirements, naming conventions
├── requirements.txt
└── pyproject.toml
```

---

## What This Demonstrates

This project is a proof-of-concept for **prompt engineering discipline** — the idea that prompt management in production AI systems should borrow the same change-management patterns that software engineering developed over decades:

- **Immutability**: deployed prompt versions are never edited in place.
- **Traceability**: every change has a proposer, a rationale, an approver, and a timestamp.
- **Reversibility**: rollback is fast, explicit, and audited.
- **Risk-tiered governance**: not every change needs the same weight of approval.
- **Separation of concerns**: the registry (what's active) is separate from the archive (what exists).

This pattern scales from a single developer managing their own prompts to a team where multiple people share ownership of high-stakes prompts deployed in production agents.

---

## Honest Status

This is a **portfolio/reference implementation**, not a production-ready library. The Python modules are well-structured stubs with full type hints and docstrings — the scaffolding is real, the storage backends and eval integrations are left as exercises.

What's real:
- The governance model (POLICY.md is genuine)
- The data model (classes and YAML schemas)
- The versioned prompt examples (showing a realistic change)
- The workflow design

What's stubbed:
- File I/O and YAML persistence in the core classes
- The diff rendering (structure is there, difflib integration is a TODO)
- Eval integrations (marked as extension points)

---

## License

MIT
