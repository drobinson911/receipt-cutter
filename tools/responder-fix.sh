#!/usr/bin/env bash
# responder-fix.sh — the ONLY way the forge ops responder may land a receipt-cutter code fix.
#   tools/responder-fix.sh "<one-line description of the bug and fix>"
# Takes the uncommitted edits in this repo (receipt_bot/, tools/, tests/ only), runs the full
# test suite, commits them on a new branch responder/<UTC stamp>, and merges that branch into
# master ONLY if every test passes (exit codes + an explicit " passed" / no "failed" check).
# Red tests → the branch is kept unmerged for Donald, master untouched, exit 1. Never pushes.
set -euo pipefail
cd "$(dirname "$0")/.."
msg="${1:?usage: responder-fix.sh \"description\"}"
[ "$(git rev-parse --abbrev-ref HEAD)" = master ] || { echo "not on master — refusing"; exit 2; }
changed=$(git status --porcelain | awk '{print $2}')
[ -n "$changed" ] || { echo "no changes to commit"; exit 2; }
bad=$(echo "$changed" | grep -v -E '^(receipt_bot/|tools/|tests/py/)' || true)
[ -z "$bad" ] || { echo "refusing: changes outside receipt_bot/ tools/ tests/py/: $bad"; exit 2; }

run_tests() {
  local out rc
  set +e
  out=$("$HOME/bin/capped" -m 2G -n "receipt-tests-$$" -- .venv/bin/python -m pytest -q tests/py 2>&1); rc=$?
  set -e
  echo "$out" | tail -5
  [ $rc -eq 0 ] && echo "$out" | grep -q -E '[0-9]+ passed' && ! echo "$out" | grep -q -E '[0-9]+ (failed|error)'
}

branch="responder/$(date -u +%Y%m%dT%H%M%SZ)"
git checkout -q -b "$branch"
git add -- $changed
git commit -q -m "responder fix: $msg" -m "Landed by the forge ops responder via tools/responder-fix.sh (tests green before merge)." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
if run_tests; then
  git checkout -q master
  git merge -q --no-ff "$branch" -m "Merge $branch: $msg"
  echo "MERGED $branch into master (tests green). Not pushed."
else
  git checkout -q master
  echo "TESTS RED — $branch left unmerged for Donald; master unchanged."
  exit 1
fi
