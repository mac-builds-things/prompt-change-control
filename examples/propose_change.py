"""
propose_change.py — CLI for submitting a prompt change proposal.

Usage:
    python examples/propose_change.py \\
        --prompt system \\
        --from-version 1.1.0 \\
        --to-file prompts/versions/system-v1.2.0.md \\
        --to-version 1.2.0 \\
        --bump minor \\
        --author alice@example.com \\
        --summary "Add structured output instructions" \\
        --rationale "Downstream parser now expects JSON blocks" \\
        --risk low

The script will:
  1. Validate that the target version file exists.
  2. Compute and display the diff between the current and new version.
  3. Generate a .proposal.yaml file alongside the new version file.
  4. Register the proposal in the change-control system.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is on the path when running from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.change_control import ChangeControlSystem, ChangeProposal, RiskLevel, VersionBump
from src.diff import PromptDiff


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Submit a prompt change proposal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--prompt", required=True, help="Prompt name (e.g. 'system')")
    p.add_argument("--from-version", required=True, dest="from_version", help="Current active version")
    p.add_argument("--to-version", required=True, dest="to_version", help="Proposed new version")
    p.add_argument(
        "--to-file",
        required=True,
        dest="to_file",
        type=Path,
        help="Path to the new version's prompt file",
    )
    p.add_argument(
        "--bump",
        required=True,
        choices=["patch", "minor", "major"],
        help="Version bump type (patch/minor/major)",
    )
    p.add_argument("--author", required=True, help="Your email or handle")
    p.add_argument("--summary", required=True, help="≤140 char change summary")
    p.add_argument("--rationale", required=True, help="Why this change is needed")
    p.add_argument(
        "--risk",
        required=True,
        choices=["none", "low", "medium", "high"],
        help="Risk level",
    )
    p.add_argument("--risk-description", default="", dest="risk_description")
    p.add_argument(
        "--registry",
        default="prompts/registry.yaml",
        help="Path to registry.yaml",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show diff and proposal YAML without writing anything",
    )
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Validate inputs
    if not args.to_file.exists():
        print(f"ERROR: Target file not found: {args.to_file}", file=sys.stderr)
        return 1

    if len(args.summary) > 140:
        print(
            f"ERROR: Summary is {len(args.summary)} chars; max is 140.",
            file=sys.stderr,
        )
        return 1

    # Load registry and current version
    # TODO: replace with ChangeControlSystem.from_registry(args.registry)
    # For now, load the from-version file directly for diff display.
    from_file = Path(f"prompts/versions/{args.prompt}-v{args.from_version}.md")
    if not from_file.exists():
        print(f"ERROR: Current version file not found: {from_file}", file=sys.stderr)
        return 1

    before_text = from_file.read_text()
    after_text = args.to_file.read_text()

    # Show diff
    print("\n" + "=" * 80)
    print("PROMPT DIFF PREVIEW")
    print("=" * 80)
    result = PromptDiff.compute(
        args.prompt,
        args.from_version,
        args.to_version,
        before_text,
        after_text,
    )
    print(result.render())

    # Suggest bump type if it differs from claimed
    print("\n")

    if args.dry_run:
        print("[DRY RUN] Would create proposal. No files written.")
        return 0

    # Build proposal
    import datetime
    year = datetime.datetime.now().year
    # TODO: auto-increment proposal ID from registry
    proposal_id = f"prop-{year}-XXX"

    proposal = ChangeProposal(
        id=proposal_id,
        prompt_name=args.prompt,
        from_version=args.from_version,
        to_version=args.to_version,
        version_bump=VersionBump(args.bump),
        author=args.author,
        summary=args.summary,
        rationale=args.rationale,
        risks=RiskLevel(args.risk),
        risk_description=args.risk_description,
    )

    # Write proposal YAML
    import yaml  # type: ignore[import]

    proposal_path = args.to_file.parent / f"{args.prompt}-v{args.to_version}.proposal.yaml"
    with proposal_path.open("w") as f:
        yaml.dump(proposal.to_dict(), f, default_flow_style=False, sort_keys=False)

    print(f"Proposal written to: {proposal_path}")
    print(f"Proposal ID: {proposal_id}")
    print("\nNext steps:")
    print(f"  1. Review the diff above.")
    print(f"  2. Share {proposal_path} with a reviewer.")
    print(f"  3. Once approved, deploy with:")
    print(f"     python -c \"from src.change_control import ChangeControlSystem; ...")
    print(f"     ccs.deploy('{proposal_id}', deployed_by='your-handle')\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
