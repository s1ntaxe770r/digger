#!/usr/bin/env bash
# Print a k8s-style "Dependencies" section (Added/Removed) by diffing
# go.mod requires between two refs.
#
# Usage: scripts/diff-go-deps.bash OLD_REF NEW_REF
#
# Only considers the go.mod files for the main OSS product
# (root, cli, backend, libs) - EE/taco/drift have their own release lines.
# A version bump shows up as the old version being removed and the new
# version being added. Identical module/version pairs across the four
# go.mod files are deduped.

set -euo pipefail

OLD_REF="${1:?usage: diff-go-deps.bash OLD_REF NEW_REF}"
NEW_REF="${2:?usage: diff-go-deps.bash OLD_REF NEW_REF}"

GOMOD_FILES=(go.mod libs/go.mod backend/go.mod cli/go.mod)

# Emit "module\tversion" pairs from a go.mod's require blocks/lines.
parse_gomod() {
  local ref="$1" path="$2"
  git show "${ref}:${path}" 2>/dev/null | awk '
    /^require[ \t]*\(/ { inblock=1; next }
    inblock && /^\)/    { inblock=0; next }
    inblock && NF>=2    { print $1"\t"$2 }
    !inblock && /^require[ \t]/ && NF>=3 { print $2"\t"$3 }
  '
}

old_all=""
new_all=""
for f in "${GOMOD_FILES[@]}"; do
  old_all+=$(parse_gomod "$OLD_REF" "$f")$'\n'
  new_all+=$(parse_gomod "$NEW_REF" "$f")$'\n'
done

old_set=$(printf '%s' "$old_all" | sort -u)
new_set=$(printf '%s' "$new_all" | sort -u)

added=$(comm -13 <(printf '%s\n' "$old_set") <(printf '%s\n' "$new_set") | sed '/^$/d')
removed=$(comm -23 <(printf '%s\n' "$old_set") <(printf '%s\n' "$new_set") | sed '/^$/d')

echo "### Dependencies"
echo

echo "#### Added"
echo
if [ -z "$added" ]; then
  echo "_Nothing has changed._"
else
  printf '%s\n' "$added" | awk -F'\t' '{print "- `" $1 "`: `" $2 "`"}'
fi
echo

echo "#### Removed"
echo
if [ -z "$removed" ]; then
  echo "_Nothing has changed._"
else
  printf '%s\n' "$removed" | awk -F'\t' '{print "- `" $1 "`: `" $2 "`"}'
fi
