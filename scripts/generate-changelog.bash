#!/usr/bin/env bash
# Generate CHANGELOG.md from GitHub releases (vMAJOR.MINOR.PATCH tags only).
#
# Usage: scripts/generate-changelog.bash [LIMIT]
#   LIMIT - number of most recent releases to include (default: 30)
#
# Requires: gh CLI, jq

set -euo pipefail

REPO="${REPO:-diggerhq/digger}"
LIMIT="${1:-30}"
OUT="${OUT:-CHANGELOG.md}"

{
  echo "# Changelog"
  echo
  echo "Generated from [GitHub releases](https://github.com/${REPO}/releases) via \`scripts/generate-changelog.bash\`."
  echo
} > "$OUT"

gh release list --repo "$REPO" --limit 1000 --json tagName,isDraft,isPrerelease \
  -q '.[] | select(.isDraft==false and .isPrerelease==false) | .tagName' \
  | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' \
  | sort -rV \
  | head -n "$LIMIT" \
  | while read -r tag; do
      gh release view "$tag" --repo "$REPO" --json tagName,publishedAt,body,url \
        | jq -r '
            "## [" + .tagName + "](" + .url + ") - " + (.publishedAt | split("T")[0]) + "\n\n"
            + (
                .body
                | gsub("\r"; "")
                | split("\n")
                | map(if test("^#+ ") then "#" + . else . end)
                | join("\n")
              )
            + "\n"
          '
    done >> "$OUT"

echo "Wrote $OUT" >&2
