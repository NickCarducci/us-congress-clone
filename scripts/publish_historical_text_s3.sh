#!/usr/bin/env bash
set -euo pipefail
congress="${1:?Congress is required}"
[[ "$congress" =~ ^[0-9]{1,3}$ ]] || exit 1
: "${SCYTALE_HOST:?}" "${SCYTALE_SSH_KEY:?}" "${GITHUB_REPOSITORY:?}" "${GITHUB_RUN_ID:?}" "${GITHUB_RUN_ATTEMPT:?}"
[[ "$GITHUB_RUN_ID" =~ ^[0-9]+$ && "$GITHUB_RUN_ATTEMPT" =~ ^[0-9]+$ ]] || exit 1
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT
mkdir "$temp/bundles"
printf '%s\n' "$SCYTALE_SSH_KEY" > "$temp/key"
chmod 600 "$temp/key"
gh release download "legislation-$congress" --repo "$GITHUB_REPOSITORY" --pattern "text-$congress-*.json.gz" --dir "$temp/bundles"
count=$(find "$temp/bundles" -type f -name '*.json.gz' | wc -l | tr -d ' ')
[ "$count" -gt 0 ] || { echo "No historical text bundles found" >&2; exit 1; }
remote="/tmp/populist-historical-text-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT-$congress"
ssh -i "$temp/key" -o StrictHostKeyChecking=accept-new "ubuntu@$SCYTALE_HOST" "mkdir -p '$remote'"
rsync -az -4 -e "ssh -i $temp/key -o StrictHostKeyChecking=accept-new" "$temp/bundles/" "ubuntu@$SCYTALE_HOST:$remote/"
ssh -i "$temp/key" -o StrictHostKeyChecking=accept-new "ubuntu@$SCYTALE_HOST" \
  "aws s3 sync '$remote/' 's3://populist-legislative-text-410937487237/federal/$congress/bundles/' --only-show-errors && rm -rf '$remote'"
echo "Published $count bundles for Congress $congress"
