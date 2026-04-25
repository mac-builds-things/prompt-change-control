#!/usr/bin/env bash
set -euo pipefail

input=$(cat)
file=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('path','') or d.get('file_path','') or '')" 2>/dev/null || echo "")

# Only check files in prompts/versions/
if echo "$file" | grep -q "prompts/versions/"; then
  # Check if the file itself has approval_status: approved
  if [ -f "$file" ] && grep -q "approval_status: approved" "$file" 2>/dev/null; then
    echo '{
      "permission": "deny",
      "user_message": "This prompt version is approved and immutable. Create a new version file instead.",
      "agent_message": "Blocked: cannot edit an approved prompt version. Create prompts/versions/<id>-v<next>.md as a new version."
    }'
    exit 0
  fi

  # Check sibling .proposal.yaml for approval_status: approved
  proposal="${file%.md}.proposal.yaml"
  if [ -f "$proposal" ] && grep -q "approval_status: approved" "$proposal" 2>/dev/null; then
    echo '{
      "permission": "deny",
      "user_message": "This prompt version is approved and immutable. Create a new version file instead.",
      "agent_message": "Blocked: cannot edit an approved prompt version. Create prompts/versions/<id>-v<next>.md as a new version."
    }'
    exit 0
  fi
fi

echo '{ "permission": "allow" }'
exit 0
