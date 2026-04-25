# CLAUDE.md

## Project

Python 3.11+ prompt change control system. Dependencies: `pydantic`, `pyyaml`.

- **`src/change_control.py`** — Core classes: `PromptVersion`, `ChangeProposal`, `ChangeControlSystem`
- **`src/diff.py`** — Diff logic between prompt versions
- **`src/approvals.py`** — Approval workflow
- **`prompts/versions/`** — Versioned prompt files (markdown)
- **`prompts/registry.yaml`** — Source of truth for active versions

## Commands

```bash
python -m pytest tests/                    # Run tests
python examples/propose_change.py          # Propose a prompt change
python examples/rollback.py                # Rollback a prompt version
```

## Change control workflow

1. Edit a new version file: `prompts/versions/<id>-v<X.Y.Z>.md`
2. Create a proposal YAML: `prompts/versions/<id>-v<X.Y.Z>.proposal.yaml`
3. Get approval (see POLICY.md for who can approve)
4. Update `prompts/registry.yaml` to mark the new version as active

## Conventions

- Prompt files are **append-only**: never edit a file that has `approval_status: approved`
- Version numbers follow semver: breaking changes bump major, additions bump minor, fixes bump patch
- Every change needs a rationale — "improved tone" is not sufficient; explain the specific behavioral delta
- The `registry.yaml` is the source of truth for what's active — don't deploy what isn't in the registry

## Agent notes

**IMPORTANT**: You must NOT edit prompts in `prompts/versions/` that already have `approval_status: approved`. Create a new version file instead. When proposing a change, always compute a diff against the current active version to include in the proposal. Read `POLICY.md` before making any change to understand approval requirements.
