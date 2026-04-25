# prompt-change-control

**Prompts are code. Treat them like it.**

In most teams today, the most consequential configuration in an AI system is managed with the rigor of a sticky note. A prompt gets tweaked in a Notion doc, a Google Sheet, or worse — directly in code as a string literal buried in a function call. Nobody knows who changed it, when, or why. A "small tweak" causes a production agent to start refusing valid requests, hallucinating structured data, or breaking downstream parsers. There's no rollback. There's no diff. There's no audit log.

This is the same class of problem that database migrations solved a decade ago. You wouldn't modify a production schema by running a raw `ALTER TABLE` without a review process, a migration file, and the ability to roll back. The argument for doing the same with prompts is identical — they're stateful, they affect behavior in ways that are hard to predict, and the blast radius of a bad change can be large and silent. The only thing missing was the tooling.

`prompt-change-control` is a lightweight system that enforces exactly that discipline. Every prompt change is a proposal with a stated rationale and risk level. Changes are reviewed and approved before deployment — by a human, by policy, or by automated evaluation gates. Every deployed version is archived with a semantic version tag. Rollback is a first-class operation, not a manual text-editing exercise. And the audit trail is durable: you can always answer "what prompt was running on Tuesday at 2pm, and who approved it?"

## The workflow

The full cycle from idea to production looks like this:

1. **Propose** — write the new prompt version and submit a proposal with a summary, rationale, and risk assessment (`low` / `medium` / `high`). This creates a versioned proposal YAML and registers it in the registry.
2. **Review** — a reviewer runs the diff tool, which computes structural diffs, constraint diffs (were any explicit prohibitions added or removed?), tone shifts, and length deltas. Significant changes surface automatically.
3. **Approve** — proposals move through states: `DRAFT → PENDING_REVIEW → APPROVED`. Approval requirements scale with risk level. A `MAJOR` version bump — persona shift, constraint removal, output format change — requires two approvers and a mandatory eval run. A `PATCH` typo fix does not.
4. **Deploy** — the registry updates the active version. Your application reads the active version from the registry at startup; nothing else changes.
5. **Rollback** — if something goes wrong, rollback is explicit and audited. You don't revert a file — you create a rollback record: which version you're returning to, why, and who authorized it. The history is never rewritten.

## What's in the repo

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

## Getting started

```bash
pip install -r requirements.txt
python examples/propose_change.py --help
```

The `examples/` directory walks through a complete scenario: proposing a change to add structured output instructions, reviewing the diff, approving, deploying, and rolling back when the eval results come back worse.

## See also

[POLICY.md](POLICY.md) contains the full change governance rules: version bump semantics, approval tier requirements, naming conventions, and rollback authorization rules.

> Note: This is a portfolio/reference implementation — the governance model, data model, and workflow design are complete; file I/O persistence and eval integrations are left as extension points.
