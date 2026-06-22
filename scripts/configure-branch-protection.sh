#!/usr/bin/env bash
# Configure branch protection on main to require the Test workflow (RFC-007).
# Run once by a repo admin after the Test workflow has completed at least once.
#
# Usage:
#   ./scripts/configure-branch-protection.sh
#   CHECK_CONTEXT="Test / test" ./scripts/configure-branch-protection.sh
#
# Requires: gh CLI authenticated with admin access to the repository.

set -euo pipefail

BRANCH="${BRANCH:-main}"
# GitHub Actions check context; override if your repo uses a different name.
# Find it under: repo Settings → Branches → required status checks, or a merged PR.
CHECK_CONTEXT="${CHECK_CONTEXT:-test}"

REPO="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

echo "Configuring branch protection for ${REPO}:${BRANCH}"
echo "Required status check: ${CHECK_CONTEXT}"

gh api \
  --method PUT \
  "repos/${REPO}/branches/${BRANCH}/protection" \
  --input - <<EOF
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      {"context": "${CHECK_CONTEXT}"}
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF

echo "Done. Verify at: https://github.com/${REPO}/settings/branches"
