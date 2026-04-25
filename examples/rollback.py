"""
rollback.py — CLI for rolling back a prompt to a previous version.

A rollback is NOT a silent revert. It is a forward-change that restores a
prior version, creates an audit record, and notifies the team. The history
is never rewritten.

Usage:
    python examples/rollback.py \\
        --prompt system \\
        --to-version 1.0.0 \\
        --reason "v1.1.0 caused citation over-hedging in 18% of sessions" \\
        --authorized-by alice@example.com \\
        --executed-by deploy-bot

This script will:
  1. Verify the target version exists and is not the current active version.
  2. Display a summary of the rollback (current → target) for confirmation.
  3. Prompt for interactive confirmation (unless --yes is passed).
  4. Create a RollbackRecord and append it to the audit log.
  5. Update the registry's active_version.
  6. Print a post-rollback summary.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.change_control import ChangeControlSystem, RollbackRecord


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Roll back a prompt to a prior version.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--prompt", required=True, help="Prompt name (e.g. 'system')")
    p.add_argument(
        "--to-version",
        required=True,
        dest="to_version",
        help="Version to roll back to (must be in registry)",
    )
    p.add_argument("--reason", required=True, help="Why you are rolling back (required for audit)")
    p.add_argument(
        "--authorized-by",
        required=True,
        dest="authorized_by",
        help="Who authorized this rollback (email or handle)",
    )
    p.add_argument(
        "--executed-by",
        default=None,
        dest="executed_by",
        help="Who is executing the rollback (defaults to authorized-by)",
    )
    p.add_argument(
        "--related-proposal",
        default=None,
        dest="related_proposal",
        help="ID of the proposal that introduced the version being rolled back from",
    )
    p.add_argument(
        "--registry",
        default="prompts/registry.yaml",
        help="Path to registry.yaml",
    )
    p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip interactive confirmation",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would happen without making changes",
    )
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def confirm(prompt: str) -> bool:
    """Prompt for y/n confirmation. Returns True if user confirms."""
    while True:
        response = input(f"{prompt} [y/N]: ").strip().lower()
        if response in ("y", "yes"):
            return True
        if response in ("n", "no", ""):
            return False
        print("Please enter 'y' or 'n'.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    executed_by = args.executed_by or args.authorized_by

    # TODO: replace with ChangeControlSystem.from_registry(args.registry)
    # For now, load the registry YAML manually for display.
    import yaml  # type: ignore[import]

    registry_path = Path(args.registry)
    if not registry_path.exists():
        print(f"ERROR: Registry not found at {registry_path}", file=sys.stderr)
        return 1

    with registry_path.open() as f:
        registry_data = yaml.safe_load(f)

    prompt_data = registry_data.get("prompts", {}).get(args.prompt)
    if not prompt_data:
        print(f"ERROR: Prompt {args.prompt!r} not found in registry.", file=sys.stderr)
        return 1

    current_version = prompt_data["active_version"]

    if current_version == args.to_version:
        print(
            f"ERROR: {args.prompt!r} is already at version {args.to_version}. "
            "Nothing to roll back.",
            file=sys.stderr,
        )
        return 1

    # Verify target version is known
    known_versions = [v["version"] for v in prompt_data.get("versions", [])]
    if args.to_version not in known_versions:
        print(
            f"ERROR: Version {args.to_version!r} is not in the registry for {args.prompt!r}.\n"
            f"Known versions: {', '.join(known_versions)}",
            file=sys.stderr,
        )
        return 1

    # Display rollback summary
    print("\n" + "=" * 70)
    print("ROLLBACK SUMMARY")
    print("=" * 70)
    print(f"  Prompt:          {args.prompt}")
    print(f"  Current version: {current_version}")
    print(f"  Rolling back to: {args.to_version}")
    print(f"  Reason:          {args.reason}")
    print(f"  Authorized by:   {args.authorized_by}")
    print(f"  Executed by:     {executed_by}")
    if args.related_proposal:
        print(f"  Related proposal: {args.related_proposal}")
    print("=" * 70)

    if args.dry_run:
        print("\n[DRY RUN] No changes made.")
        return 0

    # Confirm
    if not args.yes:
        if not confirm(
            f"\nRoll back {args.prompt!r} from {current_version} to {args.to_version}?"
        ):
            print("Rollback cancelled.")
            return 0

    # Execute rollback
    # TODO: replace with ccs.rollback(...)
    # For now, demonstrate the rollback record and registry update.

    import datetime
    import uuid

    rollback_record = RollbackRecord(
        id=f"rollback-{uuid.uuid4().hex[:8]}",
        prompt_name=args.prompt,
        rolled_back_from=current_version,
        rolled_back_to=args.to_version,
        reason=args.reason,
        authorized_by=args.authorized_by,
        executed_by=executed_by,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        related_proposal_id=args.related_proposal,
    )

    # Update registry in-memory
    prompt_data["active_version"] = args.to_version

    # Mark rolled-back-from version as deprecated, target as active
    for v in prompt_data.get("versions", []):
        if v["version"] == current_version:
            v["status"] = "deprecated"
            v["deprecated_at"] = rollback_record.timestamp.isoformat()
        if v["version"] == args.to_version:
            v["status"] = "active"
            v["deprecated_at"] = None

    # Append to rollback_history
    if "rollback_history" not in prompt_data:
        prompt_data["rollback_history"] = []
    prompt_data["rollback_history"].append(rollback_record.to_dict())

    # Append to audit_log
    if "audit_log" not in registry_data:
        registry_data["audit_log"] = []
    registry_data["audit_log"].append({
        "event": "rollback",
        "prompt_name": args.prompt,
        "version": args.to_version,
        "rolled_back_from": current_version,
        "actor": executed_by,
        "authorized_by": args.authorized_by,
        "timestamp": rollback_record.timestamp.isoformat(),
        "reason": args.reason,
        "rollback_id": rollback_record.id,
    })

    # Persist registry
    with registry_path.open("w") as f:
        yaml.dump(registry_data, f, default_flow_style=False, sort_keys=False)

    print(f"\nRollback complete.")
    print(f"  Rollback ID: {rollback_record.id}")
    print(f"  {args.prompt!r} is now active at version {args.to_version}.")
    print(f"\nRemember to:")
    print(f"  1. Post to #ai-systems-changes with the rollback reason.")
    print(f"  2. Within 5 business days, close or revise the original proposal.")
    print(f"     Proposal ID: {args.related_proposal or '(look up in registry)'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
